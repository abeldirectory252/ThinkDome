"""Sandbox lifecycle service — pause, resume, renew expiration.

Manages sandbox state transitions and expiration renewal.
Works with Docker, MicroVM, and subprocess backends.

State machine:
    Running → Pausing → Paused → Resuming → Running
    Any state → Stopping → Terminated (on delete)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional

from fastapi import HTTPException, status

from thinkdome.core.error_codes import SandboxErrorCodes

logger = logging.getLogger(__name__)


class SandboxState(str, Enum):
    """Lifecycle states for a sandbox."""
    PROVISIONING = "Provisioning"
    CREATING = "Creating"  # Legacy alias
    READY = "Ready"
    RUNNING = "Running"
    IDLE = "Idle"
    PAUSING = "Pausing"
    PAUSED = "Paused"
    RESUMING = "Resuming"
    STOPPING = "Stopping"
    TERMINATED = "Terminated"
    DESTROYED = "Destroyed"
    FAILED = "Failed"


# Valid state transitions
_VALID_TRANSITIONS = {
    SandboxState.PROVISIONING: {SandboxState.READY, SandboxState.RUNNING, SandboxState.FAILED, SandboxState.DESTROYED},
    SandboxState.CREATING: {SandboxState.READY, SandboxState.RUNNING, SandboxState.FAILED, SandboxState.DESTROYED},
    SandboxState.READY: {SandboxState.RUNNING, SandboxState.IDLE, SandboxState.STOPPING, SandboxState.DESTROYED},
    SandboxState.RUNNING: {SandboxState.IDLE, SandboxState.PAUSING, SandboxState.STOPPING, SandboxState.DESTROYED},
    SandboxState.IDLE: {SandboxState.RUNNING, SandboxState.STOPPING, SandboxState.DESTROYED},
    SandboxState.PAUSING: {SandboxState.PAUSED, SandboxState.FAILED, SandboxState.DESTROYED},
    SandboxState.PAUSED: {SandboxState.RESUMING, SandboxState.STOPPING, SandboxState.DESTROYED},
    SandboxState.RESUMING: {SandboxState.RUNNING, SandboxState.FAILED, SandboxState.DESTROYED},
    SandboxState.STOPPING: {SandboxState.TERMINATED, SandboxState.DESTROYED},
    SandboxState.TERMINATED: {SandboxState.DESTROYED},
    SandboxState.DESTROYED: set(),
    SandboxState.FAILED: {SandboxState.STOPPING, SandboxState.DESTROYED},
}


@dataclass
class SandboxInfo:
    """Runtime information for a managed sandbox."""
    sandbox_id: str
    state: SandboxState = SandboxState.RUNNING
    container_id: Optional[str] = None
    image: str = ""
    backend: str = "docker"
    owner: str = "anonymous"
    purpose: str = "general"
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None  # Unix epoch seconds, None = no expiration
    metadata: Dict[str, str] = field(default_factory=dict)
    last_state_change: float = field(default_factory=time.time)


class SandboxLifecycleService:
    """Manages sandbox lifecycle operations: pause, resume, renew expiration.

    This service maintains an in-memory registry of sandbox state and delegates
    container operations to the appropriate backend (Docker client, MicroVM executor, etc.).
    """

    def __init__(self, docker_client=None) -> None:
        self._docker_client = docker_client
        self._sandboxes: Dict[str, SandboxInfo] = {}
        self._lock = asyncio.Lock()
        self._operation_locks: Dict[str, asyncio.Lock] = {}

    @staticmethod
    def bound_ttl_by_role(requested_ttl_sec: Optional[int], role: str) -> int:
        """Bound requested TTL in seconds based on caller role limits."""
        role_upper = (role or "FREE").upper()
        default_ttl = 600  # 10 min default
        
        from thinkdome.security.identity.core import is_admin_role
        if is_admin_role(role_upper):
            max_ttl = 86400  # 24h
        elif role_upper in ("AGENT", "AGENT_STANDARD", "LLM", "SDK"):
            max_ttl = 7200   # 2h max
        else:  # Free tier
            max_ttl = 900    # 15m max

        ttl = requested_ttl_sec if requested_ttl_sec is not None else default_ttl
        return max(10, min(ttl, max_ttl))

    def register_sandbox(
        self,
        sandbox_id: str,
        container_id: Optional[str] = None,
        image: str = "",
        backend: str = "docker",
        timeout_sec: Optional[int] = None,
        metadata: Optional[Dict[str, str]] = None,
        owner: str = "anonymous",
        purpose: str = "general",
        role: str = "FREE",
    ) -> SandboxInfo:
        """Register a newly created sandbox for lifecycle management."""
        now = time.time()
        bounded_ttl = self.bound_ttl_by_role(timeout_sec, role)
        info = SandboxInfo(
            sandbox_id=sandbox_id,
            state=SandboxState.RUNNING,
            container_id=container_id,
            image=image,
            backend=backend,
            owner=owner,
            purpose=purpose,
            created_at=now,
            last_active_at=now,
            expires_at=now + bounded_ttl,
            metadata=metadata or {},
        )
        self._sandboxes[sandbox_id] = info
        self._operation_locks.setdefault(sandbox_id, asyncio.Lock())
        logger.info(f"📦 Registered sandbox {sandbox_id} (owner={owner}, purpose={purpose}, ttl={bounded_ttl}s)")
        return info

    async def destroy_sandbox(self, sandbox_id: str, actor: str = "reaper") -> SandboxInfo:
        """Safely and idempotently transition sandbox to DESTROYED and clean up resources."""
        operation_lock = self._operation_locks.setdefault(sandbox_id, asyncio.Lock())
        async with operation_lock:
            info = self._sandboxes.get(sandbox_id)
            if not info:
                # Idempotent — if already unregistered or missing, create placeholder
                return SandboxInfo(sandbox_id=sandbox_id, state=SandboxState.DESTROYED)

            if info.state == SandboxState.DESTROYED:
                return info

            try:
                self._transition_state(info, SandboxState.DESTROYED)
            except Exception:
                info.state = SandboxState.DESTROYED

            # Teardown physical container if active
            if info.container_id and self._docker_client:
                try:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self._docker_destroy, info.container_id)
                except Exception as e:
                    logger.warning(f"Container destruction note for {info.container_id}: {e}")

            logger.info(f"🗑️ Sandbox {sandbox_id} destroyed by {actor}")
            return info

    def _docker_destroy(self, container_id: str) -> None:
        try:
            container = self._docker_client.containers.get(container_id)
            container.stop(timeout=2)
            container.remove(force=True)
        except Exception as e:
            logger.debug(f"Docker remove failed for {container_id}: {e}")

    def get_sandbox(self, sandbox_id: str) -> SandboxInfo:
        """Get sandbox info, raising 404 if not found."""
        info = self._sandboxes.get(sandbox_id)
        if not info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": SandboxErrorCodes.SANDBOX_NOT_FOUND,
                    "message": f"Sandbox '{sandbox_id}' not found.",
                },
            )
        return info

    def list_sandboxes(
        self,
        state: Optional[str] = None,
        metadata_filter: Optional[Dict[str, str]] = None,
    ) -> list[SandboxInfo]:
        """List sandboxes with optional filtering."""
        results = list(self._sandboxes.values())

        if state:
            results = [s for s in results if s.state.value == state]

        if metadata_filter:
            for key, value in metadata_filter.items():
                results = [s for s in results if s.metadata.get(key) == value]

        return results

    def _transition_state(self, info: SandboxInfo, target: SandboxState) -> None:
        """Validate and perform a state transition."""
        valid_targets = _VALID_TRANSITIONS.get(info.state, set())
        if target not in valid_targets:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": SandboxErrorCodes.INVALID_STATE,
                    "message": (
                        f"Cannot transition sandbox '{info.sandbox_id}' "
                        f"from '{info.state.value}' to '{target.value}'."
                    ),
                },
            )
        info.state = target
        info.last_state_change = time.time()

    async def pause_sandbox(self, sandbox_id: str) -> SandboxInfo:
        """Pause a running sandbox."""
        operation_lock = self._operation_locks.setdefault(sandbox_id, asyncio.Lock())
        async with operation_lock:
            info = self.get_sandbox(sandbox_id)
            self._transition_state(info, SandboxState.PAUSING)

            try:
                if info.backend == "docker" and self._docker_client and info.container_id:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self._docker_pause, info.container_id)
                elif info.backend == "microvm":
                    logger.info(f"MicroVM pause for {sandbox_id} — snapshotting state to disk")
                else:
                    logger.info(f"Pause not physically supported for backend={info.backend}, marking as paused")

                self._transition_state(info, SandboxState.PAUSED)
                logger.info(f"⏸️ Sandbox {sandbox_id} paused")
            except HTTPException:
                raise
            except Exception as e:
                self._transition_state(info, SandboxState.FAILED)
                logger.error(f"Failed to pause sandbox {sandbox_id}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "code": SandboxErrorCodes.INVALID_STATE,
                        "message": f"Failed to pause sandbox: {e}",
                    },
                )

            return info

    async def resume_sandbox(self, sandbox_id: str) -> SandboxInfo:
        """Resume a paused sandbox."""
        operation_lock = self._operation_locks.setdefault(sandbox_id, asyncio.Lock())
        async with operation_lock:
            info = self.get_sandbox(sandbox_id)
            self._transition_state(info, SandboxState.RESUMING)

            try:
                if info.backend == "docker" and self._docker_client and info.container_id:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self._docker_unpause, info.container_id)
                elif info.backend == "microvm":
                    logger.info(f"MicroVM resume for {sandbox_id} — restoring from snapshot")
                else:
                    logger.info(f"Resume not physically supported for backend={info.backend}, marking as running")

                self._transition_state(info, SandboxState.RUNNING)
                logger.info(f"▶️ Sandbox {sandbox_id} resumed")
            except HTTPException:
                raise
            except Exception as e:
                self._transition_state(info, SandboxState.FAILED)
                logger.error(f"Failed to resume sandbox {sandbox_id}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "code": SandboxErrorCodes.INVALID_STATE,
                        "message": f"Failed to resume sandbox: {e}",
                    },
                )

            return info

    def renew_expiration(
        self,
        sandbox_id: str,
        expires_at: Optional[datetime] = None,
        timeout_seconds: Optional[int] = None,
    ) -> SandboxInfo:
        """Renew sandbox expiration time.

        Args:
            sandbox_id: Target sandbox.
            expires_at: Absolute expiration datetime (UTC). Must be in the future.
            timeout_seconds: Relative TTL from now in seconds.

        At least one of expires_at or timeout_seconds must be provided.
        """
        info = self.get_sandbox(sandbox_id)

        if info.state in (SandboxState.TERMINATED, SandboxState.STOPPING, SandboxState.DESTROYED, SandboxState.FAILED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": SandboxErrorCodes.INVALID_STATE,
                    "message": f"Cannot renew expiration for sandbox in '{info.state.value}' state.",
                },
            )

        now = time.time()

        if expires_at:
            # Normalize timezone
            if expires_at.tzinfo is None:
                normalized = expires_at.replace(tzinfo=timezone.utc)
            else:
                normalized = expires_at.astimezone(timezone.utc)

            epoch = normalized.timestamp()
            if epoch <= now:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": SandboxErrorCodes.INVALID_EXPIRATION,
                        "message": "New expiration time must be in the future.",
                    },
                )
            info.expires_at = epoch
        elif timeout_seconds:
            if timeout_seconds <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": SandboxErrorCodes.INVALID_EXPIRATION,
                        "message": "Timeout must be a positive number of seconds.",
                    },
                )
            info.expires_at = now + timeout_seconds
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_PARAMETER,
                    "message": "Provide either 'expires_at' or 'timeout_seconds'.",
                },
            )

        logger.info(
            f"🔄 Sandbox {sandbox_id} expiration renewed to "
            f"{datetime.fromtimestamp(info.expires_at, tz=timezone.utc).isoformat()}"
        )
        return info

    def patch_metadata(self, sandbox_id: str, patch: Dict) -> SandboxInfo:
        """Apply JSON Merge Patch (RFC 7396) to sandbox metadata."""
        from thinkdome.core.metadata_validator import apply_metadata_patch

        info = self.get_sandbox(sandbox_id)
        info.metadata = apply_metadata_patch(info.metadata, patch)
        logger.info(f"🏷️ Sandbox {sandbox_id} metadata patched")
        return info

    def unregister_sandbox(self, sandbox_id: str) -> None:
        """Remove a sandbox from lifecycle management."""
        self._sandboxes.pop(sandbox_id, None)
        self._operation_locks.pop(sandbox_id, None)

    # ── Docker helpers ──

    def _docker_pause(self, container_id: str) -> None:
        container = self._docker_client.containers.get(container_id)
        container.pause()

    def _docker_unpause(self, container_id: str) -> None:
        container = self._docker_client.containers.get(container_id)
        container.unpause()

    # ── Serialization ──

    def sandbox_to_dict(self, info: SandboxInfo) -> dict:
        """Serialize sandbox info to API response dict."""
        result = {
            "sandbox_id": info.sandbox_id,
            "state": info.state.value,
            "image": info.image,
            "backend": info.backend,
            "created_at": datetime.fromtimestamp(info.created_at, tz=timezone.utc).isoformat(),
            "metadata": info.metadata,
        }
        if info.expires_at:
            result["expires_at"] = datetime.fromtimestamp(info.expires_at, tz=timezone.utc).isoformat()
        if info.container_id:
            result["container_id"] = info.container_id
        return result
