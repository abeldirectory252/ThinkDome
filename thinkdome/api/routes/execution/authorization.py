"""Shared authorization checks for sandbox-scoped execution routes."""

from fastapi import HTTPException, Request, status


from thinkdome.security.identity.core import is_admin_role


def authorize_sandbox_access(request: Request, sandbox_id: str, user: dict):
    """Return the sandbox if the authenticated principal owns it.

    Route-level authentication alone is insufficient: sandbox IDs are
    attacker-controlled object references and must be tenant-scoped here.
    """
    role = str(user.get("role", "")).upper()
    if is_admin_role(role):
        return None
    if user.get("token_type") == "sandbox_access" and user.get("sandbox_id") != sandbox_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sandbox not found")
    principal = str(user.get("workspace_id", user.get("username", ""))).strip().lower()

    lifecycle = getattr(request.app.state, "lifecycle_service", None)
    info = None
    if lifecycle:
        info = lifecycle._sandboxes.get(sandbox_id)
        if info and str(getattr(info, "owner", "")).strip().lower() == principal:
            return info

    db = getattr(request.app.state, "db_service", None)
    record = db.get_sandbox(sandbox_id) if db else None
    if record and str(record.get("owner", "")).strip().lower() == principal:
        return info or record

    if not info and not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sandbox not found")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden: you do not own this sandbox")
