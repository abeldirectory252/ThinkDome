"""Standardized error codes for ThinkDome API.

Provides uniform error code constants used across all API endpoints.
Every error response uses the schema: {"code": "...", "message": "..."}.

Inspired by OpenSandbox's SandboxErrorCodes pattern for consistent error reporting.
"""


class SandboxErrorCodes:
    """Error codes for sandbox lifecycle and execution operations."""

    # General
    UNKNOWN_ERROR = "GENERAL::UNKNOWN_ERROR"
    INVALID_PARAMETER = "GENERAL::INVALID_PARAMETER"
    VALIDATION_FAILED = "GENERAL::VALIDATION_FAILED"

    # Authentication / Authorization
    MISSING_API_KEY = "AUTH::MISSING_API_KEY"
    INVALID_API_KEY = "AUTH::INVALID_API_KEY"
    INSUFFICIENT_PERMISSIONS = "AUTH::INSUFFICIENT_PERMISSIONS"

    # Sandbox lifecycle
    SANDBOX_NOT_FOUND = "SANDBOX::NOT_FOUND"
    SANDBOX_ALREADY_EXISTS = "SANDBOX::ALREADY_EXISTS"
    INVALID_STATE = "SANDBOX::INVALID_STATE"
    INVALID_EXPIRATION = "SANDBOX::INVALID_EXPIRATION"
    CREATION_FAILED = "SANDBOX::CREATION_FAILED"
    STATE_CONFLICT = "SANDBOX::STATE_CONFLICT"
    TENANT_SCOPE_DENIED = "TENANT::SCOPE_DENIED"
    TENANT_CONTEXT_REQUIRED = "TENANT::CONTEXT_REQUIRED"
    NO_NODE_CAPACITY = "SCHEDULER::NO_NODE_CAPACITY"
    IDEMPOTENCY_CONFLICT = "SANDBOX::IDEMPOTENCY_CONFLICT"

    # Sandbox execution
    EXECUTION_TIMEOUT = "EXECUTION::TIMEOUT"
    EXECUTION_FAILED = "EXECUTION::FAILED"
    INVALID_LANGUAGE = "EXECUTION::INVALID_LANGUAGE"
    DOCKER_NETNS_SETUP_FAILED = "EXECUTION::DOCKER_NETNS_SETUP_FAILED"

    # Metadata
    INVALID_METADATA_LABEL = "METADATA::INVALID_LABEL"
    RESERVED_LABEL_PREFIX = "METADATA::RESERVED_PREFIX"

    # Snapshots
    SNAPSHOT_NOT_FOUND = "SNAPSHOT::NOT_FOUND"
    SNAPSHOT_INVALID_STATE = "SNAPSHOT::INVALID_STATE"
    SNAPSHOT_NOT_IMPLEMENTED = "SNAPSHOT::NOT_IMPLEMENTED"

    # Diagnostics
    DIAGNOSTICS_NOT_AVAILABLE = "DIAGNOSTICS::NOT_AVAILABLE"

    # Pool
    POOL_NOT_SUPPORTED = "POOL::NOT_SUPPORTED"
    POOL_EXHAUSTED = "POOL::EXHAUSTED"

    # Files
    FILE_NOT_FOUND = "FILE::NOT_FOUND"
    FILE_INVALID_PATH = "FILE::INVALID_PATH"
    FILE_TOO_LARGE = "FILE::TOO_LARGE"

    # Network / Egress
    EGRESS_DENIED = "EGRESS::DENIED"
    EGRESS_RATE_LIMITED = "EGRESS::RATE_LIMITED"

    # Metrics
    METRICS_INVALID_EVENT = "METRICS::INVALID_EVENT"


# Reserved label prefix — metadata keys starting with this are system-managed.
RESERVED_LABEL_PREFIX = "thinkdome.io/"

# Default values for error normalization
DEFAULT_ERROR_CODE = SandboxErrorCodes.UNKNOWN_ERROR
DEFAULT_ERROR_MESSAGE = "An unexpected error occurred."


def normalize_error_detail(detail) -> dict:
    """Ensure HTTP error payloads always conform to {"code": "...", "message": "..."}.

    Accepts:
      - dict with optional "code" and "message" keys
      - str (used as message)
      - anything else (stringified as message)

    Returns:
        dict with exactly {"code": str, "message": str}
    """
    if isinstance(detail, dict):
        code = detail.get("code") or DEFAULT_ERROR_CODE
        message = detail.get("message") or DEFAULT_ERROR_MESSAGE
        return {"code": code, "message": message}
    message = str(detail) if detail else DEFAULT_ERROR_MESSAGE
    return {"code": DEFAULT_ERROR_CODE, "message": message}
