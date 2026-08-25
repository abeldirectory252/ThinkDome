"""Idempotent background reaper process for automated sandbox TTL and idle timeout teardown."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from thinkdome.sandbox.core.lifecycle_service import SandboxLifecycleService, SandboxState

logger = logging.getLogger(__name__)


class SandboxReaper:
    """Scans managed sandboxes on a fixed interval and tears down expired/idle sandboxes cleanly."""

    def __init__(
        self,
        lifecycle_service: SandboxLifecycleService,
        db_service=None,
        check_interval_sec: float = 15.0,
        default_idle_timeout_sec: float = 600.0,  # 10m idle timeout default
    ) -> None:
        self.lifecycle_service = lifecycle_service
        self.db_service = db_service
        self.check_interval_sec = check_interval_sec
        self.default_idle_timeout_sec = default_idle_timeout_sec
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

    async def start(self) -> None:
        """Start the background reaper loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._reaper_loop())
        logger.info(f"🌾 Sandbox Reaper process started (interval={self.check_interval_sec}s)")

    async def stop(self) -> None:
        """Stop the reaper process cleanly."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("🌾 Sandbox Reaper process stopped")

    async def _reaper_loop(self) -> None:
        """Main periodic loop."""
        while self._running:
            try:
                await self.reap_expired_sandboxes()
            except Exception as e:
                logger.error(f"Error in sandbox reaper cycle: {e}")
            await asyncio.sleep(self.check_interval_sec)

    async def reap_expired_sandboxes(self) -> int:
        """Scan and destroy sandboxes that have exceeded TTL or idle threshold.
        Returns the number of sandboxes destroyed in this pass.
        """
        now = time.time()
        sandboxes = list(self.lifecycle_service._sandboxes.values())
        reaped_count = 0

        for info in sandboxes:
            if info.state in (SandboxState.DESTROYED, SandboxState.TERMINATED):
                continue

            is_expired = info.expires_at is not None and now >= info.expires_at
            idle_timeout = float(info.metadata.get("idle_timeout_sec", self.default_idle_timeout_sec))
            is_idle_expired = (now - info.last_active_at) >= idle_timeout

            if is_expired or is_idle_expired:
                reason = "TTL expiration" if is_expired else "Idle timeout"
                logger.info(
                    f"⏰ Reaping sandbox {info.sandbox_id} (owner={info.owner}, purpose={info.purpose}, reason={reason})"
                )

                try:
                    # 1. Capture stdout/stderr/artifacts to audit log before teardown
                    if self.db_service:
                        try:
                            self.db_service.log_audit(
                                actor="reaper_process",
                                action="sandbox_reaped",
                                details={
                                    "sandbox_id": info.sandbox_id,
                                    "owner": info.owner,
                                    "purpose": info.purpose,
                                    "reason": reason,
                                    "container_id": info.container_id,
                                    "created_at": datetime.fromtimestamp(info.created_at, tz=timezone.utc).isoformat(),
                                }
                            )
                            # Update the authoritative ORM sandbox record.
                            self.db_service.update_sandbox_status(info.sandbox_id, "destroyed")
                        except Exception as dbe:
                            logger.warning(f"Reaper DB audit logging note for {info.sandbox_id}: {dbe}")

                    # 2. Destroy sandbox instance and release resources
                    await self.lifecycle_service.destroy_sandbox(info.sandbox_id, actor=f"reaper:{reason}")
                    
                    # 3. Unregister from in-memory tracking
                    self.lifecycle_service.unregister_sandbox(info.sandbox_id)
                    reaped_count += 1
                except Exception as e:
                    logger.error(f"Idempotent retry error during teardown of sandbox {info.sandbox_id}: {e}")

        return reaped_count
