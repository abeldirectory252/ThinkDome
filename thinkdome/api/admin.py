"""Admin, API Key, and filesystem backend management endpoints."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel, Field

from thinkdome.api.dependencies import (
    get_auth_service,
    get_request_log_service,
    get_current_admin,
    get_current_user
)
from thinkdome.services.auth_service import AuthService
from thinkdome.services.request_log_service import RequestLogService

router = APIRouter(tags=["admin"])

# In-memory filesystem backend registry (placeholder)
_fs_backends: dict[str, dict] = {
    "local": {
        "fs_id": "local",
        "type": "local",
        "path": "./storage",
        "status": "healthy",
    }
}

class CreateKeyRequest(BaseModel):
    display_name: str = Field(..., max_length=50, example="My LLM Client")
    token_type: str = Field("LLM", description="ADMIN or LLM")
    expires_at: Optional[str] = Field(None, description="ISO 8601 string or null for no expiration")

# â”€â”€ API KEY ENDPOINTS â”€â”€

@router.get("/keys")
async def list_keys(
    auth_svc: AuthService = Depends(get_auth_service),
    _admin: dict = Depends(get_current_admin)
):
    """List all registered API keys (masked tokens)."""
    return auth_svc.list_api_keys()

@router.post("/keys", status_code=201)
async def create_key(
    req: CreateKeyRequest,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
    _admin: dict = Depends(get_current_admin)
):
    """Create a new API Key (returns full token once)."""
    return auth_svc.create_api_key(
        display_name=req.display_name,
        token_type=req.token_type,
        expires_at=req.expires_at,
        creator=_admin.get("username", "admin"),
        actor_ip=request.client.host if request.client else "unknown"
    )

@router.post("/keys/{key_id}/revoke")
async def revoke_key(
    key_id: str,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
    _admin: dict = Depends(get_current_admin)
):
    """Revoke an API key."""
    success = auth_svc.revoke_api_key(
        key_id=key_id,
        actor=_admin.get("username", "admin"),
        actor_ip=request.client.host if request.client else "unknown"
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key not found."
        )
    return {"status": "success", "message": "API Key revoked successfully."}

# â”€â”€ INSPECTION LOGS ENDPOINTS â”€â”€

@router.get("/logs")
async def get_logs(
    limit: int = 100,
    log_svc: RequestLogService = Depends(get_request_log_service),
    _admin: dict = Depends(get_current_admin)
):
    """Retrieve execution request logs."""
    return log_svc.get_logs(limit=limit)

@router.post("/logs/clear")
async def clear_logs(
    request: Request,
    log_svc: RequestLogService = Depends(get_request_log_service),
    _admin: dict = Depends(get_current_admin)
):
    """Clear all request logs."""
    log_svc.clear_logs(
        actor=_admin.get("username", "admin"),
        actor_ip=request.client.host if request.client else "unknown"
    )
    return {"status": "success", "message": "All request logs cleared."}

# â”€â”€ AUDIT LOGS ENDPOINTS â”€â”€

@router.get("/audits")
async def get_audits(
    limit: int = 100,
    auth_svc: AuthService = Depends(get_auth_service),
    _admin: dict = Depends(get_current_admin)
):
    """Retrieve system audit trails."""
    return auth_svc.db_service.fetch_all(
        "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
    )

# â”€â”€ FILESYSTEMS ENDPOINTS (PROTECTED) â”€â”€

@router.get("/filesystems")
async def list_filesystems(_admin: dict = Depends(get_current_admin)):
    """List configured filesystem backends."""
    return list(_fs_backends.values())

@router.post("/filesystems", status_code=201)
async def register_filesystem(config: dict, _admin: dict = Depends(get_current_admin)):
    """Register new filesystem backend."""
    fs_id = config.get("fs_id", str(len(_fs_backends)))
    config["fs_id"] = fs_id
    _fs_backends[fs_id] = config
    return config

@router.put("/filesystems/{fs_id}")
async def update_filesystem(fs_id: str, config: dict, _admin: dict = Depends(get_current_admin)):
    if fs_id not in _fs_backends:
        raise HTTPException(status_code=404, detail="Filesystem backend not found")
    _fs_backends[fs_id].update(config)
    return _fs_backends[fs_id]

@router.delete("/filesystems/{fs_id}")
async def delete_filesystem(fs_id: str, _admin: dict = Depends(get_current_admin)):
    if fs_id not in _fs_backends:
        raise HTTPException(status_code=404, detail="Filesystem backend not found")
    del _fs_backends[fs_id]
    return {"status": "deregistered", "fs_id": fs_id}

@router.post("/filesystems/{fs_id}/health")
async def check_filesystem_health(fs_id: str, _admin: dict = Depends(get_current_admin)):
    if fs_id not in _fs_backends:
        raise HTTPException(status_code=404, detail="Filesystem backend not found")
    return {"fs_id": fs_id, "status": "healthy"}

@router.get("/storage/quota")
async def get_storage_quota(_admin: dict = Depends(get_current_admin)):
    """Get global storage quota usage."""
    return {"total_mb": 10000, "used_mb": 0, "available_mb": 10000}

@router.put("/storage/quota/{user_id}")
async def update_user_quota(user_id: str, quota: dict, _admin: dict = Depends(get_current_admin)):
    """Adjust user quota limits."""
    return {"user_id": user_id, "quota_mb": quota.get("quota_mb", 100)}


# ── SANDBOX PROVISIONING ENDPOINTS ──

class CreateSandboxRequest(BaseModel):
    name: str = Field(..., max_length=100, example="ML Sandbox")
    memory_mb: int = Field(256)
    cpu_cores: float = Field(1.0)
    timeout_sec: int = Field(30)
    network_enabled: bool = Field(False)

@router.get("/sandboxes")
async def list_sandboxes(
    auth_svc: AuthService = Depends(get_auth_service),
    user: dict = Depends(get_current_user)
):
    """List sandboxes. Admins see all; users see their own."""
    owner = None if user.get("role") == "ADMIN" else user.get("username")
    return auth_svc.db_service.list_sandboxes(owner=owner)

@router.post("/sandboxes", status_code=201)
async def create_sandbox(
    req: CreateSandboxRequest,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
    user: dict = Depends(get_current_user)
):
    """Create a new sandboxed environment with specific CPU/RAM allocations."""
    import uuid
    sandbox_id = f"sb_{uuid.uuid4().hex[:12]}"
    
    # Calculate running cost based on specifications:
    # $0.01 per 128MB RAM/hr + $0.02 per vCPU/hr + $0.005 for network
    cost = (req.memory_mb / 128) * 0.01 + req.cpu_cores * 0.02 + (0.005 if req.network_enabled else 0)
    
    res = auth_svc.db_service.create_sandbox(
        sandbox_id=sandbox_id,
        name=req.name,
        owner=user.get("username", "anonymous"),
        memory_mb=req.memory_mb,
        cpu_cores=req.cpu_cores,
        timeout_sec=req.timeout_sec,
        network_enabled=req.network_enabled,
        cost_per_hour=cost
    )
    
    # Log audit event
    auth_svc.db_service.log_audit(
        actor=user.get("username", "anonymous"),
        action="create_sandbox",
        ip_address=request.client.host if request.client else "unknown",
        details={
            "sandbox_id": sandbox_id,
            "name": req.name,
            "memory_mb": req.memory_mb,
            "cpu_cores": req.cpu_cores,
            "cost_per_hour": cost
        }
    )
    return res

@router.post("/sandboxes/{sandbox_id}/toggle")
async def toggle_sandbox(
    sandbox_id: str,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
    user: dict = Depends(get_current_user)
):
    """Toggle sandbox active vs stopped state."""
    sb = auth_svc.db_service.get_sandbox(sandbox_id)
    if not sb:
        raise HTTPException(status_code=404, detail="Sandbox not found.")
        
    # Check permissions (only owner or admin)
    if user.get("role") != "ADMIN" and sb["owner"] != user.get("username"):
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this sandbox.")
        
    new_status = "stopped" if sb["status"] == "active" else "active"
    auth_svc.db_service.update_sandbox_status(sandbox_id, new_status)
    
    # Log audit event
    auth_svc.db_service.log_audit(
        actor=user.get("username", "anonymous"),
        action="toggle_sandbox",
        ip_address=request.client.host if request.client else "unknown",
        details={"sandbox_id": sandbox_id, "status": new_status}
    )
    return {"status": "success", "sandbox_id": sandbox_id, "new_status": new_status}

@router.delete("/sandboxes/{sandbox_id}")
async def delete_sandbox(
    sandbox_id: str,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
    user: dict = Depends(get_current_user)
):
    """Terminate and delete a sandbox environment."""
    sb = auth_svc.db_service.get_sandbox(sandbox_id)
    if not sb:
        raise HTTPException(status_code=404, detail="Sandbox not found.")
        
    # Check permissions (only owner or admin)
    if user.get("role") != "ADMIN" and sb["owner"] != user.get("username"):
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this sandbox.")
        
    auth_svc.db_service.delete_sandbox(sandbox_id)
    
    # Log audit event
    auth_svc.db_service.log_audit(
        actor=user.get("username", "anonymous"),
        action="delete_sandbox",
        ip_address=request.client.host if request.client else "unknown",
        details={"sandbox_id": sandbox_id}
    )
    return {"status": "success", "message": f"Sandbox {sandbox_id} terminated."}

