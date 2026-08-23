"""JWT and Refresh Token Engine for ThinkDome Security."""

from __future__ import annotations

import hmac
import hashlib
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Set
import jwt

from thinkdome.core.config import get_settings

logger = logging.getLogger(__name__)

# In-memory revocation set for revoked JWT identifiers (jti)
_REVOKED_JTIS: Set[str] = set()

DEFAULT_SECRET_KEY = "thinkdome-super-secret-jwt-signing-key-change-in-prod"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7


def get_jwt_secret() -> str:
    """Retrieve JWT secret from settings or environment with secure fallback."""
    settings = get_settings()
    configured = getattr(settings, "JWT_SECRET_KEY", None) or getattr(settings, "SECRET_KEY", None)
    if settings.DEPLOYMENT_ENV.lower() in {"staging", "production"}:
        if not configured or len(configured) < 32:
            raise RuntimeError("JWT signing secret is not configured for production")
        return configured
    return configured or DEFAULT_SECRET_KEY


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """Mint a short-lived signed JWT access token (15-min default TTL)."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    
    jti = secrets.token_hex(16)
    to_encode.update({
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": jti,
        "type": "access",
    })
    
    secret = get_jwt_secret()
    token = jwt.encode(to_encode, secret, algorithm=ALGORITHM)
    return token


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a JWT access token."""
    secret = get_jwt_secret()
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        jti = payload.get("jti")
        if jti and jti in _REVOKED_JTIS:
            logger.warning(f"JWT access token with jti {jti} is revoked.")
            return None
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("JWT access token expired.")
        return None
    except jwt.PyJWTError as e:
        logger.debug(f"Invalid JWT access token: {e}")
        return None


def revoke_jti(jti: str) -> None:
    """Add JWT jti identifier to revocation list."""
    if jti:
        _REVOKED_JTIS.add(jti)


def generate_refresh_token() -> str:
    """Generate an opaque high-entropy refresh token."""
    return f"td_ref_{secrets.token_hex(32)}"


def hash_refresh_token(token: str) -> str:
    """Compute SHA-256 hash of refresh token for database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
