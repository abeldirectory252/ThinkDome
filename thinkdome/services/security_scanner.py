"""Security scanner — post-execution output analysis for threat detection.

Scans stdout, stderr, and exit codes from sandbox executions to detect:
  - Network access attempts (connection refused, DNS errors, socket calls)
  - Filesystem escape attempts (/etc/passwd, ../../, permission denied)
  - Privilege escalation (sudo, su root, setuid)
  - Container escape attempts (mount, unshare, docker.sock)
  - Reverse shell patterns (nc -e, bash -i, /dev/tcp)
  - Crash/exploit signals via exit code analysis (SIGSEGV, SIGABRT, etc.)
  - Stateful SSRF reconnaissance across consecutive executions
"""

from __future__ import annotations

import re
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Deque, Tuple

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class Category(str, Enum):
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    PRIVILEGE = "privilege"
    ESCAPE = "escape"
    CRASH = "crash"
    RECONNAISSANCE = "reconnaissance"


@dataclass
class SecurityFinding:
    """A single security finding from output analysis."""
    severity: Severity
    category: Category
    pattern_matched: str
    evidence: str
    recommendation: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "category": self.category.value,
            "pattern_matched": self.pattern_matched,
            "evidence": self.evidence[:500],  # Truncate long evidence
            "recommendation": self.recommendation,
            "timestamp": self.timestamp,
        }


@dataclass
class ScanResult:
    """Result of a security scan."""
    findings: List[SecurityFinding] = field(default_factory=list)
    threat_level: str = "CLEAN"  # CLEAN | LOW | MEDIUM | HIGH | CRITICAL
    scan_duration_ms: float = 0.0

    @property
    def has_findings(self) -> bool:
        return len(self.findings) > 0

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.WARNING)

    def to_dict(self) -> dict:
        return {
            "threat_level": self.threat_level,
            "finding_count": len(self.findings),
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "scan_duration_ms": round(self.scan_duration_ms, 2),
            "findings": [f.to_dict() for f in self.findings],
        }


# ── Pattern Definitions ───────────────────────────────────────────────────────

# Each pattern is: (compiled_regex, severity, category, recommendation)
_PatternDef = Tuple[re.Pattern, Severity, Category, str]

NETWORK_PATTERNS: List[_PatternDef] = [
    (
        re.compile(r"Connection refused|ECONNREFUSED", re.IGNORECASE),
        Severity.WARNING, Category.NETWORK,
        "Code attempted an outbound network connection. Sandbox network is disabled by default."
    ),
    (
        re.compile(r"Name or service not known|DNS resolution|NXDOMAIN|getaddrinfo failed", re.IGNORECASE),
        Severity.WARNING, Category.NETWORK,
        "DNS resolution attempted. This suggests outbound network activity."
    ),
    (
        re.compile(r"socket\.connect|urllib\.request|requests\.get|requests\.post|httpx\.", re.IGNORECASE),
        Severity.INFO, Category.NETWORK,
        "Network library call detected in output. Verify if network access is intended."
    ),
    (
        re.compile(r"curl\s+https?://|wget\s+https?://", re.IGNORECASE),
        Severity.WARNING, Category.NETWORK,
        "Command-line HTTP client invocation detected."
    ),
]

FILESYSTEM_PATTERNS: List[_PatternDef] = [
    (
        re.compile(r"/etc/passwd|/etc/shadow|/etc/sudoers", re.IGNORECASE),
        Severity.CRITICAL, Category.FILESYSTEM,
        "Access to sensitive system files detected. Possible credential harvesting attempt."
    ),
    (
        re.compile(r"\.\./\.\./|\.\.\\\.\.\\", re.IGNORECASE),
        Severity.CRITICAL, Category.FILESYSTEM,
        "Path traversal sequence detected. Possible sandbox escape attempt."
    ),
    (
        re.compile(r"Permission denied|EACCES|Operation not permitted", re.IGNORECASE),
        Severity.INFO, Category.FILESYSTEM,
        "Permission denied error — sandbox isolation is working correctly."
    ),
    (
        re.compile(r"/proc/self|/proc/1/|/sys/fs/cgroup", re.IGNORECASE),
        Severity.WARNING, Category.FILESYSTEM,
        "Access to /proc or /sys detected. Possible container information gathering."
    ),
]

