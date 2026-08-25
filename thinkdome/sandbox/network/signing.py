"""OSEP-0011 Signed Route Token generation and verification.

Canonical format::
    v1\\nshort\\n{sandbox_id}\\n{port}\\n{expires_b36}\\n

Signature scheme::
    inner     = BE32(len(secret)) || secret || BE32(len(canonical)) || canonical
    digest    = SHA256(inner)
    hex8      = hex(digest)[0:8]
    signature = hex8 + key_id                           # 9 chars
    route     = {sandbox_id}-{port}-{expires_b36}-{signature}
"""

from __future__ import annotations

import hmac
import hashlib
import struct
from typing import Final, Dict, Optional

_BASE36_CHARS: Final[str] = "0123456789abcdefghijklmnopqrstuvwxyz"
_BASE36_CHAR_SET: Final[set[str]] = set(_BASE36_CHARS)
MAX_EXPIRES_B36_LEN: Final[int] = 13
MAX_UINT64: Final[int] = 2**64 - 1
_CANONICAL_TEMPLATE: Final[str] = "v1\nshort\n{sandbox_id}\n{port}\n{expires_b36}\n"


def encode_expires_b36(expires_sec: int) -> str:
    """Encode a Unix epoch timestamp to base36."""
    if expires_sec < 0:
        raise ValueError(f"expires_sec must be non-negative, got {expires_sec}")
    if expires_sec > MAX_UINT64:
        raise ValueError(f"expires_sec exceeds uint64 range: {expires_sec}")
    if expires_sec == 0:
        return "0"

    n = expires_sec
    chars: list[str] = []
    while n > 0:
        n, r = divmod(n, 36)
        chars.append(_BASE36_CHARS[r])
    return "".join(reversed(chars))


def decode_expires_b36(s: str) -> int:
    """Decode a base36 string to a Unix timestamp."""
    if not s:
        raise ValueError("expires_b36 string must not be empty")
    if len(s) > MAX_EXPIRES_B36_LEN:
        raise ValueError(f"expires_b36 string too long: {len(s)} > {MAX_EXPIRES_B36_LEN}")
    if not all(c in _BASE36_CHAR_SET for c in s):
        raise ValueError(f"expires_b36 contains invalid characters: {s!r}")
    if len(s) > 1 and s[0] == "0":
        raise ValueError(f"expires_b36 must not have leading zeros: {s!r}")

    val = int(s, 36)
    if val > MAX_UINT64:
        raise ValueError(f"expires_b36 value overflows uint64: {s!r}")
    return val


def build_canonical_bytes(sandbox_id: str, port: int, expires_b36: str) -> bytes:
    """Build the canonical byte string for route signing."""
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be 1-65535, got {port}")
    text = _CANONICAL_TEMPLATE.format(
        sandbox_id=sandbox_id,
        port=port,
        expires_b36=expires_b36,
    )
    return text.encode("utf-8")


def _be32(x: int) -> bytes:
    return struct.pack(">I", x)


def compute_hex8(secret_bytes: bytes, canonical_bytes: bytes) -> str:
    """Compute the hex8 prefix of the SHA256 digest per OSEP-0011."""
    inner = (
        _be32(len(secret_bytes))
        + secret_bytes
        + _be32(len(canonical_bytes))
        + canonical_bytes
    )
    digest = hashlib.sha256(inner).digest()
    return digest.hex()[:8]


def compute_signature(
    secret_bytes: bytes,
    key_id: str,
    canonical_bytes: bytes,
) -> str:
    """Compute the full OSEP-0011 signature: hex8 + key_id (9 chars)."""
    return compute_hex8(secret_bytes, canonical_bytes) + key_id


def build_signed_route(
    sandbox_id: str,
    port: int,
    expires_sec: int,
    secret_bytes: bytes,
    key_id: str = "a",
) -> str:
    """Generate an OSEP-0011 signed route token.

    Format: {sandbox_id}-{port}-{expires_b36}-{signature}
    """
    expires_b36 = encode_expires_b36(expires_sec)
    canonical = build_canonical_bytes(sandbox_id, port, expires_b36)
    sig = compute_signature(secret_bytes, key_id, canonical)
    return f"{sandbox_id}-{port}-{expires_b36}-{sig}"


def verify_signed_route(
    route_token: str,
    secret_keys: Dict[str, bytes],
    current_time_sec: int,
) -> tuple[bool, str, Optional[str], Optional[int]]:
    """Verify an OSEP-0011 signed route token.

    Returns:
        tuple (valid: bool, reason: str, sandbox_id: Optional[str], port: Optional[int])
    """
    parts = route_token.split("-")
    if len(parts) < 4:
        return False, "Malformed route token structure", None, None

    sig = parts[-1]
    expires_b36 = parts[-2]
    try:
        port = int(parts[-3])
    except ValueError:
        return False, "Invalid port in route token", None, None

    sandbox_id = "-".join(parts[:-3])

    if len(sig) != 9:
        return False, "Signature must be 9 characters long", sandbox_id, port

    key_id = sig[-1]
    secret_bytes = secret_keys.get(key_id)
    if not secret_bytes:
        return False, f"Unknown key_id '{key_id}'", sandbox_id, port

    try:
        expires_sec = decode_expires_b36(expires_b36)
    except ValueError as e:
        return False, f"Invalid expiration encoding: {e}", sandbox_id, port

    if expires_sec < current_time_sec:
        return False, f"Signed route token expired at {expires_sec} < {current_time_sec}", sandbox_id, port

    canonical = build_canonical_bytes(sandbox_id, port, expires_b36)
    expected_sig = compute_signature(secret_bytes, key_id, canonical)

    if not hmac.compare_digest(sig, expected_sig):
        return False, "Signature verification failed", sandbox_id, port

    return True, "Valid signed route token", sandbox_id, port
