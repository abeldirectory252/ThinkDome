#!/usr/bin/env python3
"""
sandbox_escape_test.py — MicroVM / Sandbox Isolation Boundary Audit
====================================================================
A comprehensive, non-destructive security audit script that probes the
isolation boundaries of a Linux sandbox or MicroVM environment across
three severity tiers.

Author:  AI Security Audit Agent
License: Internal Use — Red Team Assessment
Python:  3.8+ (stdlib only)

Usage:
    python3 sandbox_escape_test.py
"""

import ctypes
import fcntl
import glob
import http.client
import os
import platform
import socket
import struct
import subprocess
import sys
import textwrap
import time
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────── Data Structures ──────────────────────────

TIER_SIMPLE = "SIMPLE"
TIER_MIDDLE = "MIDDLE"
TIER_HARD   = "HARD"

STATUS_SECURE     = "SECURE"
STATUS_VULNERABLE = "VULNERABLE"
STATUS_INFO       = "INFO"
STATUS_ERROR      = "ERROR"

TestResult = namedtuple("TestResult", ["tier", "name", "status", "detail"])

# Global results accumulator
_results: list[TestResult] = []


def record(tier: str, name: str, status: str, detail: str) -> None:
    """Record a single test result and print it live."""
    _results.append(TestResult(tier, name, status, detail))
    icons = {
        STATUS_SECURE:     "\033[92m[SECURE]\033[0m",
        STATUS_VULNERABLE: "\033[91m[VULNERABLE]\033[0m",
        STATUS_INFO:       "\033[93m[INFO]\033[0m",
        STATUS_ERROR:      "\033[90m[ERROR]\033[0m",
    }
    icon = icons.get(status, f"[{status}]")
    print(f"  {icon}  {name}")
    if detail:
        for line in detail.strip().splitlines():
            print(f"           {line}")
    print()


# ═══════════════════════════════════════════════════════════════════════
#  TIER 1 — SIMPLE: Basic Container & Environment Probing
# ═══════════════════════════════════════════════════════════════════════

def test_privilege_check() -> None:
    """Check for unmitigated root access by reading /etc/shadow and uid."""
    name = "Privilege Escalation Check"
    try:
        uid = os.getuid()
        euid = os.geteuid()
        id_output = subprocess.check_output(["id"], text=True, timeout=5).strip()

        shadow_readable = False
        try:
            with open("/etc/shadow", "r") as f:
                f.read(1)
            shadow_readable = True
        except PermissionError:
            shadow_readable = False

        if uid == 0 or euid == 0:
            record(TIER_SIMPLE, name, STATUS_VULNERABLE,
                   f"Running as root (uid={uid}, euid={euid}).\n"
                   f"id: {id_output}\n"
                   f"/etc/shadow readable: {shadow_readable}")
        elif shadow_readable:
            record(TIER_SIMPLE, name, STATUS_VULNERABLE,
                   f"Not root (uid={uid}) but /etc/shadow is readable!\n"
                   f"id: {id_output}")
        else:
            record(TIER_SIMPLE, name, STATUS_SECURE,
                   f"Unprivileged user (uid={uid}). /etc/shadow not readable.\n"
                   f"id: {id_output}")
    except Exception as e:
        record(TIER_SIMPLE, name, STATUS_ERROR, str(e))


def test_kernel_version_probe() -> None:
    """Read /proc/version and /proc/cmdline for host parameter leakage."""
    name = "Kernel Version & Boot Parameter Leakage"
    try:
        details = []
        version = Path("/proc/version").read_text().strip()
        details.append(f"Kernel: {version[:120]}")

        try:
            cmdline = Path("/proc/cmdline").read_text().strip()
            details.append(f"Cmdline: {cmdline[:200]}")
            # Flag common host-leaking indicators
            host_indicators = ["root=UUID=", "BOOT_IMAGE=", "console=ttyS",
                               "cloud-hypervisor", "firecracker", "vmlinuz"]
            leaks = [ind for ind in host_indicators if ind.lower() in cmdline.lower()]
            if leaks:
                details.append(f"Host boot indicators found: {', '.join(leaks)}")
        except PermissionError:
            details.append("Cmdline: access denied (good — restricted)")

        # Determine if kernel info reveals host context
        hypervisor_hints = ["kvm", "hypervisor", "vmware", "xen", "hyper-v"]
        found = [h for h in hypervisor_hints if h.lower() in version.lower()]

        if found:
            record(TIER_SIMPLE, name, STATUS_INFO,
                   "\n".join(details) + f"\nHypervisor hints in kernel: {found}")
        else:
            record(TIER_SIMPLE, name, STATUS_SECURE,
                   "\n".join(details) + "\nNo obvious hypervisor leakage in kernel string.")
    except Exception as e:
        record(TIER_SIMPLE, name, STATUS_ERROR, str(e))


