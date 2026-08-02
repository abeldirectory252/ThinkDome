"""Execution management domain — code execution, container pooling, egress.

Subdirectories:
  - core/     : ExecutionService, request/response models, manifests, languages
  - pool/     : Pre-warmed container pool manager for low-latency execution
  - egress/   : Network egress proxy & domain allowlisting
  - api/      : REST API routers (execute, languages)
  - tools/    : Agent tool wrappers (RunCode, ShellExec)
"""

from thinkdome.execution.core.service import ExecutionService
from thinkdome.execution.core.models import ExecuteRequest, ExecuteResponse
from thinkdome.execution.pool.manager import PoolManager

__all__ = ["ExecutionService", "ExecuteRequest", "ExecuteResponse", "PoolManager"]
