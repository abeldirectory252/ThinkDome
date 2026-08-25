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
    DOCKER_RUNTIME_PERMISSION = "EXECUTION::DOCKER_RUNTIME_PERMISSION"
    DOCKER_IMAGE_UNAVAILABLE = "EXECUTION::DOCKER_IMAGE_UNAVAILABLE"

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


_CLI_ERROR_MESSAGES = {
    SandboxErrorCodes.DOCKER_NETNS_SETUP_FAILED: (
        "Sandbox startup failed: Docker could not configure the isolated network. "
        "Check the Docker network runtime and retry."
    ),
    SandboxErrorCodes.DOCKER_RUNTIME_PERMISSION: (
        "Sandbox startup failed: Docker denied the container process-group setup. "
        "Check the Docker runtime permissions and security profile, then retry."
    ),
    SandboxErrorCodes.DOCKER_IMAGE_UNAVAILABLE: (
        "Sandbox startup failed: the configured Docker image is unavailable. "
        "Build or pull the image and retry."
    ),
}


def classify_sandbox_error(error: object, error_code: str | None = None) -> str:
    """Return the stable framework code for a runtime failure."""
    detail = str(error or "").strip().lower()
    if error_code and error_code != SandboxErrorCodes.EXECUTION_FAILED:
        return error_code
    if "setpgid failed" in detail or "operation not permitted" in detail:
        return SandboxErrorCodes.DOCKER_RUNTIME_PERMISSION
    if "no such image" in detail or "image not found" in detail:
        return SandboxErrorCodes.DOCKER_IMAGE_UNAVAILABLE
    if "network" in detail and ("docker" in detail or "netns" in detail):
        return SandboxErrorCodes.DOCKER_NETNS_SETUP_FAILED
    return error_code or SandboxErrorCodes.EXECUTION_FAILED


def present_sandbox_error(error: object, error_code: str | None = None) -> str:
    """Return stable, actionable user-facing text for sandbox diagnostics.

    Runtime details remain available to logs; CLI/API surfaces receive a
    predictable message that does not expose noisy engine internals.
    """
    detail = str(error or "").strip()
    lowered = detail.lower()
    code = classify_sandbox_error(detail, error_code)
    if code in _CLI_ERROR_MESSAGES:
        return _CLI_ERROR_MESSAGES[code]
    if not detail:
        return "Sandbox execution failed. Please check the runtime configuration and retry."
    return f"Sandbox execution failed [{code}]: {detail}"