def test_hardware_leakage() -> None:
    """Scan DMI and cpuinfo for underlying host hardware signatures."""
    name = "Hardware Identity Leakage (DMI / CPUINFO)"
    try:
        details = []
        # DMI identity files
        dmi_dir = Path("/sys/class/dmi/id")
        dmi_fields = ["sys_vendor", "product_name", "board_vendor",
                      "bios_vendor", "chassis_type"]
        dmi_data = {}
        for field in dmi_fields:
            fpath = dmi_dir / field
            try:
                dmi_data[field] = fpath.read_text().strip()
            except (PermissionError, FileNotFoundError):
                dmi_data[field] = "<restricted>"

        for k, v in dmi_data.items():
            details.append(f"DMI {k}: {v}")

        # CPU model from /proc/cpuinfo
        try:
            cpuinfo = Path("/proc/cpuinfo").read_text()
            for line in cpuinfo.splitlines():
                if line.startswith("model name"):
                    details.append(f"CPU: {line.split(':', 1)[1].strip()}")
                    break
        except Exception:
            pass

        # Evaluate: bare-metal CPU names leak host info
        bare_metal_indicators = ["Xeon", "EPYC", "Threadripper", "Ryzen",
                                 "i7-", "i9-", "Core(TM)"]
        combined = " ".join(dmi_data.values()) + " " + " ".join(details)
        leaks = [ind for ind in bare_metal_indicators if ind in combined]

        if leaks:
            record(TIER_SIMPLE, name, STATUS_INFO,
                   "\n".join(details) +
                   f"\nHost hardware identifiers visible: {leaks}")
        else:
            record(TIER_SIMPLE, name, STATUS_SECURE,
                   "\n".join(details) + "\nNo bare-metal CPU model leakage detected.")
    except Exception as e:
        record(TIER_SIMPLE, name, STATUS_ERROR, str(e))


def test_environment_variables() -> None:
    """Check for sensitive host environment variables leaking into the sandbox."""
    name = "Environment Variable Leakage"
    try:
        sensitive_prefixes = ["AWS_", "AZURE_", "GCP_", "GOOGLE_", "DOCKER_HOST",
                              "KUBERNETES_", "K8S_", "VAULT_", "TOKEN", "SECRET",
                              "API_KEY", "PASSWD", "CREDENTIAL"]
        leaked = {}
        for key, val in os.environ.items():
            for prefix in sensitive_prefixes:
                if key.upper().startswith(prefix) or prefix in key.upper():
                    # Mask the value for safety
                    leaked[key] = val[:8] + "..." if len(val) > 8 else val
                    break

        if leaked:
            leak_lines = [f"  {k} = {v}" for k, v in leaked.items()]
            record(TIER_SIMPLE, name, STATUS_VULNERABLE,
                   f"Found {len(leaked)} sensitive env vars:\n" + "\n".join(leak_lines))
        else:
            record(TIER_SIMPLE, name, STATUS_SECURE,
                   "No sensitive credential env vars leaked into sandbox.")
    except Exception as e:
        record(TIER_SIMPLE, name, STATUS_ERROR, str(e))


def test_proc_self_status() -> None:
    """Check /proc/self/status for capability and seccomp information."""
    name = "Process Capabilities & Seccomp Status"
    try:
        status = Path("/proc/self/status").read_text()
        details = []
        for line in status.splitlines():
            if any(line.startswith(f) for f in
                   ["CapEff", "CapPrm", "CapBnd", "CapInh", "CapAmb",
                    "Seccomp", "NoNewPrivs"]):
                details.append(line.strip())

        # Parse effective capabilities
        cap_eff_line = [l for l in details if l.startswith("CapEff")]
        has_caps = False
        if cap_eff_line:
            cap_hex = cap_eff_line[0].split(":", 1)[1].strip()
            cap_val = int(cap_hex, 16)
            # Full capabilities = 0x3fffffffff or similar large value
            if cap_val > 0xFFFF:
                has_caps = True
                details.append(f"⚠ Effective capabilities are HIGH (0x{cap_val:x})")

        seccomp_line = [l for l in details if l.startswith("Seccomp")]
        seccomp_enabled = False
        if seccomp_line:
            mode = seccomp_line[0].split(":", 1)[1].strip()
            seccomp_enabled = mode != "0"
            details.append(
                f"Seccomp mode: {mode} ({'enabled' if seccomp_enabled else 'DISABLED'})")

        if has_caps and not seccomp_enabled:
            record(TIER_SIMPLE, name, STATUS_VULNERABLE,
                   "\n".join(details) +
                   "\nHigh capabilities with no seccomp — breakout risk elevated.")
        elif has_caps:
            record(TIER_SIMPLE, name, STATUS_INFO,
                   "\n".join(details) +
                   "\nHigh capabilities detected but seccomp is active.")
        else:
            record(TIER_SIMPLE, name, STATUS_SECURE, "\n".join(details))
    except Exception as e:
        record(TIER_SIMPLE, name, STATUS_ERROR, str(e))