PRIVILEGE_PATTERNS: List[_PatternDef] = [
    (
        re.compile(r"\bsudo\b|\bsu\s+root\b|\bsu\s+-\b", re.IGNORECASE),
        Severity.CRITICAL, Category.PRIVILEGE,
        "Privilege escalation command detected. Sandbox runs as non-root (UID 1000)."
    ),
    (
        re.compile(r"setuid|setgid|chmod\s+[ugo]*s|chmod\s+[0-7]*[4-7][0-7]{2}", re.IGNORECASE),
        Severity.CRITICAL, Category.PRIVILEGE,
        "Set-UID/GID manipulation detected. This is blocked by capability dropping."
    ),
    (
        re.compile(r"operation not permitted|EPERM", re.IGNORECASE),
        Severity.INFO, Category.PRIVILEGE,
        "Operation blocked by sandbox security — isolation is working."
    ),
]

ESCAPE_PATTERNS: List[_PatternDef] = [
    (
        re.compile(r"\bmount\b|\bumount\b|pivot_root|chroot", re.IGNORECASE),
        Severity.CRITICAL, Category.ESCAPE,
        "Filesystem namespace manipulation detected. Possible container escape attempt."
    ),
    (
        re.compile(r"\bunshare\b|\bnsenter\b|\bsetns\b", re.IGNORECASE),
        Severity.CRITICAL, Category.ESCAPE,
        "Namespace manipulation command detected. Blocked by seccomp profile."
    ),
    (
        re.compile(r"docker\.sock|/var/run/docker", re.IGNORECASE),
        Severity.CRITICAL, Category.ESCAPE,
        "Docker socket access attempt detected. Critical container escape vector."
    ),
    (
        re.compile(r"nc\s+-[elp]|ncat\s+-|bash\s+-i\s*>|/dev/tcp/|python.*socket.*connect", re.IGNORECASE),
        Severity.CRITICAL, Category.ESCAPE,
        "Reverse shell pattern detected. Immediate threat — possible remote access attempt."
    ),
    (
        re.compile(r"kexec|init_module|finit_module|insmod|modprobe", re.IGNORECASE),
        Severity.CRITICAL, Category.ESCAPE,
        "Kernel module operation detected. Blocked by seccomp profile."
    ),
]

# All patterns combined for scanning
ALL_PATTERNS: List[_PatternDef] = (
    NETWORK_PATTERNS + FILESYSTEM_PATTERNS + PRIVILEGE_PATTERNS + ESCAPE_PATTERNS
)

# Exit code analysis
EXIT_CODE_SIGNALS: Dict[int, Tuple[Severity, Category, str]] = {
    124: (Severity.WARNING, Category.CRASH, "Process timed out (SIGTERM). Execution exceeded the allowed time limit."),
    126: (Severity.INFO, Category.RECONNAISSANCE, "Permission denied on exec. Code tried to execute a non-executable file."),
    127: (Severity.INFO, Category.RECONNAISSANCE, "Command not found. Possible environment probing."),
    134: (Severity.WARNING, Category.CRASH, "Process aborted (SIGABRT). Possible crash exploit or assertion failure."),
    136: (Severity.WARNING, Category.CRASH, "Floating point exception (SIGFPE). Possible arithmetic exploit."),
    137: (Severity.WARNING, Category.CRASH, "Process killed (SIGKILL). Likely OOM-killed or exceeded resource limits."),
    139: (Severity.CRITICAL, Category.CRASH, "Segmentation fault (SIGSEGV). Memory corruption — possible exploit attempt."),
}


