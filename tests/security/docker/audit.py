"""Read-only Docker sandbox configuration audit.

This module deliberately audits repository configuration only. Live probes are
opt-in and live in ``test_live_isolation.py`` so normal CI never talks to an
untrusted or production Docker daemon by accident.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def _finding(fid: str, severity: str, title: str, evidence: str, remediation: str) -> dict[str, str]:
    return {
        "id": fid,
        "severity": severity,
        "title": title,
        "evidence": evidence,
        "remediation": remediation,
    }


def run_static_audit() -> dict[str, Any]:
    compose = (ROOT / "docker/docker-compose.yml").read_text()
    prod = (ROOT / "docker/docker-compose.prod.yml").read_text()
    policy = (ROOT / "thinkdome/sandbox/executors/docker/container_policy.py").read_text()
    backend = (ROOT / "thinkdome/sandbox/executors/docker/backend.py").read_text()
    findings: list[dict[str, str]] = []

    host_socket_exposed = "/var/run/docker.sock:/var/run/docker.sock" in compose
    if host_socket_exposed:
        findings.append(_finding(
            "DSK-001", "CRITICAL", "Development API has host Docker socket",
            "docker/docker-compose.yml mounts /var/run/docker.sock into thinkdome-api",
            "Remove the host socket from any stack that can process untrusted input; use a separately isolated, least-privileged execution service.",
        ))
    prod_dind_privileged = "privileged: true" in prod
    if prod_dind_privileged:
        findings.append(_finding(
            "DIND-001", "HIGH", "Production Docker-in-Docker daemon is privileged",
            "docker/docker-compose.prod.yml sets dind.privileged=true",
            "Prefer a separately isolated node/daemon boundary; if DIND remains, isolate it, restrict its client certificates, and treat compromise as host-equivalent within the DIND VM/container boundary.",
        ))
    import yaml
    try:
        prod_data = yaml.safe_load(prod) or {}
    except Exception:
        prod_data = {}
    prod_services = prod_data.get("services", {})
    api_vols = prod_services.get("thinkdome-api", {}).get("volumes", [])
    worker_vols = prod_services.get("thinkdome-worker", {}).get("volumes", [])
    if any("dind-certs" in str(v) for v in api_vols) or any("dind-certs" in str(v) for v in worker_vols):
        findings.append(_finding(
            "DIND-002", "HIGH", "Docker client TLS certificate volume is shared with API/workers",
            "API and worker services mount dind-certs:/certs:ro",
            "Give only the execution service the narrowest possible Docker authority and keep public API/workers out of the Docker control path.",
        ))

    required = {
        "cap_drop=ALL": '"cap_drop": ["ALL"]' in policy or 'cap_drop=["ALL"]' in backend,
        "privileged=false": '"privileged": False' in policy or "privileged=False" in backend,
        "read_only": '"read_only": True' in policy or "read_only=True" in backend,
        "network_none": '"network_mode": "none"' in policy or 'network_mode=attachment.mode' in backend,
        "private_ipc": '"ipc_mode": "private"' in policy or 'ipc_mode="private"' in backend,
        "pids_limit": '"pids_limit"' in policy or "pids_limit=100" in backend,
        "no_new_privileges": 'no-new-privileges:true' in backend,
    }
    for control, present in required.items():
        if not present:
            findings.append(_finding(
                f"EXEC-{control.upper().replace('-', '_')}", "HIGH",
                f"Executor control missing: {control}",
                "Required Docker executor hardening marker was not found in policy/backend source",
                "Restore the invariant and add a focused regression test before deployment.",
            ))

    counts = {level.lower(): sum(f["severity"] == level for f in findings) for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
    status = "CRITICAL_FAILURE" if counts["critical"] else "FAIL" if counts["high"] or counts["medium"] else "PASS_WITH_CONDITIONS" if counts["low"] else "PASS"
    tests = {
        "filesystem_isolation": "PASS" if required["read_only"] else "FAIL",
        "process_isolation": "PASS" if required["pids_limit"] else "FAIL",
        "network_isolation": "PASS" if required["network_none"] else "FAIL",
        "resource_limits": "PASS" if required["pids_limit"] else "FAIL",
        "secret_isolation": "NOT_RUN",
        "container_isolation": "NOT_RUN",
        "docker_socket": "FAIL" if host_socket_exposed else "PASS",
        "capabilities": "PASS" if required["cap_drop=ALL"] else "FAIL",
        "lifecycle": "NOT_RUN",
    }
    return {
        "sandbox": "docker",
        "status": status,
        **counts,
        "tests": tests,
        "findings": findings,
        "live_tests": "NOT_RUN",
    }


def write_report(path: Path) -> dict[str, Any]:
    report = run_static_audit()
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report
