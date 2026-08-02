"""ThinkDome Execution Engine Package.

Provides pluggable, hardware and container-isolated execution backends:
  - ``thinkdome.executors.microvm``    : Hardware-virtualized MicroVM backends (Cloud Hypervisor / KVM)
  - ``thinkdome.executors.docker``     : OCI Container isolation backends
  - ``thinkdome.executors.kubernetes`` : Kubernetes Pod isolation backends
  - ``thinkdome.executors.host``       : Local subprocess & sandbox backends
  - ``thinkdome.executors.stubs``      : Compiled language stubs (C++, Java, C#)
"""

from thinkdome.executors.base import BaseExecutor, ExecRequest, ExecResult
from thinkdome.executors.executor_backend import ExecutorBackend, SandboxHandle
from thinkdome.executors.factory import create_executor
from thinkdome.executors.host.subprocess_executor import SubprocessExecutor
from thinkdome.executors.host.bubblewrap import BubblewrapExecutor

# Optional backends — guarded to avoid ImportError when deps are missing
try:
    from thinkdome.executors.host.python_hybrid import PythonHybridExecutor
except ImportError:
    PythonHybridExecutor = None  # type: ignore[assignment,misc]

try:
    from thinkdome.executors.microvm.executor import MicroVMExecutor, MicroVMInstance
except ImportError:
    MicroVMExecutor = MicroVMInstance = None  # type: ignore[assignment,misc]

try:
    from thinkdome.executors.docker import DockerBackend, PythonDockerExecutor
except ImportError:
    DockerBackend = PythonDockerExecutor = None  # type: ignore[assignment,misc]

try:
    from thinkdome.executors.kubernetes import KubernetesBackend, PythonKubernetesExecutor
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