class SecurityScanner:
    """Stateful security scanner for sandbox execution output.

    Maintains per-token state to detect multi-step attack patterns (e.g., SSRF
    reconnaissance across consecutive executions).

    Usage:
        scanner = SecurityScanner()
        result = scanner.scan(stdout, stderr, exit_code, token_id="td_llm_xxx")
        if result.has_findings:
            for finding in result.findings:
                print(f"[{finding.severity}] {finding.category}: {finding.evidence}")
    """

    def __init__(self, max_history: int = 100) -> None:
        # Per-token history for stateful detection: token_id -> deque of (timestamp, findings)
        self._token_history: Dict[str, Deque[Tuple[float, List[SecurityFinding]]]] = {}
        self._max_history = max_history

        # Global scan counters
        self._total_scans: int = 0
        self._total_findings: int = 0
        self._critical_findings: int = 0

    def scan(
        self,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = 0,
        token_id: Optional[str] = None,
    ) -> ScanResult:
        """Scan execution output for security threats.

        Args:
            stdout: Standard output from execution
            stderr: Standard error from execution
            exit_code: Process exit code
            token_id: Optional token identifier for stateful tracking

        Returns:
            ScanResult with any findings and overall threat level
        """
        start = time.monotonic()
        findings: List[SecurityFinding] = []

        # Combine output for pattern scanning
        combined = f"{stdout}\n{stderr}"

        # 1. Pattern-based output scanning
        for pattern, severity, category, recommendation in ALL_PATTERNS:
            for match in pattern.finditer(combined):
                # Extract context around the match (up to 100 chars each side)
                start_idx = max(0, match.start() - 100)
                end_idx = min(len(combined), match.end() + 100)
                evidence = combined[start_idx:end_idx].strip()

                findings.append(SecurityFinding(
                    severity=severity,
                    category=category,
                    pattern_matched=pattern.pattern,
                    evidence=evidence,
                    recommendation=recommendation,
                ))

        # 2. Exit code analysis
        if exit_code in EXIT_CODE_SIGNALS:
            severity, category, recommendation = EXIT_CODE_SIGNALS[exit_code]
            findings.append(SecurityFinding(
                severity=severity,
                category=category,
                pattern_matched=f"exit_code={exit_code}",
                evidence=f"Process exited with code {exit_code}",
                recommendation=recommendation,
            ))

        # 3. Stateful SSRF detection (across consecutive executions)
        if token_id:
            ssrf_findings = self._check_ssrf_pattern(token_id, findings)
            findings.extend(ssrf_findings)

            # Store in history
            if token_id not in self._token_history:
                self._token_history[token_id] = deque(maxlen=self._max_history)
            self._token_history[token_id].append((time.time(), findings))

        # 4. Determine overall threat level
        threat_level = self._classify_threat_level(findings)

        # Update counters
        self._total_scans += 1
        self._total_findings += len(findings)
        self._critical_findings += sum(1 for f in findings if f.severity == Severity.CRITICAL)

        duration_ms = (time.monotonic() - start) * 1000

        if findings:
            logger.info(
                f"🔍 Security scan: {len(findings)} findings "
                f"(threat_level={threat_level}, duration={duration_ms:.1f}ms)"
            )
            for f in findings:
                if f.severity == Severity.CRITICAL:
                    logger.warning(f"🚨 CRITICAL: [{f.category.value}] {f.evidence[:200]}")

        return ScanResult(
            findings=findings,
            threat_level=threat_level,
            scan_duration_ms=duration_ms,
        )

    def _check_ssrf_pattern(
        self, token_id: str, current_findings: List[SecurityFinding]
    ) -> List[SecurityFinding]:
        """Detect multi-step SSRF reconnaissance from a single token."""
        extra_findings: List[SecurityFinding] = []

        history = self._token_history.get(token_id)
        if not history:
            return extra_findings

        # Count network-related findings in the last 60 seconds
        now = time.time()
        recent_network = 0
        for ts, findings in history:
            if now - ts < 60:
                recent_network += sum(
                    1 for f in findings if f.category == Category.NETWORK
                )

        # Current findings
        current_network = sum(1 for f in current_findings if f.category == Category.NETWORK)
        total_recent = recent_network + current_network

        # Threshold: 3+ network findings in 60 seconds = potential SSRF
        if total_recent >= 3:
            extra_findings.append(SecurityFinding(
                severity=Severity.CRITICAL,
                category=Category.RECONNAISSANCE,
                pattern_matched="ssrf_multi_step",
                evidence=(
                    f"Token {token_id[:20]}... generated {total_recent} network-related "
                    f"findings in the last 60 seconds. Possible SSRF reconnaissance."
                ),
                recommendation=(
                    "Consider revoking this token. Multiple consecutive network "
                    "probing attempts suggest automated SSRF scanning."
                ),
            ))

        return extra_findings

    def _classify_threat_level(self, findings: List[SecurityFinding]) -> str:
        """Classify the overall threat level from findings."""
        if not findings:
            return "CLEAN"

        severities = [f.severity for f in findings]

        if Severity.CRITICAL in severities:
            return "CRITICAL"
        elif severities.count(Severity.WARNING) >= 3:
            return "HIGH"
        elif Severity.WARNING in severities:
            return "MEDIUM"
        else:
            return "LOW"

    def get_stats(self) -> dict:
        """Return scanner statistics."""
        return {
            "total_scans": self._total_scans,
            "total_findings": self._total_findings,
            "critical_findings": self._critical_findings,
            "tracked_tokens": len(self._token_history),
        }

    def clear_token_history(self, token_id: str) -> None:
        """Clear history for a specific token (e.g., on revocation)."""
        self._token_history.pop(token_id, None)