# ═══════════════════════════════════════════════════════════════════════
#  TIER 2 — MIDDLE: Network Probing & Container Breakouts
# ═══════════════════════════════════════════════════════════════════════

def _get_default_gateway() -> str | None:
    """Parse /proc/net/route to find the default gateway IP."""
    try:
        with open("/proc/net/route", "r") as f:
            for line in f.readlines()[1:]:  # skip header
                fields = line.strip().split()
                if len(fields) >= 3 and fields[1] == "00000000":
                    # Gateway is in hex, little-endian
                    gw_hex = fields[2]
                    gw_bytes = bytes.fromhex(gw_hex)
                    gw_ip = socket.inet_ntoa(gw_bytes[::-1]
                                             if sys.byteorder == "little"
                                             else gw_bytes)
                    return gw_ip
    except Exception:
        pass
    return None


def test_gateway_port_scan() -> None:
    """Scan the default gateway for common management/service ports."""
    name = "Host Gateway TCP Port Scan"
    try:
        gateway = _get_default_gateway()
        if not gateway:
            record(TIER_MIDDLE, name, STATUS_ERROR,
                   "Could not determine default gateway from /proc/net/route.")
            return

        target_ports = {
            22:   "SSH",
            80:   "HTTP",
            443:  "HTTPS",
            2375: "Docker (unencrypted)",
            2376: "Docker (TLS)",
            4243: "Docker (legacy)",
            6443: "Kubernetes API",
            8080: "HTTP-Alt / Management",
            8443: "HTTPS-Alt",
            10250: "Kubelet",
        }

        open_ports = []
        details = [f"Gateway IP: {gateway}"]

        for port, service in target_ports.items():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.5)
            try:
                result = sock.connect_ex((gateway, port))
                if result == 0:
                    open_ports.append((port, service))
                    details.append(f"  ✗ Port {port:>5} ({service}): OPEN")
                else:
                    details.append(f"  ✓ Port {port:>5} ({service}): closed/filtered")
            except socket.timeout:
                details.append(f"  ✓ Port {port:>5} ({service}): timeout")
            finally:
                sock.close()

        # Docker unencrypted or K8s API open = high severity
        critical_ports = {2375, 4243, 6443, 10250}
        critical_open = [p for p, _ in open_ports if p in critical_ports]

        if critical_open:
            record(TIER_MIDDLE, name, STATUS_VULNERABLE,
                   "\n".join(details) +
                   f"\n⚠ CRITICAL management ports reachable: {critical_open}")
        elif open_ports:
            record(TIER_MIDDLE, name, STATUS_INFO,
                   "\n".join(details) +
                   f"\n{len(open_ports)} port(s) open on gateway (non-critical).")
        else:
            record(TIER_MIDDLE, name, STATUS_SECURE,
                   "\n".join(details) + "\nNo gateway ports reachable from sandbox.")
    except Exception as e:
        record(TIER_MIDDLE, name, STATUS_ERROR, str(e))


