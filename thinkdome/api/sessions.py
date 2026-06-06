"""Session management endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from thinkdome.api.dependencies import get_session_service
from thinkdome.models.sessions import (
    CreateSessionRequest,
    SessionInfo,
    SessionExecRequest,
    SessionExecResponse,
)
from thinkdome.services.session_service import SessionService

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionInfo, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    svc: SessionService = Depends(get_session_service),
):
    return svc.create(body)


@router.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(
    session_id: str, svc: SessionService = Depends(get_session_service)
):
    info = svc.get(session_id)
    if not info:
        raise HTTPException(status_code=404, detail="Session not found")
    return info


@router.post("/sessions/{session_id}/exec", response_model=SessionExecResponse)
async def execute_in_session(
    session_id: str,
    body: SessionExecRequest,
    svc: SessionService = Depends(get_session_service),
):
    result = await svc.execute_in_session(session_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found or inactive")
    return result


@router.delete("/sessions/{session_id}")
async def close_session(
    session_id: str, svc: SessionService = Depends(get_session_service)
):
    if not svc.close(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "closed", "session_id": session_id}
