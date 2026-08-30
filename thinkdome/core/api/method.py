"""ThinkDome /api/method/ RPC Router — Frappe-style method endpoint.

Resolves dotted Python method paths, binds the authenticated session,
enforces @thinkdome.whitelist() permissions, and returns JSON results.

Frontend usage::

    const result = await thinkdome.call("thinkdome.core.ui.api.get_navigation");
    const result = await thinkdome.call("thinkdome.core.ui.api.save_ui_draft", { data: {...} });

HTTP wire protocol::

    POST /api/method/thinkdome.core.ui.api.get_navigation
    Content-Type: application/json
    Authorization: Bearer <token>

    {"key": "value"}

    →  200 { "message": {...} }
    →  403 { "exc_type": "PermissionError", ... }
    →  404 { "exc_type": "AttributeError", ... }
"""

from __future__ import annotations

import json
import logging
import traceback
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from thinkdome.core.dependencies import get_current_user
from thinkdome.core.handler import (
    SessionContext,
    resolve_and_call,
    get_all_whitelisted_methods,
    _resolve_method,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ThinkDome RPC"])


@router.api_route(
    "/api/method/{method_path:path}",
    methods=["GET", "POST"],
    include_in_schema=True,
    name="thinkdome_rpc",
)
async def handle_rpc_call(
    method_path: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Frappe-style generic RPC endpoint.

    Resolves ``method_path`` to a whitelisted Python function, binds the
    authenticated user as the thread-local session, and executes it.

    GET requests pass query params as keyword arguments.
    POST requests pass JSON body keys as keyword arguments.
    """
    # 1. Parse arguments
    kwargs: Dict[str, Any] = {}

    if request.method == "GET":
        for key, value in request.query_params.items():
            # Try JSON-decoding values so callers can pass objects/arrays
            try:
                kwargs[key] = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                kwargs[key] = value
    else:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    kwargs = body
            except Exception:
                pass
        elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            form = await request.form()
            for key in form:
                val = form[key]
                try:
                    kwargs[key] = json.loads(val)
                except (json.JSONDecodeError, ValueError, TypeError):
                    kwargs[key] = val

    # 2. Build session context from authenticated user
    session = {
        "user_id": user.get("username", user.get("user_id", "system")),
        "username": user.get("username", "system"),
        "role": user.get("role", "GUEST"),
        "roles": [user.get("role", "GUEST")],
        "ip_address": request.client.host if request.client else "127.0.0.1",
    }

    # 3. Resolve and execute inside session context
    try:
        with SessionContext(session):
            result = resolve_and_call(method_path, **kwargs)

        return JSONResponse(content={
            "message": result,
        })

    except PermissionError as e:
        logger.warning(f"RPC permission denied: {method_path} — {e}")
        return JSONResponse(
            status_code=403,
            content={
                "exc_type": "PermissionError",
                "message": str(e),
                "_server_messages": json.dumps([{"message": str(e), "indicator": "red"}]),
            },
        )

    except AttributeError as e:
        logger.warning(f"RPC method not found: {method_path} — {e}")
        return JSONResponse(
            status_code=404,
            content={
                "exc_type": "AttributeError",
                "message": str(e),
            },
        )

    except Exception as e:
        logger.exception(f"RPC error in {method_path}")
        return JSONResponse(
            status_code=500,
            content={
                "exc_type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc() if logger.isEnabledFor(logging.DEBUG) else None,
            },
        )


@router.get("/api/method", name="list_rpc_methods")
async def list_rpc_methods(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """List all registered whitelisted methods and their signatures."""
    methods = get_all_whitelisted_methods()
    return JSONResponse(content={"message": methods})
