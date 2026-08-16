"""Monitor API endpoints — real-time sandbox metrics, alerts, and WebSocket streaming."""

import json
import logging
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse

from thinkdome.core.dependencies import get_current_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitor"])


@router.get("/monitor/metrics")
async def get_all_metrics(request: Request, _user=Depends(get_current_admin)):
    """Get latest metrics snapshot for all active sandboxes."""
    monitor = getattr(request.app.state, "monitor_service", None)
    if not monitor:
        return JSONResponse(
            status_code=503,
            content={"detail": "Monitor service not available"}
        )
    return {
        "status": monitor.get_status(),
        "sandboxes": monitor.get_all_metrics(),
    }


@router.get("/monitor/metrics/{sandbox_id}")
async def get_sandbox_metrics(sandbox_id: str, request: Request, _user=Depends(get_current_admin)):
    """Get latest metrics for a specific sandbox."""
    monitor = getattr(request.app.state, "monitor_service", None)
    if not monitor:
        return JSONResponse(status_code=503, content={"detail": "Monitor service not available"})

    metrics = monitor.get_sandbox_metrics(sandbox_id)
    if not metrics:
        return JSONResponse(status_code=404, content={"detail": f"No metrics for sandbox '{sandbox_id}'"})

    return {
        "sandbox_id": sandbox_id,
        "metrics": metrics,
        "history": monitor.get_sandbox_history(sandbox_id),
    }


@router.get("/monitor/alerts")
async def get_alerts(request: Request, limit: int = 50, _user=Depends(get_current_admin)):
    """Get recent alert history."""
    monitor = getattr(request.app.state, "monitor_service", None)
    if not monitor:
        return JSONResponse(status_code=503, content={"detail": "Monitor service not available"})

    return {
        "alerts": monitor.get_alerts(limit=limit),
        "rules": monitor.get_alert_rules(),
    }


@router.websocket("/monitor/ws")
async def monitor_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time metrics streaming.

    Clients connect and receive metrics broadcasts every poll interval.
    Authentication is checked via query parameter: ?token=<api_key>
    """
    monitor = getattr(websocket.app.state, "monitor_service", None)
    if not monitor:
        await websocket.close(code=1013, reason="Monitor service not available")
        return

    # Authenticate via query param
    token = websocket.query_params.get("token")
    if token:
        auth_service = getattr(websocket.app.state, "auth_service", None)
        if auth_service:
            identity = auth_service.verify_token(token)
            if not identity or identity.get("role") not in ("ADMIN", "ORCH", "IDE"):
                await websocket.close(code=1008, reason="Unauthorized")
                return

    await websocket.accept()
    logger.info("📊 Monitor WebSocket client connected")

    # Subscribe to metrics broadcasts
    async def send_metrics(payload: dict):
        await websocket.send_json(payload)

    sub_id = monitor.subscribe(send_metrics)

    try:
        # Keep connection alive — client can send pings
        while True:
            data = await websocket.receive_text()
            # Handle ping/pong or commands
            if data == "ping":
                await websocket.send_text("pong")
            elif data == "status":
                await websocket.send_json(monitor.get_status())
    except WebSocketDisconnect:
        logger.info("📊 Monitor WebSocket client disconnected")
    except Exception as e:
        logger.debug(f"Monitor WebSocket error: {e}")
    finally:
        monitor.unsubscribe(sub_id)