def test_cloud_metadata_access() -> None:
    """Probe cloud provider metadata endpoints for credential exposure."""
    name = "Cloud Metadata Service (IMDS) Access"
    try:
        # Standard metadata endpoints across providers
        endpoints = [
            # AWS IMDSv1
            ("169.254.169.254", "/latest/meta-data/", {"Host": "169.254.169.254"},
             "AWS IMDSv1"),
            # AWS IMDSv2 (token-based — just test reachability)
            ("169.254.169.254", "/latest/api/token",
             {"X-aws-ec2-metadata-token-ttl-seconds": "21600"}, "AWS IMDSv2 token"),
            # GCP
            ("metadata.google.internal", "/computeMetadata/v1/",
             {"Metadata-Flavor": "Google"}, "GCP Metadata"),
            # Azure
            ("169.254.169.254", "/metadata/instance?api-version=2021-02-01",
             {"Metadata": "true"}, "Azure IMDS"),
            # DigitalOcean
            ("169.254.169.254", "/metadata/v1/", {}, "DigitalOcean Metadata"),
        ]

        accessible = []
        details = []

        for host, path, headers, label in endpoints:
            try:
                conn = http.client.HTTPConnection(host, timeout=2)
                conn.request("GET", path, headers=headers)
                resp = conn.getresponse()
                body_preview = resp.read(256).decode("utf-8", errors="replace")
                conn.close()

                if resp.status < 400:
                    accessible.append(label)
                    details.append(
                        f"  ✗ {label}: HTTP {resp.status} — "
                        f"{body_preview[:80]}...")
                else:
                    details.append(
                        f"  ✓ {label}: HTTP {resp.status} (denied/not found)")
            except (socket.timeout, ConnectionRefusedError, OSError) as exc:
                details.append(f"  ✓ {label}: unreachable ({type(exc).__name__})")
            except Exception as exc:
                details.append(f"  ? {label}: {type(exc).__name__}: {exc}")

        if accessible:
            record(TIER_MIDDLE, name, STATUS_VULNERABLE,
                   "\n".join(details) +
                   f"\n⚠ {len(accessible)} metadata endpoint(s) reachable: "
                   f"{accessible}")
        else:
            record(TIER_MIDDLE, name, STATUS_SECURE,
                   "\n".join(details) +
                   "\nNo cloud metadata endpoints accessible from sandbox.")
    except Exception as e:
        record(TIER_MIDDLE, name, STATUS_ERROR, str(e))


def test_docker_socket_probe() -> None:
    """Check for mounted and writable container runtime sockets."""
    name = "Container Runtime Socket Exposure"
    try:
        socket_paths = [
            "/var/run/docker.sock",
            "/run/docker.sock",
            "/var/run/containerd/containerd.sock",
            "/run/containerd/containerd.sock",
            "/var/run/crio/crio.sock",
            "/run/crio/crio.sock",
        ]

        details = []
        writable_sockets = []
        readable_sockets = []

        for spath in socket_paths:
            exists = os.path.exists(spath)
            if not exists:
                details.append(f"  ✓ {spath}: not present")
                continue

            is_socket = os.path.exists(spath) and (
                os.stat(spath).st_mode & 0o170000 == 0o140000  # S_ISSOCK
            )
            readable = os.access(spath, os.R_OK)
            writable = os.access(spath, os.W_OK)

            if writable:
                writable_sockets.append(spath)
                details.append(f"  ✗ {spath}: EXISTS, WRITABLE (socket={is_socket})")
                # Try to query Docker API
                if "docker" in spath:
                    try:
                        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        sock.settimeout(3)
                        sock.connect(spath)
                        sock.sendall(
                            b"GET /v1.24/info HTTP/1.1\r\nHost: localhost\r\n\r\n")
                        resp = sock.recv(4096).decode("utf-8", errors="replace")
                        sock.close()
                        if "API" in resp or "Containers" in resp:
                            details.append(
                                f"    → Docker API responded! "
                                f"Preview: {resp[:120]}...")
                    except Exception as exc:
                        details.append(
                            f"    → Docker API query failed: {exc}")
            elif readable:
                readable_sockets.append(spath)
                details.append(f"  ⚠ {spath}: EXISTS, readable but not writable")
            else:
                details.append(f"  ⚠ {spath}: EXISTS but not accessible")

        if writable_sockets:
            record(TIER_MIDDLE, name, STATUS_VULNERABLE,
                   "\n".join(details) +
                   f"\n⚠ Writable runtime sockets: {writable_sockets}\n"
                   "Container escape via socket API is possible!")
        elif readable_sockets:
            record(TIER_MIDDLE, name, STATUS_INFO,
                   "\n".join(details) +
                   "\nSockets exist but are read-only — limited risk.")
        else:
            record(TIER_MIDDLE, name, STATUS_SECURE,
                   "\n".join(details) +
                   "\nNo container runtime sockets exposed.")
    except Exception as e:
        record(TIER_MIDDLE, name, STATUS_ERROR, str(e))


