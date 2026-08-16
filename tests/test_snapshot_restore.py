"""Tests for Snapshot & Restore Backtracking Engine and SDK context manager."""

import pytest
import tempfile
from pathlib import Path

from thinkdome import Sandbox
from thinkdome.sandbox.snapshots.service import SnapshotService
from thinkdome.core.config import Settings


def test_snapshot_service_create_and_restore():
    """Test SnapshotService creation, list, restore, and delete."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        settings = Settings()
        settings.SNAPSHOT_STORAGE_DIR = str(Path(tmp_dir) / "snapshots")
        svc = SnapshotService(settings)

        # Create workspace with sample file
        ws_dir = Path(tmp_dir) / "workspace"
        ws_dir.mkdir(parents=True, exist_ok=True)
        (ws_dir / "state.txt").write_text("initial state v1", encoding="utf-8")

        # 1. Take snapshot
        meta = svc.create_snapshot(
            sandbox_id="sb_test_01",
            tag="checkpoint_1",
            description="Initial state before agent modification",
            workspace_path=str(ws_dir),
        )

        snap_id = meta["snapshot_id"]
        assert snap_id.startswith("snap_")
        assert meta["tag"] == "checkpoint_1"

        # 2. Modify workspace
        (ws_dir / "state.txt").write_text("agent modified state v2", encoding="utf-8")
        (ws_dir / "new_file.txt").write_text("unwanted mutation", encoding="utf-8")
        assert (ws_dir / "state.txt").read_text() == "agent modified state v2"

        # 3. Restore snapshot
        res = svc.restore_snapshot(
            sandbox_id="sb_test_01",
            snapshot_id=snap_id,
            workspace_path=str(ws_dir),
        )

        assert res["success"]
        assert (ws_dir / "state.txt").read_text() == "initial state v1"
        assert not (ws_dir / "new_file.txt").exists()

        # 4. List and lineage
        snaps = svc.list_snapshots(sandbox_id="sb_test_01")
        assert len(snaps) == 1
        lineage = svc.get_lineage(sandbox_id="sb_test_01")
        assert len(lineage["nodes"]) == 1

        # 5. Delete snapshot
        assert svc.delete_snapshot(snap_id)


def test_sandbox_sdk_snapshot_and_backtrack():
    """Test Sandbox Python SDK snapshot and backtrack methods."""
    with Sandbox(backend="subprocess") as dome:
        dome.write_file("agent_step.txt", "step 1 completed")

        # Create snapshot checkpoint
        snap_id = dome.snapshot(tag="step_1")
        assert snap_id

        # Perform bad mutation
        dome.write_file("agent_step.txt", "step 2 failed with error")
        assert dome.read_file("agent_step.txt") == "step 2 failed with error"

        # Backtrack back to previous checkpoint
        restored = dome.backtrack()
        assert restored
        assert dome.read_file("agent_step.txt") == "step 1 completed"
