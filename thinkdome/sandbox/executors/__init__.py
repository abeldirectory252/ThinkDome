"""ThinkDome Execution Engine Package.

Provides pluggable, hardware and container-isolated execution backends:
  - ``thinkdome.sandbox.executors.microvm``    : Hardware-virtualized MicroVM backends (Cloud Hypervisor / KVM)
  - ``thinkdome.sandbox.executors.docker``     : OCI Container isolation backends
  - ``thinkdome.sandbox.executors.kubernetes`` : Kubernetes Pod isolation backends
  - ``thinkdome.sandbox.executors.host``       : Local subprocess & sandbox backends
  - ``thinkdome.sandbox.executors.stubs``      : Compiled language stubs (C++, Java, C#)
"""

from thinkdome.sandbox.executors.base import BaseExecutor, ExecRequest, ExecResult
from thinkdome.sandbox.executors.executor_backend import ExecutorBackend, SandboxHandle
from thinkdome.sandbox.executors.factory import create_executor
from thinkdome.sandbox.executors.host.subprocess_executor import SubprocessExecutor
from thinkdome.sandbox.executors.host.bubblewrap import BubblewrapExecutor

# Optional backends — guarded to avoid ImportError when deps are missing
try:
    from thinkdome.sandbox.executors.host.python_hybrid import PythonHybridExecutor
except ImportError:
    PythonHybridExecutor = None  # type: ignore[assignment,misc]

try:
    from thinkdome.sandbox.executors.microvm.executor import MicroVMExecutor, MicroVMInstance
except ImportError:
    MicroVMExecutor = MicroVMInstance = None  # type: ignore[assignment,misc]

try:
    from thinkdome.sandbox.executors.docker import DockerBackend, PythonDockerExecutor
except ImportError:
    DockerBackend = PythonDockerExecutor = None  # type: ignore[assignment,misc]

try:
    from thinkdome.sandbox.executors.kubernetes import KubernetesBackend, PythonKubernetesExecutor
except ImportError:
    KubernetesBackend = PythonKubernetesExecutor = None  # type: ignore[assignment,misc]

__all__ = [
    "BaseExecutor",
    "ExecRequest",
    "ExecResult",
    "ExecutorBackend",
    "SandboxHandle",
    "create_executor",
    "SubprocessExecutor",
    "BubblewrapExecutor",
    "PythonHybridExecutor",
    "MicroVMExecutor",
    "MicroVMInstance",
    "DockerBackend",
    "PythonDockerExecutor",
    "KubernetesBackend",
    "PythonKubernetesExecutor",
]