def test_mount_namespace_escape() -> None:
    """Check if /proc/1/root points to host filesystem (namespace escape)."""
    name = "Mount Namespace Escape (/proc/1/root)"
    try:
        details = []

        # Check /proc/1/root — in a properly namespaced container,
        # this should be inaccessible or point to the container root
        target = "/proc/1/root"
        try:
            real = os.readlink(target)
            details.append(f"/proc/1/root -> {real}")

            # Try to list it
            try:
                entries = os.listdir(target)
                details.append(f"Can list /proc/1/root: {len(entries)} entries")
                # If we can read host files through this...
                host_markers = ["/proc/1/root/etc/hostname",
                                "/proc/1/root/etc/machine-id"]
                for marker in host_markers:
                    try:
                        content = Path(marker).read_text().strip()
                        details.append(f"  Read {marker}: {content[:60]}")
                    except Exception:
                        pass
                record(TIER_MIDDLE, name, STATUS_INFO,
                       "\n".join(details) +
                       "\n/proc/1/root is accessible — typical in non-containerized envs.")
            except PermissionError:
                record(TIER_MIDDLE, name, STATUS_SECURE,
                       "\n".join(details) +
                       "\n/proc/1/root listing denied — good namespace isolation.")
        except PermissionError:
            record(TIER_MIDDLE, name, STATUS_SECURE,
                   "Cannot read /proc/1/root symlink — namespace isolation intact.")
        except FileNotFoundError:
            record(TIER_MIDDLE, name, STATUS_SECURE,
                   "/proc/1/root not found — unusual but not exploitable.")
    except Exception as e:
        record(TIER_MIDDLE, name, STATUS_ERROR, str(e))


# ═══════════════════════════════════════════════════════════════════════
#  TIER 3 — HARD: Hypervisor Escape Vectors & Device Probing
# ═══════════════════════════════════════════════════════════════════════

def test_kvm_hypervisor_interaction() -> None:
    """Probe /dev/kvm for nested virtualization and ioctl access."""
    name = "KVM / Hypervisor Device Access"
    try:
        kvm_path = "/dev/kvm"
        details = []

        if not os.path.exists(kvm_path):
            record(TIER_HARD, name, STATUS_SECURE,
                   "/dev/kvm does not exist — nested virtualization not exposed.")
            return

        details.append(f"{kvm_path} exists")

        try:
            fd = os.open(kvm_path, os.O_RDWR)
            details.append("Opened /dev/kvm with O_RDWR!")

            # KVM_GET_API_VERSION = 0xAE00
            KVM_GET_API_VERSION = 0xAE00
            try:
                api_version = fcntl.ioctl(fd, KVM_GET_API_VERSION)
                details.append(f"KVM API version: {api_version}")

                # KVM_CREATE_VM = 0xAE01
                KVM_CREATE_VM = 0xAE01
                try:
                    vm_fd = fcntl.ioctl(fd, KVM_CREATE_VM, 0)
                    details.append(f"⚠ Created a VM fd={vm_fd} — full KVM access!")
                    os.close(vm_fd)
                except OSError as e:
                    details.append(f"KVM_CREATE_VM blocked: {e}")
            except OSError as e:
                details.append(f"ioctl KVM_GET_API_VERSION failed: {e}")

            os.close(fd)

            record(TIER_HARD, name, STATUS_VULNERABLE,
                   "\n".join(details) +
                   "\n⚠ /dev/kvm is open and responsive — "
                   "hypervisor escape surface exists.")
        except PermissionError:
            details.append("Permission denied opening /dev/kvm (good).")
            record(TIER_HARD, name, STATUS_SECURE, "\n".join(details))
        except OSError as e:
            details.append(f"OS error opening /dev/kvm: {e}")
            record(TIER_HARD, name, STATUS_SECURE, "\n".join(details))
    except Exception as e:
        record(TIER_HARD, name, STATUS_ERROR, str(e))


