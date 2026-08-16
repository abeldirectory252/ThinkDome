"""Metadata label validation for sandbox resources.

Validates metadata keys/values against Kubernetes-style label rules:
  - Keys: up to 63 chars, alphanumeric with - _ . allowed
  - Keys with prefix: prefix is a DNS subdomain (≤253 chars), separated by /
  - Values: up to 63 chars, alphanumeric with - _ . allowed
  - Reserved prefix 'thinkdome.io/' is system-managed and cannot be set by users

Inspired by OpenSandbox's validators.py with Kubernetes label conventions.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

from fastapi import HTTPException, status

from thinkdome.core.error_codes import SandboxErrorCodes, RESERVED_LABEL_PREFIX

DNS_LABEL_PATTERN = r"[a-z0-9]([-a-z0-9]*[a-z0-9])?"
DNS_SUBDOMAIN_RE = re.compile(rf"^(?:{DNS_LABEL_PATTERN}\.)*{DNS_LABEL_PATTERN}$")
LABEL_NAME_RE = re.compile(r"^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$")
LABEL_VALUE_RE = re.compile(r"^([A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?)?$")


def _is_valid_label_key(key: str) -> bool:
    """Validate a metadata label key (with optional DNS subdomain prefix)."""
    if "/" in key:
        prefix, name = key.split("/", 1)
        if not prefix or not name:
            return False
        if len(prefix) > 253:
            return False
        if not DNS_SUBDOMAIN_RE.match(prefix):
            return False
    else:
        name = key
    if len(name) > 63 or not LABEL_NAME_RE.match(name):
        return False
    return True


def _is_valid_label_value(value: str) -> bool:
    """Validate a metadata label value."""
    if len(value) > 63:
        return False
    return bool(LABEL_VALUE_RE.match(value))


def is_system_label(key: str) -> bool:
    """Check if a label key uses the reserved system prefix."""
    return key.startswith(RESERVED_LABEL_PREFIX)


def ensure_metadata_labels(metadata: Optional[Dict[str, str]]) -> None:
    """Validate metadata keys/values against K8s-style label rules.

    Raises:
        HTTPException: When a key/value is invalid or uses reserved prefix.
    """
    if not metadata:
        return

    for key, value in metadata.items():
        if is_system_label(key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.RESERVED_LABEL_PREFIX,
                    "message": (
                        f"Metadata key '{key}' uses the reserved prefix '{RESERVED_LABEL_PREFIX}'. "
                        "Keys under this prefix are managed by the system and cannot be set via metadata."
                    ),
                },
            )
        if not _is_valid_label_key(key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_METADATA_LABEL,
                    "message": (
                        f"Metadata key '{key}' is invalid: must be either a name or a "
                        "DNS-subdomain prefix and name separated by /, where the name "
                        "is up to 63 characters and matches [A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?, "
                        "and the optional prefix is a valid DNS subdomain up to 253 characters."
                    ),
                },
            )
        if not _is_valid_label_value(value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.INVALID_METADATA_LABEL,
                    "message": (
                        f"Metadata value '{value}' is invalid: must be 63 characters or less, "
                        "start/end with an alphanumeric character, and contain only alphanumeric, "
                        "'-', '_', or '.' characters."
                    ),
                },
            )


def apply_metadata_patch(labels: dict, patch: dict) -> dict:
    """Apply JSON Merge Patch (RFC 7396) to metadata labels.

    - Non-null values add or replace keys
    - Null values delete keys
    - Absent keys are unchanged
    - System labels (thinkdome.io/ prefix) are preserved and cannot be patched

    Args:
        labels: Current label dict.
        patch: Patch dict with values to add/replace/delete.

    Returns:
        New label dict with patch applied.
    """
    # Reject patching system labels
    for key in patch:
        if is_system_label(key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": SandboxErrorCodes.RESERVED_LABEL_PREFIX,
                    "message": f"Metadata key '{key}' is reserved (thinkdome.io/ prefix).",
                },
            )

    # Validate only incoming patch values (not existing labels)
    patch_additions = {k: str(v) for k, v in patch.items() if v is not None}
    if patch_additions:
        ensure_metadata_labels(patch_additions)

    # Separate system labels from user metadata
    current_metadata = {
        k: v for k, v in labels.items() if not is_system_label(k)
    }

    # Apply patch
    for key, value in patch.items():
        if value is None:
            current_metadata.pop(key, None)
        else:
            current_metadata[key] = str(value)

    # Rebuild: system labels + patched user labels
    new_labels = {k: v for k, v in labels.items() if is_system_label(k)}
    for k, v in current_metadata.items():
        new_labels[k] = str(v)

    return new_labels
