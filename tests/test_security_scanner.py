"""Unit tests for the output security scanner."""

import pytest
from thinkdome.services.security_scanner import SecurityScanner, Severity, Category


@pytest.fixture
def scanner():
    return SecurityScanner()


def test_security_scanner_clean_output(scanner):
    res = scanner.scan(stdout="Hello, standard output!", stderr="", exit_code=0)
    assert res.threat_level == "CLEAN"
    assert not res.has_findings


def test_security_scanner_network_detection(scanner):
    # NXDOMAIN / DNS errors
    res = scanner.scan(stdout="", stderr="ERROR: getaddrinfo failed to resolve host NXDOMAIN", exit_code=1)
    assert res.threat_level == "MEDIUM"
    assert res.has_findings
    assert res.findings[0].category == Category.NETWORK
    assert res.findings[0].severity == Severity.WARNING

    # Socket connect string
    res2 = scanner.scan(stdout="import socket; socket.connect(('1.1.1.1', 80))", stderr="", exit_code=0)
    assert res2.has_findings
    assert res2.findings[0].severity == Severity.INFO


def test_security_scanner_filesystem_escape(scanner):
    # /etc/passwd access
    res = scanner.scan(stdout="root:x:0:0:root:/root:/bin/bash in /etc/passwd contents", stderr="", exit_code=0)
    assert res.threat_level == "CRITICAL"
    assert res.critical_count == 1
    assert res.findings[0].category == Category.FILESYSTEM

    # Path traversal
    res2 = scanner.scan(stdout="Trying to write into ../../etc/passwd", stderr="", exit_code=0)
    assert res2.threat_level == "CRITICAL"


def test_security_scanner_privilege_escalation(scanner):
    res = scanner.scan(stdout="sandboxuser is running: sudo su root", stderr="", exit_code=0)
    assert res.threat_level == "CRITICAL"
    assert res.findings[0].category == Category.PRIVILEGE


def test_security_scanner_reverse_shell(scanner):
    res = scanner.scan(stdout="sh -c 'nc -lvp 4444 -e /bin/sh'", stderr="", exit_code=0)
    assert res.threat_level == "CRITICAL"
    assert res.findings[0].category == Category.ESCAPE


def test_security_scanner_exit_codes(scanner):
    # Segfault
    res = scanner.scan(stdout="", stderr="Crash report", exit_code=139)
    assert res.threat_level == "CRITICAL"
    assert res.findings[0].category == Category.CRASH
    assert "Segmentation fault" in res.findings[0].recommendation

    # Timeout
    res2 = scanner.scan(stdout="", stderr="", exit_code=124)
    assert res2.threat_level == "MEDIUM"
    assert res2.findings[0].category == Category.CRASH


def test_security_scanner_stateful_ssrf(scanner):
    token = "test_token_ssrf"
    
    # 1st network probe
    res = scanner.scan(stdout="Connection refused", token_id=token)
    assert res.threat_level == "MEDIUM"
    
    # 2nd network probe
    res = scanner.scan(stdout="NXDOMAIN", token_id=token)
    assert res.threat_level == "MEDIUM"

    # 3rd network probe (triggers multi-step SSRF threat warning)
    res = scanner.scan(stdout="Connection refused", token_id=token)
    assert res.threat_level == "CRITICAL"
    
    # Verify we have the stateful warning
    recon_findings = [f for f in res.findings if f.category == Category.RECONNAISSANCE]
    assert len(recon_findings) == 1
    assert "SSRF reconnaissance" in recon_findings[0].evidence
