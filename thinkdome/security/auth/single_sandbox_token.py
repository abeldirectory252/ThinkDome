"""Short-lived, single-sandbox access tokens for client-side streaming and sandbox sidecar interaction."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
import jwt

from thinkdome.security.auth.jwt_engine import get_jwt_secret, ALGORITHM

logger = logging.getLogger(__name__)

SANDBOX_TOKEN_EXPIRE_MINUTES = 5


def mint_sandbox_access_token(
    sandbox_id: str,
    username: str,
    role: str = "AGENT_STANDARD",
    expires_minutes: int = SANDBOX_TOKEN_EXPIRE_MINUTES,
    allowed_actions: Optional[list[str]] = None
) -> str:
    """Mint a narrow, single-sandbox, time-boxed access token (5-min default TTL)."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes)
    
    payload = {
        "sub": username,
        "role": role,
        "sandbox_id": sandbox_id,
        "type": "sandbox_access",
        "actions": allowed_actions or ["read_logs", "stream", "exec_guest"],
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    
    secret = get_jwt_secret()
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def verify_sandbox_access_token(token: str, target_sandbox_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Verify a single-sandbox access token."""
    secret = get_jwt_secret()
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        if payload.get("type") != "sandbox_access":
            return None
        
        token_sandbox_id = payload.get("sandbox_id")
        if target_sandbox_id and token_sandbox_id != target_sandbox_id:
            logger.warning(
                f"Sandbox token mismatch: token requested for {token_sandbox_id}, target was {target_sandbox_id}"
            )
            return None
            
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("Single-sandbox access token expired.")
        return None
    except jwt.PyJWTError as e:
        logger.debug(f"Invalid single-sandbox access token: {e}")
        return None
