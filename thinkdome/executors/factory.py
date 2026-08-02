"""Executor factory — selects backend based on configuration."""

from __future__ import annotations

from thinkdome.core.config import Settings
from thinkdome.executors.base import BaseExecutor


def create_executor(settings: Settings, language: str = "python") -> BaseExecutor:
    """Create an executor instance based on settings and language.

    Imports are deferred to avoid crashing when optional dependencies
    (docker, kubernetes, aiohttp) are not installed.
    """
    language = language.lower()
    backend = settings.EXECUTOR_BACKEND.lower()

    executor_cls: type[BaseExecutor] | None = None

    if backend == "microvm":
        from thinkdome.executors.microvm.executor import MicroVMExecutor
        executor_cls = MicroVMExecutor

    elif backend == "docker":
        from thinkdome.executors.docker import PythonDockerExecutor
        if language == "python":
            executor_cls = PythonDockerExecutor
        else:
            from thinkdome.executors.stubs import CppExecutor, JavaExecutor, CSharpExecutor
            executor_cls = {"cpp": CppExecutor, "java": JavaExecutor, "csharp": CSharpExecutor}.get(language)

    elif backend == "kubernetes":
        from thinkdome.executors.kubernetes import PythonKubernetesExecutor
        executor_cls = PythonKubernetesExecutor if language == "python" else None

    elif backend == "subprocess":
        from thinkdome.executors.host.subprocess_executor import SubprocessExecutor
        executor_cls = SubprocessExecutor if language == "python" else None

    elif backend == "hybrid":
        from thinkdome.executors.host.python_hybrid import PythonHybridExecutor
        executor_cls = PythonHybridExecutor if language == "python" else None

    if not executor_cls:
        raise ValueError(
            f"Unsupported backend '{backend}' for language '{language}'."
        )

    try:
        return executor_cls(settings)  # type: ignore
    except TypeError:
        return executor_cls()  # type: ignore

