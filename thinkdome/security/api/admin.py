"""Admin, API Key, and filesystem backend management endpoints."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from thinkdome.core.dependencies import (
    get_auth_service,
    get_request_log_service,
    get_current_admin,
    get_current_user,
    get_billing_service
)
from thinkdome.security.auth.service import AuthService
from thinkdome.platform.orchestration.request_log import RequestLogService
from thinkdome.platform.billing.service import BillingService
from thinkdome.core.config import get_settings

router = APIRouter(tags=["admin"])
logger = logging.getLogger(__name__)
_SANDBOX_CACHE_PREFIX = "thinkdome:sandboxes:v1"
_sandbox_redis = None


async def _sandbox_cache_client():
    """Return Redis when available; the ORM remains the source of truth."""
    global _sandbox_redis
    if _sandbox_redis is False:
        return None
    if _sandbox_redis is not None:
        return _sandbox_redis
    try:
        from redis.asyncio import from_url
        client = from_url(get_settings().REDIS_URL, decode_responses=True)
        await client.ping()
        _sandbox_redis = client
        return client
    except Exception as exc:
        logger.debug("Sandbox Redis cache unavailable: %s", exc)
        _sandbox_redis = False
        return None


def _sandbox_cache_key(owner: Optional[str]) -> str:
    scope = owner or "__admin_fleet__"
    digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]
    return f"{_SANDBOX_CACHE_PREFIX}:{digest}"


async def _get_cached_sandboxes(owner: Optional[str]):
    client = await _sandbox_cache_client()
    if not client:
        return None
    try:
        value = await client.get(_sandbox_cache_key(owner))
        return json.loads(value) if value else None
    except Exception as exc:
        logger.debug("Sandbox cache read failed: %s", exc)
        return None


async def _cache_sandboxes(owner: Optional[str], rows: list[dict]) -> None:
    client = await _sandbox_cache_client()
    if not client:
        return
    try:
        # Keep the coherence window deliberately short. All supported writes
        # invalidate this namespace after the ORM transaction commits.
        await client.setex(_sandbox_cache_key(owner), 1, json.dumps(rows, default=str))
    except Exception as exc:
        logger.debug("Sandbox cache write failed: %s", exc)


async def _invalidate_sandbox_cache() -> None:
    client = await _sandbox_cache_client()
    if not client:
        return
    try:
        keys = [key async for key in client.scan_iter(match=f"{_SANDBOX_CACHE_PREFIX}:*")]
        if keys:
            await client.delete(*keys)
    except Exception as exc:
        logger.debug("Sandbox cache invalidation failed: %s", exc)


@router.get("/settings")
async def get_web_settings(_admin: dict = Depends(get_current_admin)):
    settings = get_settings()
    from thinkdome.apps.sandbox.models import SystemSetting
    records = {r.key: r for r in SystemSetting.query().all()}
    def configured_int(key: str, default: int, minimum: int, maximum: int) -> int:
        value = records.get(key).value if records.get(key) else None
        try:
            parsed = int(value)
            return parsed if minimum <= parsed <= maximum else default
        except (TypeError, ValueError):
            return default
    quota = configured_int("filebox_default_quota_mb", settings.FILEBOX_DEFAULT_QUOTA_MB, 1, 1_048_576)
    settings.MCP_MAX_MESSAGE_BYTES = configured_int("mcp_max_message_bytes", settings.MCP_MAX_MESSAGE_BYTES, 16_384, 16_777_216)
    settings.REQUEST_LOG_MAX_PAYLOAD_BYTES = configured_int("request_log_max_payload_bytes", settings.REQUEST_LOG_MAX_PAYLOAD_BYTES, 16_384, 16_777_216)
    return {
        "filebox_default_quota_mb": quota,
        "mcp_max_message_bytes": settings.MCP_MAX_MESSAGE_BYTES,
        "request_log_max_payload_bytes": settings.REQUEST_LOG_MAX_PAYLOAD_BYTES,
        "execution_hook_timeout_ms": settings.EXECUTION_HOOK_TIMEOUT_MS,
    }


@router.put("/settings")
async def update_web_settings(payload: dict, _admin: dict = Depends(get_current_admin)):
    quota = payload.get("filebox_default_quota_mb")
    mcp_limit = payload.get("mcp_max_message_bytes")
    log_limit = payload.get("request_log_max_payload_bytes")
    hook_timeout = payload.get("execution_hook_timeout_ms")
    if quota is None and mcp_limit is None and log_limit is None and hook_timeout is None:
        raise HTTPException(status_code=422, detail="At least one setting is required")
    if quota is not None and (not isinstance(quota, int) or isinstance(quota, bool) or not 1 <= quota <= 1_048_576):
        raise HTTPException(status_code=422, detail="filebox_default_quota_mb must be an integer from 1 to 1048576")
    if mcp_limit is not None and (not isinstance(mcp_limit, int) or isinstance(mcp_limit, bool) or not 16_384 <= mcp_limit <= 16_777_216):
        raise HTTPException(status_code=422, detail="mcp_max_message_bytes must be an integer from 16384 to 16777216")
    if log_limit is not None and (not isinstance(log_limit, int) or isinstance(log_limit, bool) or not 16_384 <= log_limit <= 16_777_216):
        raise HTTPException(status_code=422, detail="request_log_max_payload_bytes must be an integer from 16384 to 16777216")
    if hook_timeout is not None and (not isinstance(hook_timeout, int) or isinstance(hook_timeout, bool) or not 100 <= hook_timeout <= 120_000):
        raise HTTPException(status_code=422, detail="execution_hook_timeout_ms must be an integer from 100 to 120000")
    settings = get_settings()
    if quota is not None:
        settings.FILEBOX_DEFAULT_QUOTA_MB = quota
    if mcp_limit is not None:
        settings.MCP_MAX_MESSAGE_BYTES = mcp_limit
    if log_limit is not None:
        settings.REQUEST_LOG_MAX_PAYLOAD_BYTES = log_limit
    if hook_timeout is not None:
        settings.EXECUTION_HOOK_TIMEOUT_MS = hook_timeout
    from thinkdome.apps.sandbox.models import SystemSetting
    values = {
        "filebox_default_quota_mb": quota,
        "mcp_max_message_bytes": mcp_limit,
        "request_log_max_payload_bytes": log_limit,
        "execution_hook_timeout_ms": hook_timeout,
    }
    for key, value in values.items():
        if value is None:
            continue
        record = SystemSetting.query().filter(key=key).first()
        if record:
            record._values["value"] = str(value)
        else:
            record = SystemSetting(key=key, value=str(value), category="system")
        record.save()
    return await get_web_settings(_admin)


def _principal(user: dict) -> str:
    """Stable per-user namespace, including API-key identities."""
    return str(user.get("workspace_id", user.get("username", "anonymous"))).strip().lower()


def _is_admin(user: dict) -> bool:
    """Use the resolved RBAC role, never a display name, for admin scope."""
    return str(user.get("role", "")).upper() in {
        "ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN", "ORCH", "IDE"
    }

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
    display_name: str = Field(..., max_length=50, json_schema_extra={"example": "My LLM Client"})
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
    from thinkdome.security.rbac.models import RbacAuditLog
    logs = RbacAuditLog.query().limit(limit).all()
    return [l.to_dict() for l in logs]

@router.get("/audits/{audit_id}")
async def get_audit_detail(
    audit_id: str,
    auth_svc: AuthService = Depends(get_auth_service),
    _admin: dict = Depends(get_current_admin)
):
    """Retrieve a single audit log entry with parsed details."""
    import json as _json
    from thinkdome.security.rbac.models import RbacAuditLog
    log_model = RbacAuditLog.get(audit_id)
    if not log_model:
        raise HTTPException(status_code=404, detail="Audit log entry not found.")
    entry = log_model.to_dict()
    # Parse details JSON string into object
    try:
        entry["details"] = _json.loads(entry["details"]) if isinstance(entry["details"], str) else entry["details"]
    except Exception:
        pass

    # Try to find a related request log by matching timestamp window (+/- 2 seconds)
    related_log = None
    if entry.get("timestamp"):
        related_log = auth_svc.db_service.fetch_one(
            """SELECT * FROM request_logs 
               WHERE ABS(julianday(timestamp) - julianday(?)) < 0.00003
               ORDER BY ABS(julianday(timestamp) - julianday(?)) ASC
               LIMIT 1""",
            (entry["timestamp"], entry["timestamp"])
        )
    if related_log:
        related_log = dict(related_log)
        try:
            related_log["request_payload"] = _json.loads(related_log["request_payload"]) if isinstance(related_log["request_payload"], str) else related_log["request_payload"]
        except Exception:
            pass
        try:
            related_log["response_payload"] = _json.loads(related_log["response_payload"]) if isinstance(related_log["response_payload"], str) else related_log["response_payload"]
        except Exception:
            pass
        entry["related_execution"] = related_log
    else:
        entry["related_execution"] = None

    return entry

# ── FILESYSTEMS ENDPOINTS (PROTECTED) ──

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
    name: str = Field(..., max_length=100, json_schema_extra={"example": "ML Sandbox"})
    # Keep resource requests within the scheduler/container contract.  E2B
    # similarly bounds sandbox lifetime instead of accepting arbitrary TTLs.
    memory_mb: int = Field(256, gt=0, le=65536)
    cpu_cores: float = Field(1.0, gt=0, le=64)
    timeout_sec: int = Field(30, ge=1, le=86400)
    network_enabled: bool = Field(False)
    storage_quota_mb: int = Field(10240, gt=0, le=1_048_576)

@router.get("/sandboxes")
async def list_sandboxes(
    auth_svc: AuthService = Depends(get_auth_service),
    user: dict = Depends(get_current_user)
):
    """List sandboxes. Admins see all; users see their own."""
    from thinkdome.security.identity.core import UserIdentity
    identity = UserIdentity.from_dict(user)
    owner = None if identity.is_admin() else _principal(user)
    cached = await _get_cached_sandboxes(owner)
    if cached is not None:
        return cached
    rows = auth_svc.db_service.list_sandboxes(owner=owner)
    await _cache_sandboxes(owner, rows)
    return rows

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
    
    from thinkdome.apps.sandbox.models import Sandbox
    sandbox = Sandbox(
        id=sandbox_id,
        name=req.name,
        owner=_principal(user),
        memory_limit=req.memory_mb,
        cpu_limit=req.cpu_cores,
        storage_quota_mb=req.storage_quota_mb,
        network_enabled=req.network_enabled,
        status="Created",
    )
    sandbox.save()
    await _invalidate_sandbox_cache()
    res = sandbox.to_dict()
    res["sandbox_id"] = sandbox_id
    res["timeout_sec"] = req.timeout_sec
    res["cost_per_hour"] = cost
    
    # Log audit event
    auth_svc.db_service.log_audit(
        actor=_principal(user),
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
    if user.get("role") != "ADMIN" and sb["owner"] != _principal(user):
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this sandbox.")
        
    new_status = "stopped" if sb["status"] == "active" else "active"
    auth_svc.db_service.update_sandbox_status(sandbox_id, new_status)
    await _invalidate_sandbox_cache()
    
    # Log audit event
    auth_svc.db_service.log_audit(
        actor=_principal(user),
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
    if user.get("role") != "ADMIN" and sb["owner"] != _principal(user):
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this sandbox.")
        
    auth_svc.db_service.delete_sandbox(sandbox_id)
    await _invalidate_sandbox_cache()
    
    # Log audit event
    auth_svc.db_service.log_audit(
        actor=_principal(user),
        action="delete_sandbox",
        ip_address=request.client.host if request.client else "unknown",
        details={"sandbox_id": sandbox_id}
    )
    return {"status": "success", "message": f"Sandbox {sandbox_id} terminated."}


# ── BILLING ENDPOINTS ──

@router.get("/billing")
async def get_billing_report(
    cycle: str = "this",
    billing_svc: BillingService = Depends(get_billing_service),
    user: dict = Depends(get_current_user)
):
    """Retrieve billing and usage reports."""
    return billing_svc.get_billing_data(
        cycle=cycle, username=_principal(user), is_admin=_is_admin(user)
    )


@router.post("/billing/invoice")
async def compile_invoice(
    cycle: str = "this",
    billing_svc: BillingService = Depends(get_billing_service),
    user: dict = Depends(get_current_user)
):
    """Compile PDF invoice for a given billing cycle."""
    invoice_id, _ = billing_svc.compile_invoice_pdf(
        cycle=cycle, username=_principal(user), is_admin=_is_admin(user)
    )
    
    # We construct a secure download URL passing the session token as query parameter
    return {
        "invoice_id": invoice_id,
        "download_url": f"/v1/admin/billing/invoice/download/{invoice_id}"
    }


@router.get("/billing/invoice/download/{invoice_id}")
async def download_invoice_pdf(
    invoice_id: str,
    billing_svc: BillingService = Depends(get_billing_service),
    _user: dict = Depends(get_current_user)
):
    """Serve the compiled PDF invoice file."""
    pdf_path = billing_svc.invoices_dir / f"invoice_{invoice_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Invoice PDF file not found.")
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"invoice_{invoice_id}.pdf"
    )


# ── ADMINISTRATOR CONTROLS (NETWORK POLICY, RUNTIMES, KILL SWITCH) ──

class NetworkPolicyUpdateRequest(BaseModel):
    tenant_id: str = Field("default", description="Tenant ID or '*' for global")
    role: Optional[str] = Field(None, description="Role target (e.g. AGENT_STANDARD)")
    allowlist: list[str] = Field(default_factory=list, description="Allowed domain regex patterns")
    denylist: list[str] = Field(default_factory=list, description="Denied domain regex patterns")

class RuntimeToggleRequest(BaseModel):
    runtime: str = Field(..., description="Runtime identifier: python, node, go")
    enabled: bool = Field(..., description="Whether runtime is enabled")
    tenant_id: Optional[str] = Field("default", description="Target tenant or 'default'")

class KillSwitchRequest(BaseModel):
    freeze_creation: bool = Field(True, description="Freeze new sandbox creation")
    purge_sandboxes: bool = Field(False, description="Force purge active sandboxes")
    tenant_id: Optional[str] = Field(None, description="Specific target tenant ID or None for platform-wide")

_PLATFORM_RUNTIMES: dict[str, bool] = {
    "python": True,
    "node": True,
    "go": False,
}
_PLATFORM_FROZEN: bool = False


@router.get("/network-policy")
async def get_network_policy(
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
    _admin: dict = Depends(get_current_admin)
):
    """Get active network egress policies."""
    row = auth_svc.db_service.fetch_one(
        "SELECT config_value FROM admin_configs WHERE config_key = 'network_policy'"
    )
    if row:
        import json
        return json.loads(row["config_value"])
    return {
        "tenant_id": "default",
        "allowlist": [r".*\.github\.com$", r".*\.pypi\.org$", r".*\.python\.org$"],
        "denylist": [r"^169\.254\.169\.254$"]
    }


@router.put("/network-policy")
async def update_network_policy(
    req: NetworkPolicyUpdateRequest,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
    _admin: dict = Depends(get_current_admin)
):
    """Update data-driven network egress policy per role or tenant and log audit."""
    import json
    actor = _admin.get("username", "admin")
    client_ip = request.client.host if request.client else "unknown"
    
    policy_data = {
        "tenant_id": req.tenant_id,
        "role": req.role,
        "allowlist": req.allowlist,
        "denylist": req.denylist,
        "updated_at": request.headers.get("date", "")
    }
    
    auth_svc.db_service.execute(
        """
        INSERT INTO admin_configs (config_key, config_value, updated_at, updated_by)
        VALUES ('network_policy', ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(config_key) DO UPDATE SET config_value = excluded.config_value, updated_by = excluded.updated_by
        """,
        (json.dumps(policy_data), actor)
    )
    
    # Audit log
    auth_svc.db_service.log_audit(
        actor=actor,
        action="update_network_policy",
        ip_address=client_ip,
        details=policy_data
    )
    return {"status": "success", "policy": policy_data}


@router.get("/runtimes")
async def list_runtimes(_admin: dict = Depends(get_current_admin)):
    """List platform-wide language runtime availability."""
    return {"runtimes": _PLATFORM_RUNTIMES}


@router.post("/runtimes/toggle")
async def toggle_runtime(
    req: RuntimeToggleRequest,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
    _admin: dict = Depends(get_current_admin)
):
    """Enable or disable language runtimes platform-wide or per tenant."""
    actor = _admin.get("username", "admin")
    client_ip = request.client.host if request.client else "unknown"
    
    runtime = req.runtime.lower()
    _PLATFORM_RUNTIMES[runtime] = req.enabled
    
    auth_svc.db_service.log_audit(
        actor=actor,
        action="toggle_runtime",
        ip_address=client_ip,
        details={"runtime": runtime, "enabled": req.enabled, "tenant_id": req.tenant_id}
    )
    return {"status": "success", "runtime": runtime, "enabled": req.enabled}


@router.post("/kill-switch")
async def trigger_kill_switch(
    req: KillSwitchRequest,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
    _admin: dict = Depends(get_current_admin)
):
    """Platform emergency kill switch: freeze sandbox creation or force-purge tenant sandboxes."""
    global _PLATFORM_FROZEN
    actor = _admin.get("username", "admin")
    client_ip = request.client.host if request.client else "unknown"
    
    _PLATFORM_FROZEN = req.freeze_creation
    purged_count = 0
    
    if req.purge_sandboxes:
        lifecycle_svc = getattr(request.app.state, "lifecycle_service", None)
        if lifecycle_svc:
            sboxes = list(lifecycle_svc._sandboxes.values())
            for sb in sboxes:
                if req.tenant_id is None or sb.metadata.get("tenant_id") == req.tenant_id:
                    await lifecycle_svc.destroy_sandbox(sb.sandbox_id, actor=f"admin_kill_switch:{actor}")
                    purged_count += 1
                    
    auth_svc.db_service.log_audit(
        actor=actor,
        action="trigger_kill_switch",
        ip_address=client_ip,
        details={
            "freeze_creation": req.freeze_creation,
            "purge_sandboxes": req.purge_sandboxes,
            "tenant_id": req.tenant_id,
            "purged_count": purged_count
        }
    )
    
    return {
        "status": "success",
        "frozen": _PLATFORM_FROZEN,
        "purged_count": purged_count,
        "message": f"Kill switch triggered by {actor}."
    }
