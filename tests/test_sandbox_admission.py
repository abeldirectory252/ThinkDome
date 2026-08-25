"""Admission and lease validation regressions."""

import pytest

from thinkdome.security.api.admin import CreateSandboxRequest


def test_lease_ttl_is_bounded_to_72_hours():
    assert CreateSandboxRequest(name="demo", ttl_seconds=259200).ttl_seconds == 259200
    with pytest.raises(ValueError):
        CreateSandboxRequest(name="demo", ttl_seconds=259201)


def test_python_dependencies_are_validated_before_persistence():
    request = CreateSandboxRequest(
        name="demo",
        python_dependencies=["numpy==2.1.0", "requests>=2.32"],
    )
    assert request.python_dependencies == ["numpy==2.1.0", "requests>=2.32"]
    with pytest.raises(ValueError):
        CreateSandboxRequest(name="demo", python_dependencies=["numpy; rm -rf /"])
