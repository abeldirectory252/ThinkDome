"""User-facing sandbox lifecycle routes.

The legacy admin router remains available for compatibility, but sandbox
resources are not administrative resources and are exposed under /v1/sandboxes.
"""

from fastapi import APIRouter, Depends, Request

from thinkdome.core.dependencies import get_auth_service, get_current_user
from thinkdome.security.auth.service import AuthService
from thinkdome.security.api import admin as legacy

router = APIRouter(prefix="/sandboxes", tags=["sandboxes"])


@router.get("")
async def list_sandboxes(auth_svc: AuthService = Depends(get_auth_service), user: dict = Depends(get_current_user)):
    return await legacy.list_sandboxes(auth_svc, user)


@router.get("/capacity")
async def sandbox_capacity(auth_svc: AuthService = Depends(get_auth_service), user: dict = Depends(get_current_user)):
    return await legacy.sandbox_capacity(auth_svc, user)


@router.post("", status_code=201)
async def create_sandbox(
    req: legacy.CreateSandboxRequest,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
    user: dict = Depends(get_current_user),
):
    return await legacy.create_sandbox(req, request, auth_svc, user)


@router.post("/{sandbox_id}/toggle")
async def toggle_sandbox(
    sandbox_id: str,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
    user: dict = Depends(get_current_user),
):
    return await legacy.toggle_sandbox(sandbox_id, request, auth_svc, user)


@router.delete("/{sandbox_id}")
async def delete_sandbox(
    sandbox_id: str,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
    user: dict = Depends(get_current_user),
):
    return await legacy.delete_sandbox(sandbox_id, request, auth_svc, user)
