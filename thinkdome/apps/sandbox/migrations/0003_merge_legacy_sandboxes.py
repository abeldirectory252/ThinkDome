"""Merge legacy DatabaseService sandbox rows into the authoritative ORM table."""

from sqlalchemy import inspect, text


def up(db) -> None:
    inspector = inspect(db.bind)
    if not inspector.has_table("sandboxes"):
        return

    from thinkdome.apps.sandbox.models import Sandbox

    legacy_rows = db.execute(text("SELECT * FROM sandboxes")).mappings().all()
    for row in legacy_rows:
        sandbox_id = row.get("sandbox_id")
        if not sandbox_id or Sandbox.get(sandbox_id):
            continue
        status = str(row.get("status") or "Running").lower()
        status = {"active": "Running", "running": "Running", "destroyed": "Destroyed", "stopped": "Stopped"}.get(status, "Created")
        runtime = row.get("backend_type") or "docker"
        if runtime not in {"docker", "kubernetes", "subprocess", "microvm"}:
            runtime = "docker"
        Sandbox(
            id=sandbox_id,
            name=row.get("name") or sandbox_id,
            owner=row.get("owner") or "system",
            status=status,
            runtime=runtime,
            memory_limit=int(row.get("memory_mb") or 256),
            cpu_limit=float(row.get("cpu_cores") or 1.0),
            gpu_limit=int(row.get("gpu_count") or 0),
            network_enabled=bool(row.get("network_enabled")),
            storage_quota_mb=int(row.get("storage_quota_mb") or 10240),
        ).save()

    db.execute(text("DROP TABLE sandboxes"))
    db.commit()


def down(db) -> None:
    """Legacy table restoration is intentionally unsupported."""
    return None