def test_raw_block_device_access() -> None:
    """Scan /dev/ for raw disk devices and attempt to read the MBR."""
    name = "Raw Block Device Access (MBR Read)"
    try:
        # Common block device patterns
        patterns = [
            "/dev/sda", "/dev/sdb", "/dev/sdc",
            "/dev/vda", "/dev/vdb",
            "/dev/nvme0n1", "/dev/nvme1n1",
            "/dev/xvda", "/dev/xvdb",
        ]

        found_devices = []
        readable_devices = []
        details = []

        for dev in patterns:
            if os.path.exists(dev):
                found_devices.append(dev)
                try:
                    with open(dev, "rb") as f:
                        mbr = f.read(512)
                    readable_devices.append(dev)

                    # Check for MBR boot signature (0x55AA at offset 510)
                    has_mbr_sig = (len(mbr) >= 512 and
                                   mbr[510] == 0x55 and mbr[511] == 0xAA)
                    # Check for GPT marker
                    has_gpt_marker = b"EFI PART" in mbr

                    details.append(
                        f"  ✗ {dev}: READABLE ({len(mbr)} bytes) "
                        f"MBR_sig={has_mbr_sig} GPT={has_gpt_marker}")
                except PermissionError:
                    details.append(f"  ✓ {dev}: exists but not readable (good)")
                except OSError as e:
                    details.append(f"  ✓ {dev}: exists, OS error: {e}")
            # else: skip silently

        # Also scan for any unexpected block devices
        try:
            all_block = glob.glob("/dev/sd[a-z]") + glob.glob("/dev/nvme*n*")
            extras = [d for d in all_block if d not in patterns and os.path.exists(d)]
            for dev in extras:
                found_devices.append(dev)
                details.append(f"  ⚠ {dev}: unexpected block device found")
        except Exception:
            pass

        if not found_devices:
            record(TIER_HARD, name, STATUS_SECURE,
                   "No raw block devices found in /dev/ — "
                   "storage is properly abstracted.")
        elif readable_devices:
            record(TIER_HARD, name, STATUS_VULNERABLE,
                   "\n".join(details) +
                   f"\n⚠ {len(readable_devices)} block device(s) readable: "
                   f"{readable_devices}\n"
                   "Guest can read raw host/VM disk sectors!")
        else:
            record(TIER_HARD, name, STATUS_SECURE,
                   "\n".join(details) +
                   f"\n{len(found_devices)} device(s) present but none readable.")
    except Exception as e:
        record(TIER_HARD, name, STATUS_ERROR, str(e))


def test_timing_side_channel() -> None:
    """Evaluate timing side-channel susceptibility via clock drift analysis."""
    name = "CPU Timing Side-Channel (Clock Drift)"
    try:
        details = []

        # 1. Check /proc/timer_list access
        timer_list_readable = False
        try:
            with open("/proc/timer_list", "r") as f:
                timer_data = f.read(2048)
            timer_list_readable = True
            # Look for host clock references
            host_clocks = [l.strip() for l in timer_data.splitlines()
                           if "clock" in l.lower() or "jiffies" in l.lower()]
            details.append(f"/proc/timer_list: readable ({len(host_clocks)} "
                           f"clock entries)")
            if host_clocks[:3]:
                for cl in host_clocks[:3]:
                    details.append(f"  → {cl[:100]}")
        except PermissionError:
            details.append("/proc/timer_list: access denied (good)")
        except FileNotFoundError:
            details.append("/proc/timer_list: not present")

        # 2. High-frequency timing measurement
        # Perform a quick burst of time.perf_counter_ns() calls to measure
        # the resolution and jitter of the guest clock
        samples = 1000
        deltas = []
        for _ in range(samples):
            t0 = time.perf_counter_ns()
            t1 = time.perf_counter_ns()
            deltas.append(t1 - t0)

        avg_ns = sum(deltas) / len(deltas)
        min_ns = min(deltas)
        max_ns = max(deltas)
        # Standard deviation
        variance = sum((d - avg_ns) ** 2 for d in deltas) / len(deltas)
        stddev_ns = variance ** 0.5

        details.append(f"Clock resolution test ({samples} samples):")
        details.append(f"  min={min_ns}ns  avg={avg_ns:.1f}ns  "
                       f"max={max_ns}ns  stddev={stddev_ns:.1f}ns")

        # High resolution (<50ns) with low jitter could enable side-channel
        high_resolution = min_ns < 50
        low_jitter = stddev_ns < 100

        if timer_list_readable and high_resolution:
            record(TIER_HARD, name, STATUS_VULNERABLE,
                   "\n".join(details) +
                   "\n⚠ High-resolution timer + /proc/timer_list access "
                   "enables timing side-channel attacks.")
        elif timer_list_readable or high_resolution:
            record(TIER_HARD, name, STATUS_INFO,
                   "\n".join(details) +
                   "\nPartial timing visibility — limited side-channel surface.")
        else:
            record(TIER_HARD, name, STATUS_SECURE,
                   "\n".join(details) +
                   "\nTimer resolution is coarse and /proc/timer_list is restricted.")
    except Exception as e:
        record(TIER_HARD, name, STATUS_ERROR, str(e))


