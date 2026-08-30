"""Static Docker security regressions; no Docker daemon required."""

from pathlib import Path

from tests.security.docker.audit import ROOT, run_static_audit


def test_executor_policy_has_required_isolation_invariants():
    report = run_static_audit()
    assert report["tests"]["capabilities"] == "PASS"
    assert report["tests"]["filesystem_isolation"] == "PASS"
    assert report["tests"]["network_isolation"] == "PASS"
    assert report["tests"]["process_isolation"] == "PASS"


def test_executor_source_does_not_expose_docker_or_runtime_sockets():
    source = "\n".join(
        p.read_text(errors="ignore")
        for p in (ROOT / "thinkdome/sandbox").rglob("*.py")
    )
    for socket in ("/var/run/docker.sock", "/run/docker.sock", "/run/containerd/"):
        assert socket not in source


def test_executor_cannot_become_privileged_or_add_capabilities():
    source = (ROOT / "thinkdome/sandbox/executors/docker/backend.py").read_text()
    policy = (ROOT / "thinkdome/sandbox/executors/docker/container_policy.py").read_text()
    assert "privileged=True" not in source
    assert '"privileged": True' not in policy
    assert "cap_add" not in source
    assert '"cap_add"' not in policy


def test_development_stack_does_not_expose_host_docker_socket():
    report = run_static_audit()
    assert not any(f["id"] == "DSK-001" for f in report["findings"])


def test_seccomp_is_default_deny_and_blocks_namespace_escape_primitives():
    import json

    profile = json.loads((ROOT / "security/seccomp.json").read_text())
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
    names = {name for group in profile["syscalls"] for name in group.get("names", [])}
    assert not names.intersection({"mount", "umount2", "pivot_root", "setns", "unshare", "ptrace", "bpf", "init_module", "finit_module"})


def test_sandbox_scoped_routes_require_owner_authorization():
    for name in ("diagnostics.py", "lifecycle.py", "metadata.py"):
        source = (ROOT / "thinkdome/api/routes/execution" / name).read_text()
        assert "authorize_sandbox_access(request, sandbox_id, user)" in source


def test_docker_execution_environment_is_sanitized():
    source = (ROOT / "thinkdome/sandbox/executors/docker/container_policy.py").read_text()
    assert "sanitize_environment" in source
    assert "PROXY_VARIABLES" in source
    assert "_is_env_var_sensitive" in source


def test_legacy_controller_uses_hardened_executor_policy():
    source = (ROOT / "thinkdome/apps/sandbox/controller.py").read_text()
    assert "image=settings.EXECUTOR_IMAGE" in source
    assert 'network_mode=attachment.mode' in source
    assert 'user="1000:1000"' in source
    assert "read_only=True" in source
    assert 'cap_drop=["ALL"]' in source
    assert "privileged=False" in source
    assert 'ipc_mode="private"' in source
    assert "pids_limit=100" in source


def test_production_dind_is_not_privileged():
    source = (ROOT / "docker/docker-compose.prod.yml").read_text()
    assert "EXECUTOR_DOCKER_HOST:?" in source
    assert "EXECUTOR_DOCKER_CERT_DIR:?" in source
    assert "image: docker:dind" not in source
    assert "image: docker:dind-rootless" not in source
    assert "privileged: true" not in source
    assert "thinkdome-docker-executor" in source


def test_production_executor_token_has_no_weak_default():
    source = (ROOT / "docker/docker-compose.prod.yml").read_text()
    assert "EXECUTOR_CONTROL_AUTH_TOKEN:-thinkdome" not in source
    assert "EXECUTOR_CONTROL_AUTH_TOKEN:?" in source


def test_production_requires_immutable_executor_image():
    source = (ROOT / "docker/docker-compose.prod.yml").read_text()
    assert "EXECUTOR_IMAGE:?" in source
    assert "EXECUTOR_IMAGE: thinkdome-executor:latest" not in source


def test_production_does_not_publish_internal_infrastructure_ports():
    source = (ROOT / "docker/docker-compose.prod.yml").read_text()
    for port in ('"5432:5432"', '"5672:5672"', '"15672:15672"', '"6379:6379"', '"4317:4317"', '"4318:4318"', '"8888:8888"'):
        assert port not in source


def test_production_infrastructure_images_are_digest_pinned():
    import yaml

    services = yaml.safe_load((ROOT / "docker/docker-compose.prod.yml").read_text())["services"]
    for name in ("postgres", "rabbitmq", "redis", "otel-collector"):
        image = services[name]["image"]
        assert "@sha256:" in image
        assert ":latest" not in image


def test_production_does_not_use_default_infrastructure_credentials():
    source = (ROOT / "docker/docker-compose.prod.yml").read_text()
    assert "postgresql://thinkdome:thinkdome@" not in source
    assert "amqp://guest:guest@" not in source
    assert "POSTGRES_PASSWORD: thinkdome" not in source


def test_production_api_worker_and_executor_are_non_root():
    import yaml

    services = yaml.safe_load((ROOT / "docker/docker-compose.prod.yml").read_text())["services"]
    for service in ("thinkdome-api:", "thinkdome-worker:", "thinkdome-docker-executor:"):
        assert services[service[:-1]].get("user") == "1000:1000"


def test_security_report_template_is_machine_readable():
    report_path = ROOT / "security-report.json"
    assert report_path.is_file()
    assert report_path.read_text().strip().startswith("{")
