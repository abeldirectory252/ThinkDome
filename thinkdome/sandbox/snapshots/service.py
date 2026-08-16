"""Snapshot & Backtrack Service for ThinkDome.

Manages point-in-time state snapshotting, workspace state preservation,
and tree-based workflow backtracking for AI agent execution steps.

When a MicroVM executor is available, snapshots include real Cloud Hypervisor
VM-level state (memory + CPU registers + stateful disk) via the CHV snapshot
API. Otherwise, falls back to workspace file-copy snapshots.
"""

from __future__ import annotations

import os
import time
import json
import uuid
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from thinkdome.core.config import Settings, get_settings
from thinkdome.apps.sandbox.models import Snapshot

logger = logging.getLogger(__name__)


class SnapshotService:
    """Service managing MicroVM and Sandbox state snapshots and backtracking workflows."""

    def __init__(self, settings: Optional[Settings] = None, microvm_executor=None) -> None:
        self.settings = settings or get_settings()
        self.storage_dir = Path(getattr(self.settings, "SNAPSHOT_STORAGE_DIR", "./storage/snapshots"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # In-memory index for fast lookup (fallback when DB is offline)
        self._snapshots: Dict[str, Dict[str, Any]] = {}
        self._latest_by_sandbox: Dict[str, str] = {}
        # Optional MicroVM executor for real VM-level snapshots
        self._microvm_executor = microvm_executor

    def create_snapshot(
        self,
        sandbox_id: str,
        tag: Optional[str] = None,
        description: str = "",
        owner: str = "anonymous",
        workspace_path: Optional[str] = None,
        files: Optional[Dict[str, bytes]] = None,
    ) -> Dict[str, Any]:
        """Create a state snapshot checkpoint for a sandbox.

        Args:
            sandbox_id: ID or name of the active sandbox.
            tag: Optional human tag (e.g., "step_1", "pre-execution").
            description: Detailed notes or reason for checkpoint.
            owner: User or agent owner.
            workspace_path: Local filesystem path of the active workspace.
            files: Dict of file path -> content bytes to snapshot explicitly.

        Returns:
            Dict containing snapshot metadata.
        """
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        timestamp = time.time()
        parent_id = self._latest_by_sandbox.get(sandbox_id, "")

        snap_dir = self.storage_dir / snapshot_id
        snap_dir.mkdir(parents=True, exist_ok=True)
        files_dir = snap_dir / "workspace_files"
        files_dir.mkdir(parents=True, exist_ok=True)

        snapshot_files = {}

        # 1. Snapshot workspace directory contents if provided
        if workspace_path and Path(workspace_path).exists():
            ws = Path(workspace_path)
            for p in ws.rglob("*"):
                if p.is_file():
                    rel = str(p.relative_to(ws)).replace("\\", "/")
                    dest = files_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(p, dest)
                        snapshot_files[rel] = str(dest)
                    except Exception as e:
                        logger.warning(f"Could not backup workspace file {rel} for snapshot {snapshot_id}: {e}")

        # 2. Snapshot explicit files if provided
        if files:
            for rel, content in files.items():
                dest = files_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, str):
                    content = content.encode("utf-8")
                dest.write_bytes(content)
                snapshot_files[rel] = str(dest)

        # 3. VM-level snapshot via MicroVM executor (if available)
        vm_snapshot_id = None
        if self._microvm_executor:
            try:
                from thinkdome.sandbox.executors.microvm_executor import MicroVMExecutor
                if isinstance(self._microvm_executor, MicroVMExecutor) and self._microvm_executor.instances:
                    # Snapshot the first running VM
                    vm_id = next(iter(self._microvm_executor.instances))
                    vm_snapshot_id = f"vmsnap_{snapshot_id}"
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # Schedule as task; best-effort in sync context
                            asyncio.ensure_future(
                                self._microvm_executor.snapshot_vm(vm_id, vm_snapshot_id)
                            )
                        else:
                            loop.run_until_complete(
                                self._microvm_executor.snapshot_vm(vm_id, vm_snapshot_id)
                            )
                    except RuntimeError:
                        new_loop = asyncio.new_event_loop()
                        new_loop.run_until_complete(
                            self._microvm_executor.snapshot_vm(vm_id, vm_snapshot_id)
                        )
                        new_loop.close()
                    logger.info(f"VM-level snapshot '{vm_snapshot_id}' created for sandbox '{sandbox_id}'.")
            except Exception as e:
                logger.warning(f"VM-level snapshot failed (workspace files still saved): {e}")
                vm_snapshot_id = None

        meta = {
            "snapshot_id": snapshot_id,
            "sandbox_id": sandbox_id,
            "name": tag or f"Snapshot {snapshot_id[:8]}",
            "tag": tag or "checkpoint",
            "description": description,
            "created_at": timestamp,
            "state_dir": str(snap_dir),
            "parent_snapshot_id": parent_id,
            "owner": owner,
            "file_count": len(snapshot_files),
            "vm_snapshot_id": vm_snapshot_id,
        }

        # Write metadata file inside snapshot directory
        (snap_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        # Record in memory
        self._snapshots[snapshot_id] = meta
        self._latest_by_sandbox[sandbox_id] = snapshot_id

        # Persist to database via ORM if available
        try:
            snap_obj = Snapshot(
                snapshot_id=snapshot_id,
                sandbox_id=sandbox_id,
                name=meta["name"],
                tag=meta["tag"],
                description=description,
                created_at=timestamp,
                state_dir=str(snap_dir),
                parent_snapshot_id=parent_id,
                owner=owner,
            )
            snap_obj.save()
        except Exception as e:
            logger.debug(f"Snapshot ORM database save skipped: {e}")

        logger.info(f"Created snapshot '{snapshot_id}' for sandbox '{sandbox_id}' with {len(snapshot_files)} files.")
        return meta

    def restore_snapshot(
        self,
        sandbox_id: str,
        snapshot_id: str,
        workspace_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Restore a sandbox state to a given snapshot checkpoint.

        Args:
            sandbox_id: Target sandbox ID.
            snapshot_id: ID of the snapshot checkpoint to restore.
            workspace_path: Workspace directory path to restore files into.

        Returns:
            Dict containing restore result status and target files.
        """
        meta = self._snapshots.get(snapshot_id)
        if not meta:
            # Try reading from disk metadata
            snap_dir = self.storage_dir / snapshot_id
            meta_file = snap_dir / "metadata.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                self._snapshots[snapshot_id] = meta
            else:
                raise ValueError(f"Snapshot '{snapshot_id}' not found.")

        snap_dir = Path(meta["state_dir"])
        files_dir = snap_dir / "workspace_files"
        restored_files = {}

        if workspace_path and files_dir.exists():
            ws = Path(workspace_path)
            ws.mkdir(parents=True, exist_ok=True)

            # Clear active workspace before restoring snapshot files
            for item in ws.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)

            # Copy snapshot files back into workspace
            for p in files_dir.rglob("*"):
                if p.is_file():
                    rel = str(p.relative_to(files_dir)).replace("\\", "/")
                    dest = ws / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dest)
                    restored_files[rel] = p.read_bytes()

        self._latest_by_sandbox[sandbox_id] = snapshot_id

        # Attempt VM-level restore if a vm_snapshot_id is present in metadata
        vm_restored = False
        vm_snapshot_id = meta.get("vm_snapshot_id")
        if vm_snapshot_id and self._microvm_executor:
            try:
                from thinkdome.sandbox.executors.microvm_executor import MicroVMExecutor
                if isinstance(self._microvm_executor, MicroVMExecutor):
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.ensure_future(
                                self._microvm_executor.restore_vm(
                                    f"restored-{sandbox_id}", vm_snapshot_id
                                )
                            )
                        else:
                            loop.run_until_complete(
                                self._microvm_executor.restore_vm(
                                    f"restored-{sandbox_id}", vm_snapshot_id
                                )
                            )
                    except RuntimeError:
                        new_loop = asyncio.new_event_loop()
                        new_loop.run_until_complete(
                            self._microvm_executor.restore_vm(
                                f"restored-{sandbox_id}", vm_snapshot_id
                            )
                        )
                        new_loop.close()
                    vm_restored = True
                    logger.info(f"VM-level restore from '{vm_snapshot_id}' succeeded.")
            except Exception as e:
                logger.warning(f"VM-level restore failed (workspace files still restored): {e}")

        logger.info(f"Restored sandbox '{sandbox_id}' back to snapshot checkpoint '{snapshot_id}'.")
        return {
            "success": True,
            "sandbox_id": sandbox_id,
            "snapshot_id": snapshot_id,
            "restored_files_count": len(restored_files),
            "restored_files": restored_files,
            "restored_at": time.time(),
            "vm_restored": vm_restored,
        }

    def list_snapshots(
        self,
        sandbox_id: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all active snapshots, optionally filtered by sandbox_id or owner."""
        snaps = list(self._snapshots.values())

        # Also load from disk if memory is empty
        if not snaps and self.storage_dir.exists():
            for p in self.storage_dir.iterdir():
                meta_file = p / "metadata.json"
                if meta_file.exists():
                    try:
                        m = json.loads(meta_file.read_text(encoding="utf-8"))
                        self._snapshots[m["snapshot_id"]] = m
                        snaps.append(m)
                    except Exception:
                        pass

        if sandbox_id:
            snaps = [s for s in snaps if s.get("sandbox_id") == sandbox_id]
        if owner:
            snaps = [s for s in snaps if s.get("owner") == owner]

        snaps.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return snaps

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot checkpoint and release storage."""
        meta = self._snapshots.pop(snapshot_id, None)
        snap_dir = self.storage_dir / snapshot_id
        if snap_dir.exists():
            try:
                shutil.rmtree(snap_dir)
            except Exception as e:
                logger.warning(f"Error removing snapshot dir {snap_dir}: {e}")
        return True

    def backtrack_to_last(self, sandbox_id: str, workspace_path: Optional[str] = None) -> Dict[str, Any]:
        """Backtrack sandbox state to its most recent snapshot checkpoint."""
        latest_id = self._latest_by_sandbox.get(sandbox_id)
        if not latest_id:
            snaps = self.list_snapshots(sandbox_id=sandbox_id)
            if snaps:
                latest_id = snaps[0]["snapshot_id"]

        if not latest_id:
            raise ValueError(f"No previous snapshot checkpoints found for sandbox '{sandbox_id}'.")

        return self.restore_snapshot(sandbox_id=sandbox_id, snapshot_id=latest_id, workspace_path=workspace_path)

    def get_lineage(self, sandbox_id: str) -> Dict[str, Any]:
        """Build snapshot tree/lineage graph for visualization and MCTS backtracking."""
        snaps = self.list_snapshots(sandbox_id=sandbox_id)
        nodes = []
        edges = []

        for s in snaps:
            nodes.append({
                "id": s["snapshot_id"],
                "label": s["name"],
                "tag": s["tag"],
                "created_at": s["created_at"],
                "file_count": s.get("file_count", 0),
            })
            if s.get("parent_snapshot_id"):
                edges.append({
                    "from": s["parent_snapshot_id"],
                    "to": s["snapshot_id"],
                })

        return {"sandbox_id": sandbox_id, "nodes": nodes, "edges": edges}