def test_device_file_enumeration() -> None:
    """Enumerate sensitive device files that should not be exposed to guests."""
    name = "Sensitive Device File Exposure"
    try:
        sensitive_devices = {
            "/dev/mem":      "Physical memory access",
            "/dev/kmem":     "Kernel memory access",
            "/dev/port":     "I/O port access",
            "/dev/sda":      "Raw disk (primary)",
            "/dev/sda1":     "Disk partition 1",
            "/dev/sda2":     "Disk partition 2",
            "/dev/sda3":     "Disk partition 3",
            "/dev/sr0":      "CD/DVD drive",
            "/dev/ttyS0":    "Serial console",
            "/dev/vhost-net": "vhost-net (virtio host networking)",
            "/dev/kvm":      "KVM hypervisor interface",
            "/dev/fuse":     "FUSE filesystem",
            "/dev/loop0":    "Loop device 0",
            "/dev/net/tun":  "TUN/TAP virtual network",
        }

        exposed = []
        restricted = []
        details = []

        for dev, desc in sorted(sensitive_devices.items()):
            if os.path.exists(dev):
                readable = os.access(dev, os.R_OK)
                writable = os.access(dev, os.W_OK)
                if readable or writable:
                    perm = f"r={'Y' if readable else 'N'} w={'Y' if writable else 'N'}"
                    exposed.append((dev, desc, perm))
                    details.append(f"  ✗ {dev:<20} ({desc}): {perm}")
                else:
                    restricted.append(dev)
                    details.append(f"  ✓ {dev:<20} ({desc}): exists, no access")
            # skip missing devices silently

        if exposed:
            # Classify severity
            critical = [d for d, _, _ in exposed
                        if d in ("/dev/mem", "/dev/kmem", "/dev/kvm")]
            if critical:
                record(TIER_HARD, name, STATUS_VULNERABLE,
                       "\n".join(details) +
                       f"\n⚠ CRITICAL devices accessible: {critical}")
            else:
                record(TIER_HARD, name, STATUS_INFO,
                       "\n".join(details) +
                       f"\n{len(exposed)} device(s) accessible (non-critical).")
        else:
            record(TIER_HARD, name, STATUS_SECURE,
                   "\n".join(details) +
                   "\nNo sensitive devices accessible.")
    except Exception as e:
        record(TIER_HARD, name, STATUS_ERROR, str(e))


