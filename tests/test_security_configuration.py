"""Security-sensitive configuration defaults and parsing."""

import pytest

from thinkdome.core.config import Settings


def test_cors_is_disabled_by_default():
    assert Settings(CORS_ALLOW_ORIGINS="").cors_allow_origins() == []


def test_cors_accepts_only_explicit_origins():
    settings = Settings(CORS_ALLOW_ORIGINS="https://console.example, https://app.example ")
    assert settings.cors_allow_origins() == ["https://console.example", "https://app.example"]


def test_host_subprocess_fallback_is_never_available_in_production():
    assert not Settings(
        DEPLOYMENT_ENV="production", EXECUTOR_BACKEND_USE_FALLBACK=True
    ).allows_insecure_execution_fallback()
    assert Settings(
        DEPLOYMENT_ENV="development", EXECUTOR_BACKEND_USE_FALLBACK=True
    ).allows_insecure_execution_fallback()


def test_production_rejects_host_subprocess_backend():
    with pytest.raises(RuntimeError, match="subprocess execution backend"):
        Settings(DEPLOYMENT_ENV="production", EXECUTOR_BACKEND="subprocess").validate_production_runtime()


def test_production_requires_immutable_docker_image():
    with pytest.raises(RuntimeError, match="immutable"):
        Settings(DEPLOYMENT_ENV="production", EXECUTOR_BACKEND="docker", EXECUTOR_IMAGE="runner:latest").validate_production_runtime()
