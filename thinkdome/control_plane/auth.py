"""Operation-scoped authorization tokens for node orchestrators."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Mapping

from thinkdome.control_plane.orchestrator import OrchestratorAuthorization, OrchestratorOperation


class InvalidNodeAuthorization(ValueError):
    """A node authorization token is malformed, expired, or invalid."""


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class NodeAuthorizationSigner:
    """HMAC signer used between a control plane and a trusted node agent.

    In production the key is delivered through a secret manager and rotated;
    the token itself contains no tenant credentials or Docker credentials.
    """

    def __init__(self, key: bytes, key_id: str = "current") -> None:
        if len(key) < 32:
            raise ValueError("node authorization key must contain at least 32 bytes")
        self._key = key
        self.key_id = key_id

    def issue(self, authorization: OrchestratorAuthorization) -> str:
        payload = authorization.model_dump(mode="json")
        payload["key_id"] = self.key_id
        body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        signature = hmac.new(self._key, body.encode(), hashlib.sha256).digest()
        return f"tdn1.{body}.{_b64(signature)}"

    def verify(self, token: str) -> OrchestratorAuthorization:
        try:
            scheme, body, signature = token.split(".", 2)
            if scheme != "tdn1":
                raise ValueError("unsupported token scheme")
            expected = hmac.new(self._key, body.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, _unb64(signature)):
                raise ValueError("signature mismatch")
            payload = json.loads(_unb64(body))
            if payload.pop("key_id", None) != self.key_id:
                raise ValueError("unknown key id")
            authorization = OrchestratorAuthorization.model_validate(payload)
            if authorization.is_expired():
                raise ValueError("authorization expired")
            return authorization
        except Exception as exc:
            raise InvalidNodeAuthorization(f"invalid node authorization: {exc}") from exc


def generate_node_key() -> bytes:
    """Generate a key suitable for NodeAuthorizationSigner."""
    return secrets.token_bytes(32)
