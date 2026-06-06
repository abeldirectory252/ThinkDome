"""Executor factory â€” selects backend based on configuration."""

from __future__ import annotations

from thinkdome.core.config import Settings
from thinkdome.executors.base import BaseExecutor
from thinkdome.executors.python_docker import PythonDockerExecutor
from thinkdome.executors.subprocess_executor import SubprocessExecutor
from thinkdome.executors.cpp_stub import CppExecutor
from thinkdome.executors.java_stub import JavaExecutor
from thinkdome.executors.csharp_stub import CSharpExecutor


_LANGUAGE_EXECUTORS: dict[str, dict[str, type[BaseExecutor]]] = {
    "python": {
        "docker": PythonDockerExecutor,
        "subprocess": SubprocessExecutor,
    },
    "cpp": {"docker": CppExecutor},
    "java": {"docker": JavaExecutor},
    "csharp": {"docker": CSharpExecutor},
}


def create_executor(settings: Settings, language: str = "python") -> BaseExecutor:
    """Create an executor instance based on settings and language."""
    language = language.lower()
    backend = settings.EXECUTOR_BACKEND.lower()

    lang_backends = _LANGUAGE_EXECUTORS.get(language)
    if not lang_backends:
        raise ValueError(f"Unsupported language: {language}")

    executor_cls = lang_backends.get(backend)
    if not executor_cls:
        raise ValueError(
            f"Unsupported backend '{backend}' for language '{language}'. "
            f"Available: {list(lang_backends.keys())}"
        )

    # Executors that accept settings
    try:
        return executor_cls(settings)  # type: ignore
    except TypeError:
        return executor_cls()  # type: ignore