def test_cgroup_escape() -> None:
    """Check for cgroup misconfiguration that could enable resource escape."""
    name = "Cgroup Escape / Resource Limit Audit"
    try:
        details = []

        # Check which cgroup version
        cgroup_v2 = os.path.exists("/sys/fs/cgroup/cgroup.controllers")
        details.append(f"Cgroup version: {'v2' if cgroup_v2 else 'v1'}")

        if cgroup_v2:
            # Read our cgroup membership
            try:
                cgroup_self = Path("/proc/self/cgroup").read_text().strip()
                details.append(f"Self cgroup: {cgroup_self}")
            except Exception:
                pass

            # Check if we can write to cgroup hierarchy
            cgroup_root = Path("/sys/fs/cgroup")
            procs_file = cgroup_root / "cgroup.procs"
            try:
                writable = os.access(str(procs_file), os.W_OK)
                if writable:
                    details.append(
                        "⚠ /sys/fs/cgroup/cgroup.procs is WRITABLE — "
                        "can migrate processes!")
                    record(TIER_HARD, name, STATUS_VULNERABLE,
                           "\n".join(details))
                    return
                else:
                    details.append(
                        "Root cgroup.procs is not writable (good).")
            except Exception:
                pass

            # Check for release_agent (classic cgroup v1 escape path)
            release_agents = glob.glob(
                "/sys/fs/cgroup/*/release_agent") + glob.glob(
                "/sys/fs/cgroup/release_agent")
            for ra in release_agents:
                try:
                    writable = os.access(ra, os.W_OK)
                    if writable:
                        details.append(f"⚠ {ra} is WRITABLE — escape vector!")
                        record(TIER_HARD, name, STATUS_VULNERABLE,
                               "\n".join(details))
                        return
                except Exception:
                    pass

        record(TIER_HARD, name, STATUS_SECURE,
               "\n".join(details) +
               "\nNo cgroup escape vectors detected.")
    except Exception as e:
        record(TIER_HARD, name, STATUS_ERROR, str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Test Runner & Report Generator
# ═══════════════════════════════════════════════════════════════════════

ALL_TESTS = [
    # TIER 1 — SIMPLE
    test_privilege_check,
    test_kernel_version_probe,
    test_hardware_leakage,
    test_environment_variables,
    test_proc_self_status,
    # TIER 2 — MIDDLE
    test_gateway_port_scan,
    test_cloud_metadata_access,
    test_docker_socket_probe,
    test_mount_namespace_escape,
    # TIER 3 — HARD
    test_kvm_hypervisor_interaction,
    test_raw_block_device_access,
    test_timing_side_channel,
    test_device_file_enumeration,
    test_cgroup_escape,
]


def print_banner() -> None:
    banner = r"""
╔══════════════════════════════════════════════════════════════════════╗
║           SANDBOX ISOLATION BOUNDARY AUDIT                         ║
║           MicroVM / Container Escape Test Suite                     ║
╠══════════════════════════════════════════════════════════════════════╣
║  Mode: Non-destructive · Passive probing · Stdlib only             ║
╚══════════════════════════════════════════════════════════════════════╝
    """
    print(banner)
    print(f"  Timestamp : {datetime.now(timezone.utc).isoformat()}")
    print(f"  Hostname  : {platform.node()}")
    print(f"  Platform  : {platform.platform()}")
    print(f"  Python    : {sys.version.split()[0]}")
    print(f"  PID       : {os.getpid()}  UID: {os.getuid()}  "
          f"EUID: {os.geteuid()}")
    print()


def print_summary() -> None:
    """Print a structured summary table of all results."""
    print()
    print("=" * 74)
    print("  AUDIT SUMMARY")
    print("=" * 74)
    print()

    # Count by status
    counts = {}
    for r in _results:
        counts[r.status] = counts.get(r.status, 0) + 1

    vuln_count = counts.get(STATUS_VULNERABLE, 0)
    secure_count = counts.get(STATUS_SECURE, 0)
    info_count = counts.get(STATUS_INFO, 0)
    error_count = counts.get(STATUS_ERROR, 0)

    # Table header
    print(f"  {'Tier':<8} {'Test Name':<45} {'Status':<12}")
    print(f"  {'─' * 8} {'─' * 45} {'─' * 12}")

    current_tier = None
    for r in _results:
        if r.tier != current_tier:
            if current_tier is not None:
                print()
            current_tier = r.tier

        status_colored = {
            STATUS_SECURE:     f"\033[92m{r.status}\033[0m",
            STATUS_VULNERABLE: f"\033[91m{r.status}\033[0m",
            STATUS_INFO:       f"\033[93m{r.status}\033[0m",
            STATUS_ERROR:      f"\033[90m{r.status}\033[0m",
        }.get(r.status, r.status)

        print(f"  {r.tier:<8} {r.name:<45} {status_colored}")

    print()
    print(f"  ─── Totals ───")
    print(f"  🟢 SECURE:     {secure_count}")
    print(f"  🔴 VULNERABLE: {vuln_count}")
    print(f"  🟡 INFO:       {info_count}")
    print(f"  ⚪ ERROR:      {error_count}")
    print()

    if vuln_count == 0:
        print("  ✅ OVERALL: No critical isolation breaches detected.")
    else:
        print(f"  ⛔ OVERALL: {vuln_count} VULNERABILITY(ies) detected — "
              f"sandbox isolation is COMPROMISED.")
        print()
        print("  Vulnerable findings:")
        for r in _results:
            if r.status == STATUS_VULNERABLE:
                print(f"    • [{r.tier}] {r.name}")

    print()
    print("=" * 74)


def main() -> int:
    print_banner()

    tier_labels = {
        TIER_SIMPLE: "TIER 1 — SIMPLE: Basic Container & Environment Probing",
        TIER_MIDDLE: "TIER 2 — MIDDLE: Network Probing & Container Breakouts",
        TIER_HARD:   "TIER 3 — HARD: Hypervisor Escape & Device Probing",
    }

    current_tier = None
    for test_fn in ALL_TESTS:
        # Determine tier from the function (via first call's recording)
        # We print tier headers based on function ordering
        # Infer tier from function name mapping
        tier = (TIER_SIMPLE if test_fn in ALL_TESTS[:5] else
                TIER_MIDDLE if test_fn in ALL_TESTS[5:9] else
                TIER_HARD)
        if tier != current_tier:
            current_tier = tier
            print()
            print(f"{'─' * 74}")
            print(f"  {tier_labels.get(tier, tier)}")
            print(f"{'─' * 74}")
            print()

        try:
            test_fn()
        except Exception as e:
            record(tier, test_fn.__name__, STATUS_ERROR,
                   f"Unhandled exception: {e}")

    print_summary()

    vuln_count = sum(1 for r in _results if r.status == STATUS_VULNERABLE)
    return 1 if vuln_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
