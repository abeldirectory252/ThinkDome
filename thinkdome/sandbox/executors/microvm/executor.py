"""MicroVM Execution Backend — Real Cloud Hypervisor / KVM Integration.

Provides hardware-isolated MicroVM sandboxes using:
  - Cloud Hypervisor (CHV) VMM process spawning via ``/dev/kvm``
  - BusyBox initramfs + OverlayFS for read-only base / writable state separation
  - AF_VSOCK IPC for host↔guest command execution
  - TAP networking with iptables DNAT port forwarding
  - Full VM-level snapshot/restore for agent backtracking

Architecture mirrors the Arrakis reference implementation (Ref/arrakis-main/):
  - server.go   → MicroVMExecutor (VM lifecycle management)
  - fountain.go → allocators.TapDeviceManager
  - ipallocator → allocators.IPAllocator
  - cidallocator → allocators.CIDAllocator
  - chv-api.yaml → chv_client.CHVClient
  - vsockclient → vsock_client.VsockClient / GuestHTTPClient
"""

from __future__ import annotations

import os
import sys
import time
import json
import uuid
import shutil
import asyncio
import logging
import subprocess
from enum import Enum
from pathlib import Path
from typing import Optional, AsyncGenerator, Dict, Any, List
from dataclasses import dataclass, field

from thinkdome.core.config import Settings
from thinkdome.sandbox.executors.base import BaseExecutor, ExecRequest, ExecResult
from thinkdome.sandbox.executors.microvm.allocators import (
    IPAllocator,
    CIDAllocator,
    TapDeviceManager,
    TapDevice,
)
from thinkdome.sandbox.executors.microvm.chv_client import (
    CHVClient,
    VmConfig,
    PayloadConfig,
    DiskConfig,
    CpusConfig,
    MemoryConfig,
    NetConfig,
    VsockConfig,
    ConsoleConfig,
)
from thinkdome.sandbox.executors.microvm.vsock_client import VsockClient, GuestHTTPClient
from thinkdome.sandbox.executors.microvm.networking import (
    setup_bridge_and_firewall,
    cleanup_bridge,
    cleanup_all_tap_devices,
    cleanup_iptables_for_ip,
    setup_port_forward,
    get_ip_prefix,
    PortForward,
)

from thinkdome.sandbox.executors.microvm.exceptions import (
    MicroVMError,
    InsufficientPrivilegesError,
    TAPDeviceError,
    NetworkConfigurationError,
    MicroVMProvisionError,
)

logger = logging.getLogger(__name__)



# ─── Constants ───────────────────────────────────────────────────────────────

SERIAL_PORT_MODE = "Tty"     # Case-sensitive, per CHV API
CONSOLE_PORT_MODE = "Off"
NET_DEVICE_QUEUES = 2
NET_DEVICE_QUEUE_SIZE = 256
NET_DEVICE_ID = "_net0"
REAP_VM_TIMEOUT = 20.0       # seconds
CMD_SERVER_READY_TIMEOUT = 60.0
STATEFUL_DISK_FILENAME = "stateful.img"
CID_FILENAME = "cid"


class VMStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


# ─── MicroVM Instance ───────────────────────────────────────────────────────

class MicroVMInstance:
    """Represents a running hardware-isolated MicroVM instance.

    Unlike the previous façade, this class now holds real runtime state:
    the CHV process handle, API client, vsock client, TAP device, allocated
    IP and CID, and the stateful disk path.
    """

    def __init__(
        self,
        vm_id: str,
        name: str,
        state_dir: Path,
        vcpus: int = 2,
        memory_mb: int = 512,
    ) -> None:
        self.vm_id = vm_id
        self.name = name
        self.state_dir = state_dir
        self.vcpus = vcpus
        self.memory_mb = memory_mb
        self.status = VMStatus.CREATED
        self.created_at = time.time()

        # Runtime state (populated during spawn)
        self.process: Optional[subprocess.Popen] = None
        self.api_socket_path: str = ""
        self.chv_client: Optional[CHVClient] = None
        self.vsock_client: Optional[VsockClient] = None
        self.guest_http_client: Optional[GuestHTTPClient] = None
        self.tap_device: Optional[TapDevice] = None
        self.ip_address: Optional[str] = None  # e.g. "10.20.1.2/24"
        self.ip_bare: Optional[str] = None     # e.g. "10.20.1.2"
        self.cid: int = 0
        self.vsock_path: str = ""
        self.stateful_disk_path: str = ""
        self.port_forwards: List[PortForward] = []

        # OverlayFS directories
        self.upper_dir = state_dir / "upper"
        self.work_dir = state_dir / "work"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vm_id": self.vm_id,
            "name": self.name,
            "vcpus": self.vcpus,
            "memory_mb": self.memory_mb,
            "ip": self.ip_address,
            "ip_bare": self.ip_bare,
            "tap_device": self.tap_device.name if self.tap_device else None,
            "status": self.status.value,
            "vsock_path": self.vsock_path,
            "cid": self.cid,
            "created_at": self.created_at,
            "state_dir": str(self.state_dir),
            "port_forwards": [
                {"host": pf.host_port, "guest": pf.guest_port, "desc": pf.description}
                for pf in self.port_forwards
            ],
        }


# ─── Stateful Disk Helpers ───────────────────────────────────────────────────

def _create_stateful_disk(path: str, size_mb: int) -> None:
    """Create a sparse ext4 disk image for the writable OverlayFS layer.

    Mirrors Arrakis ``createStatefulDisk`` in server.go.
    """
    logger.info("Creating stateful disk at %s (%dMB)", path, size_mb)
    subprocess.run(
        ["truncate", "-s", f"{size_mb}M", path],
        check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["mkfs.ext4", "-F", path],
        check=True, capture_output=True, text=True,
    )


def _copy_file(src: str, dst: str) -> None:
    """Copy a file (binary-safe). Mirrors Arrakis ``copyFile``."""
    shutil.copy2(src, dst)


def _reap_process(process: subprocess.Popen, timeout: float = REAP_VM_TIMEOUT) -> None:
    """Wait for a process to exit, force-killing after timeout.

    Mirrors Arrakis ``reapProcess`` in server.go.
    """
    try:
        process.wait(timeout=timeout)
        logger.info("VM process exited (pid=%d)", process.pid)
    except subprocess.TimeoutExpired:
        logger.warning("VM process did not exit in %ds, force killing", timeout)
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _get_kernel_cmdline(gateway_ip: str, guest_ip: str) -> str:
    """Build the kernel command line for guest boot.

    Mirrors Arrakis ``getKernelCmdLine`` in server.go.
    """
    return f'console=ttyS0 gateway_ip="{gateway_ip}" guest_ip="{guest_ip}"'


def _calculate_vcpu_count() -> int:
    """Calculate vCPU count based on host CPUs (max 8, min 1, half of host)."""
    host_cpus = os.cpu_count() or 2
    suggested = host_cpus // 2
    return max(1, min(8, suggested))


# ─── MicroVM Executor ───────────────────────────────────────────────────────

class MicroVMExecutor(BaseExecutor):
    """Execution backend using real Cloud Hypervisor MicroVM isolation.

    This is a complete rewrite of the previous façade. It now:
    1. Spawns actual ``cloud-hypervisor`` processes with ``/dev/kvm``
    2. Creates real TAP devices and Linux bridges
    3. Communicates with guest VMs via AF_VSOCK IPC and HTTP
    4. Supports full VM-level snapshot/restore for agent backtracking
    5. Uses OverlayFS for read-only base + writable state separation
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings()
        self.instances: Dict[str, MicroVMInstance] = {}

        # Infrastructure state
        self._initialized = False
        self.kvm_available = False

        # Allocators (created during initialize)
        self._ip_allocator: Optional[IPAllocator] = None
        self._cid_allocator: Optional[CIDAllocator] = None
        self._tap_manager: Optional[TapDeviceManager] = None

        # Config values
        self._chv_binary = getattr(self.settings, "MICROVM_BINARY", "cloud-hypervisor")
        self._kernel_path = getattr(self.settings, "MICROVM_KERNEL_PATH", "/var/lib/thinkdome/vmlinux")
        self._rootfs_path = getattr(self.settings, "MICROVM_ROOTFS_PATH", "/var/lib/thinkdome/rootfs.ext4")
        self._initramfs_path = getattr(self.settings, "MICROVM_INITRAMFS_PATH", "./initramfs/initramfs.cpio.gz")
        self._state_dir = Path(getattr(self.settings, "MICROVM_STATE_DIR", "./vm-state"))
        self._bridge_name = getattr(self.settings, "MICROVM_BRIDGE_NAME", "br0")
        self._bridge_ip = getattr(self.settings, "MICROVM_BRIDGE_IP", "10.20.1.1/24")
        self._bridge_subnet = getattr(self.settings, "MICROVM_BRIDGE_SUBNET", "10.20.1.0/24")
        self._stateful_disk_mb = getattr(self.settings, "MICROVM_STATEFUL_DISK_MB", 2048)
        self._guest_mem_pct = getattr(self.settings, "MICROVM_GUEST_MEM_PERCENTAGE", 50)
        self._vsock_port = getattr(self.settings, "MICROVM_VSOCK_PORT", 4032)
        self._cmd_server_port = getattr(self.settings, "MICROVM_CMD_SERVER_PORT", 4031)
        self._snapshot_dir = self._state_dir / "snapshots"

    async def initialize(self) -> None:
        """Initialize MicroVM environment: validate prerequisites, setup networking.

        This mirrors the ``NewServer`` constructor in Arrakis server.go.
        """
        # 1. Validate /dev/kvm
        self.kvm_available = (
            os.path.exists("/dev/kvm")
            and os.access("/dev/kvm", os.R_OK | os.W_OK)
        )
        if not self.kvm_available:
            logger.warning(
                "MicroVM: /dev/kvm not available or not writable. "
                "VM creation will fail without KVM hardware acceleration."
            )

        # 2. Validate cloud-hypervisor binary
        chv_path = shutil.which(self._chv_binary)
        if chv_path:
            self._chv_binary = chv_path
            logger.info("MicroVM: Found CHV binary at %s", chv_path)
        else:
            logger.warning(
                "MicroVM: cloud-hypervisor binary '%s' not found in PATH. "
                "VM creation will fail.", self._chv_binary
            )

        # 3. Create state directories
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)

        # 4. Cleanup any stale resources from previous runs
        try:
            cleanup_all_tap_devices()
            cleanup_bridge(self._bridge_name)
            ip_prefix = get_ip_prefix(self._bridge_subnet)
            cleanup_iptables_for_ip(ip_prefix)
        except Exception as exc:
            logger.warning("MicroVM: Cleanup of stale resources failed: %s", exc)

        # 5. Setup bridge and firewall
        try:
            setup_bridge_and_firewall(
                bridge_name=self._bridge_name,
                bridge_ip=self._bridge_ip,
                bridge_subnet=self._bridge_subnet,
            )
        except InsufficientPrivilegesError as exc:
            logger.info("MicroVM host bridge setup skipped: %s", exc)
        except Exception as exc:
            logger.warning("MicroVM host bridge setup failed: %s", exc)


        # 6. Create allocators
        self._ip_allocator = IPAllocator(self._bridge_subnet)
        self._cid_allocator = CIDAllocator(low_cid=3, high_cid=1000)
        self._tap_manager = TapDeviceManager(bridge_name=self._bridge_name)

        # 7. Validate kernel/rootfs/initramfs existence
        for label, path in [
            ("kernel", self._kernel_path),
            ("rootfs", self._rootfs_path),
            ("initramfs", self._initramfs_path),
        ]:
            if not os.path.exists(path):
                logger.warning("MicroVM: %s not found at %s", label, path)

        self._initialized = True
        logger.info(
            "MicroVMExecutor initialized. KVM=%s, CHV=%s, Bridge=%s (%s)",
            self.kvm_available, self._chv_binary,
            self._bridge_name, self._bridge_ip,
        )

    def spawn_vm(
        self,
        name: str = "agent-microvm",
        memory_mb: int = 512,
        vcpus: int = 2,
    ) -> MicroVMInstance:
        """Spawn a real hardware-isolated MicroVM instance.

        Mirrors Arrakis ``createVM`` + ``boot`` + port forwarding in server.go.

        Lifecycle:
          1. Allocate TAP device, IP, CID
          2. Create stateful disk
          3. Spawn ``cloud-hypervisor --api-socket <path>`` process
          4. Wait for CHV API readiness
          5. Call CHV API: create_vm → boot_vm
          6. Wait for in-guest command server
          7. Setup DNAT port forwards
        """
        vm_id = f"mvm_{uuid.uuid4().hex[:8]}"
        vm_state_dir = self._state_dir / vm_id
        vm_state_dir.mkdir(parents=True, exist_ok=True)

        instance = MicroVMInstance(
            vm_id=vm_id,
            name=name,
            state_dir=vm_state_dir,
            vcpus=vcpus,
            memory_mb=memory_mb,
        )

        try:
            # 1. Allocate network resources
            instance.tap_device = self._tap_manager.create_tap_device()
            allocated_ip = self._ip_allocator.allocate_ip()
            instance.ip_address = str(allocated_ip)
            instance.ip_bare = str(allocated_ip.ip)
            instance.cid = self._cid_allocator.allocate_cid()

            # 2. Create stateful disk for writable OverlayFS layer
            instance.stateful_disk_path = str(vm_state_dir / STATEFUL_DISK_FILENAME)
            _create_stateful_disk(instance.stateful_disk_path, self._stateful_disk_mb)

            # 3. Setup CHV API socket and spawn process
            instance.api_socket_path = str(vm_state_dir / f"{vm_id}.sock")
            log_file_path = vm_state_dir / "log"
            log_file = open(log_file_path, "w")

            cmd = [self._chv_binary, "--api-socket", instance.api_socket_path]
            instance.process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=log_file,
                # Separate process group so Ctrl-C doesn't kill VMs
                preexec_fn=os.setpgrp,
            )
            logger.info(
                "Spawned CHV process (pid=%d) for VM %s",
                instance.process.pid, vm_id,
            )

            # 4. Wait for CHV API socket to be ready
            instance.chv_client = CHVClient(instance.api_socket_path)
            instance.chv_client.wait_for_api(timeout=10.0)

            # 5. Build VmConfig and create+boot the VM
            # Extract gateway IP from bridge IP (e.g. "10.20.1.1/24" → "10.20.1.1")
            gateway_ip = self._bridge_ip.split("/")[0]
            kernel_cmdline = _get_kernel_cmdline(gateway_ip, instance.ip_address)

            vm_config = VmConfig(
                payload=PayloadConfig(
                    kernel=self._kernel_path,
                    cmdline=kernel_cmdline,
                    initramfs=self._initramfs_path,
                ),
                disks=[
                    DiskConfig(
                        path=self._rootfs_path,
                        readonly=True,
                        num_queues=vcpus,
                    ),
                    DiskConfig(
                        path=instance.stateful_disk_path,
                        num_queues=vcpus,
                    ),
                ],
                cpus=CpusConfig(boot_vcpus=vcpus, max_vcpus=vcpus),
                memory=MemoryConfig(size=memory_mb * 1024 * 1024),
                net=[
                    NetConfig(
                        tap=instance.tap_device.name,
                        num_queues=NET_DEVICE_QUEUES,
                        queue_size=NET_DEVICE_QUEUE_SIZE,
                        id=NET_DEVICE_ID,
                    ),
                ],
                vsock=VsockConfig(
                    cid=instance.cid,
                    socket=str(vm_state_dir / "vsock.sock"),
                ),
                serial=ConsoleConfig(mode=SERIAL_PORT_MODE),
                console=ConsoleConfig(mode=CONSOLE_PORT_MODE),
            )

            instance.vsock_path = str(vm_state_dir / "vsock.sock")
            instance.chv_client.create_vm(vm_config)
            logger.info("VM %s created, booting...", vm_id)

            instance.chv_client.boot_vm()
            instance.status = VMStatus.RUNNING
            logger.info("VM %s booted (pid=%d)", vm_id, instance.process.pid)

            # 6. Setup vsock and HTTP clients
            instance.vsock_client = VsockClient(
                instance.vsock_path, port=self._vsock_port
            )
            instance.guest_http_client = GuestHTTPClient(
                instance.ip_bare, port=self._cmd_server_port
            )

            # 7. Wait for in-guest command server
            # (best-effort; may timeout if guest boot is slow)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Can't await in sync context; just log a note
                    logger.info(
                        "VM %s: Guest cmd server readiness check deferred to first execute()",
                        vm_id,
                    )
                else:
                    loop.run_until_complete(
                        instance.guest_http_client.wait_for_ready(
                            timeout=CMD_SERVER_READY_TIMEOUT
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "VM %s: Guest command server not ready yet: %s", vm_id, exc
                )

            # 8. Setup OverlayFS directories
            instance.upper_dir.mkdir(parents=True, exist_ok=True)
            instance.work_dir.mkdir(parents=True, exist_ok=True)

        except Exception:
            # Cleanup on failure
            self._cleanup_vm_resources(instance)
            raise

        self.instances[vm_id] = instance
        return instance

    def _cleanup_vm_resources(self, instance: MicroVMInstance) -> None:
        """Clean up all resources allocated for a VM instance on failure."""
        # Kill CHV process
        if instance.process and instance.process.poll() is None:
            try:
                instance.process.kill()
                instance.process.wait(timeout=5)
            except Exception:
                pass

        # Free allocator resources
        if instance.tap_device and self._tap_manager:
            try:
                self._tap_manager.destroy_tap_device(instance.tap_device)
            except Exception as exc:
                logger.warning("Cleanup: TAP destroy failed: %s", exc)

        if instance.ip_bare and self._ip_allocator:
            import ipaddress
            try:
                self._ip_allocator.free_ip(ipaddress.IPv4Address(instance.ip_bare))
            except Exception:
                pass

        if instance.cid and self._cid_allocator:
            try:
                self._cid_allocator.free_cid(instance.cid)
            except Exception:
                pass

        # Cleanup iptables
        if instance.ip_bare:
            try:
                cleanup_iptables_for_ip(instance.ip_bare)
            except Exception:
                pass

        # Remove state directory
        if instance.state_dir.exists():
            try:
                shutil.rmtree(instance.state_dir)
            except Exception:
                pass

    async def destroy_vm(self, vm_id: str) -> None:
        """Destroy a VM: shutdown, delete, reap process, free resources.

        Mirrors Arrakis ``destroyVM`` in server.go.
        """
        instance = self.instances.get(vm_id)
        if not instance:
            raise ValueError(f"VM {vm_id} not found")

        logger.info("Destroying VM %s", vm_id)

        # 1. Graceful shutdown via CHV API
        if instance.chv_client:
            try:
                instance.chv_client.shutdown_vm()
            except Exception as exc:
                logger.warning("VM %s: Shutdown failed: %s", vm_id, exc)

            try:
                instance.chv_client.delete_vm()
            except Exception as exc:
                logger.warning("VM %s: Delete failed: %s", vm_id, exc)

            try:
                instance.chv_client.shutdown_vmm()
            except Exception as exc:
                logger.warning("VM %s: VMM shutdown failed: %s", vm_id, exc)

        # 2. Reap CHV process
        if instance.process:
            _reap_process(instance.process)

        # 3. Cleanup iptables, TAP, allocators
        self._cleanup_vm_resources(instance)

        instance.status = VMStatus.STOPPED
        self.instances.pop(vm_id, None)
        logger.info("VM %s destroyed", vm_id)

    async def execute(self, request: ExecRequest) -> ExecResult:
        """Execute code inside a MicroVM guest via the vsock/HTTP command server.

        If no VM exists, spawns one. Uploads files, runs the script inside the
        guest, and downloads output files.
        """
        start_time = time.time()

        # Find or create a VM
        if not self.instances:
            try:
                self.spawn_vm(
                    memory_mb=getattr(self.settings, "MICROVM_DEFAULT_MEM_MB", 512),
                    vcpus=getattr(self.settings, "MICROVM_DEFAULT_VCPUS", 2),
                )
            except InsufficientPrivilegesError as exc:
                use_fallback = getattr(self.settings, "EXECUTOR_BACKEND_USE_FALLBACK", False)
                if use_fallback:
                    logger.info("Insufficient system privileges for MicroVM networking; gracefully falling back to subprocess executor.")
                    return await self._fallback_subprocess_execute(request, start_time)
                else:
                    raise MicroVMProvisionError(
                        f"MicroVM provisioning failed due to insufficient privileges: {exc}. "
                        "Set EXECUTOR_BACKEND_USE_FALLBACK=True or run with root/CAP_NET_ADMIN privileges."
                    ) from exc
            except Exception as exc:
                use_fallback = getattr(self.settings, "EXECUTOR_BACKEND_USE_FALLBACK", False)
                if use_fallback:
                    logger.warning("Failed to spawn MicroVM (%s); falling back to subprocess executor.", exc)
                    return await self._fallback_subprocess_execute(request, start_time)
                else:
                    raise MicroVMProvisionError(
                        f"Failed to spawn MicroVM instance: {exc}. "
                        "Set EXECUTOR_BACKEND_USE_FALLBACK=True to allow automatic fallback."
                    ) from exc


        instance = next(iter(self.instances.values()))

        # Ensure guest command server is ready
        if instance.guest_http_client:
            try:
                await instance.guest_http_client.wait_for_ready(timeout=30.0)
            except Exception as exc:
                logger.error("Guest command server not ready: %s", exc)
                return ExecResult(
                    stdout="",
                    stderr=f"Guest command server not ready: {exc}",
                    exit_code=1,
                    timed_out=False,
                    duration_ms=(time.time() - start_time) * 1000.0,
                    output_files={},
                )

        try:
            # 1. Upload input files to guest workspace
            if request.files:
                workspace_files = {}
                for rel_path, content in request.files.items():
                    if isinstance(content, str):
                        content = content.encode("utf-8")
                    workspace_files[f"/workspace/{rel_path}"] = content
                await instance.guest_http_client.upload_files(workspace_files)

            # 2. Write the script to the guest
            script_filename = (
                "main.py" if request.language.lower() == "python"
                else f"main.{request.language.lower()}"
            )
            script_content = request.code.encode("utf-8")
            await instance.guest_http_client.upload_files({
                f"/workspace/{script_filename}": script_content,
            })

            # 3. Execute inside the guest
            timeout_sec = (request.timeout_ms or 10000) / 1000.0
            if request.language.lower() == "python":
                cmd = f"cd /workspace && timeout {timeout_sec} python3 {script_filename} 2>&1"
            else:
                cmd = f"cd /workspace && timeout {timeout_sec} ./{script_filename} 2>&1"

            output, error = await instance.guest_http_client.run_command(cmd)

            # 4. Check for timeout in output
            timed_out = "Timed out" in error if error else False
            exit_code = 124 if timed_out else (1 if error else 0)

            # 5. Download output files from guest workspace
            output_files = {}
            # List files in /workspace and download any new ones
            try:
                ls_output, _ = await instance.guest_http_client.run_command(
                    f"find /workspace -type f ! -name '{script_filename}' -printf '%P\\n'"
                )
                if ls_output.strip():
                    file_paths = [
                        f"/workspace/{p}" for p in ls_output.strip().split("\n")
                        if p.strip()
                    ]
                    downloaded = await instance.guest_http_client.download_files(file_paths)
                    for path, content in downloaded.items():
                        rel = path.replace("/workspace/", "", 1)
                        output_files[rel] = content.encode("utf-8") if isinstance(content, str) else content
            except Exception as exc:
                logger.warning("Could not download output files: %s", exc)

            duration_ms = (time.time() - start_time) * 1000.0

            return ExecResult(
                stdout=output,
                stderr=error,
                exit_code=exit_code,
                timed_out=timed_out,
                duration_ms=duration_ms,
                output_files=output_files,
            )

        except Exception as e:
            logger.error("Error during MicroVM execution: %s", e)
            return ExecResult(
                stdout="",
                stderr=f"MicroVM execution error: {str(e)}",
                exit_code=1,
                timed_out=False,
                duration_ms=(time.time() - start_time) * 1000.0,
                output_files={},
            )

    async def _fallback_subprocess_execute(
        self, request: ExecRequest, start_time: float
    ) -> ExecResult:
        """Fallback: execute code as a local subprocess when VM creation fails.

        This preserves backward compatibility with the previous façade behavior.
        """
        import tempfile

        with tempfile.TemporaryDirectory(prefix="mvm_fallback_") as temp_dir:
            temp_path = Path(temp_dir)

            if request.files:
                for rel_path, content in request.files.items():
                    target = temp_path / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if isinstance(content, str):
                        content = content.encode("utf-8")
                    target.write_bytes(content)

            script_filename = (
                "main.py" if request.language.lower() == "python"
                else f"main.{request.language.lower()}"
            )
            script_path = temp_path / script_filename
            script_path.write_text(request.code, encoding="utf-8")

            from thinkdome.sandbox.executors.host.bubblewrap import _build_safe_env
            env = _build_safe_env(
                security_profile=getattr(request, "security_profile", "HIGH_SECURITY") or "HIGH_SECURITY",
                custom_env_vars=request.env_vars,
            )

            cmd = [sys.executable, str(script_path)]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(temp_path),
                    env=env,
                )

                timeout_sec = (request.timeout_ms or 10000) / 1000.0
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout_sec
                    )
                    timed_out = False
                    exit_code = proc.returncode or 0
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    stdout_bytes, stderr_bytes = b"", b"Execution timed out (fallback mode)."
                    timed_out = True
                    exit_code = 124

                output_files = {}
                for p in temp_path.rglob("*"):
                    if p.is_file() and p.name != script_filename:
                        rel = str(p.relative_to(temp_path)).replace("\\", "/")
                        output_files[rel] = p.read_bytes()

                return ExecResult(
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                    exit_code=exit_code,
                    timed_out=timed_out,
                    duration_ms=(time.time() - start_time) * 1000.0,
                    output_files=output_files,
                )
            except Exception as e:
                return ExecResult(
                    stdout="",
                    stderr=f"Fallback subprocess error: {str(e)}",
                    exit_code=1,
                    timed_out=False,
                    duration_ms=(time.time() - start_time) * 1000.0,
                    output_files={},
                )

    async def execute_stream(
        self, request: ExecRequest
    ) -> AsyncGenerator[tuple[str, str], None]:
        """Stream execution output from MicroVM guest."""
        result = await self.execute(request)
        if result.stdout:
            yield ("stdout", result.stdout)
        if result.stderr:
            yield ("stderr", result.stderr)

    async def shutdown(self) -> None:
        """Destroy all active MicroVM instances and clean up infrastructure."""
        for vm_id in list(self.instances.keys()):
            try:
                await self.destroy_vm(vm_id)
            except Exception as exc:
                logger.warning("Error destroying VM %s during shutdown: %s", vm_id, exc)

        # Clean up bridge and TAP devices
        try:
            cleanup_all_tap_devices()
            cleanup_bridge(self._bridge_name)
        except Exception as exc:
            logger.warning("Infrastructure cleanup failed: %s", exc)

    async def health_check(self) -> bool:
        """Check MicroVM executor health."""
        return self._initialized and self.kvm_available

    # ─── Snapshot & Restore (VM-level) ───────────────────────────────────────

    async def snapshot_vm(self, vm_id: str, snapshot_id: str) -> str:
        """Take a full VM-level snapshot (memory + CPU + disk state).

        Mirrors Arrakis ``SnapshotVM`` in server.go.
        Pauses the VM, copies the stateful disk, calls CHV snapshot API,
        then resumes.

        Returns:
            The snapshot_id.
        """
        instance = self.instances.get(vm_id)
        if not instance or not instance.chv_client:
            raise ValueError(f"VM {vm_id} not found or not running")

        output_dir = self._snapshot_dir / snapshot_id
        if output_dir.exists():
            raise ValueError(f"Snapshot {snapshot_id} already exists")
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Pause VM (required before snapshot per CHV spec)
            instance.chv_client.pause_vm()
            instance.status = VMStatus.PAUSED
            logger.info("VM %s paused for snapshot", vm_id)

            # 2. Copy stateful disk to snapshot directory
            stateful_dest = str(output_dir / STATEFUL_DISK_FILENAME)
            _copy_file(instance.stateful_disk_path, stateful_dest)
            logger.info("Copied stateful disk to %s", stateful_dest)

            # 3. Save CID
            cid_path = output_dir / CID_FILENAME
            cid_path.write_text(str(instance.cid))

            # 4. Call CHV snapshot API
            snapshot_url = f"file://{output_dir}"
            instance.chv_client.snapshot_vm(snapshot_url)
            logger.info("VM %s snapshot created at %s", vm_id, output_dir)

        finally:
            # 5. Always resume the VM
            try:
                instance.chv_client.resume_vm()
                instance.status = VMStatus.RUNNING
                logger.info("VM %s resumed after snapshot", vm_id)
            except Exception as exc:
                logger.error("Failed to resume VM %s after snapshot: %s", vm_id, exc)

        return snapshot_id

    async def restore_vm(self, vm_name: str, snapshot_id: str) -> MicroVMInstance:
        """Restore a VM from a snapshot.

        Mirrors Arrakis ``restoreVM`` in server.go.
        Creates a new CHV process, restores the snapshot state,
        re-establishes networking.

        Returns:
            The restored MicroVMInstance.
        """
        snapshot_path = self._snapshot_dir / snapshot_id
        if not snapshot_path.exists():
            raise ValueError(f"Snapshot {snapshot_id} does not exist")

        vm_id = f"mvm_{uuid.uuid4().hex[:8]}"
        vm_state_dir = self._state_dir / vm_id
        vm_state_dir.mkdir(parents=True, exist_ok=True)

        instance = MicroVMInstance(
            vm_id=vm_id,
            name=vm_name,
            state_dir=vm_state_dir,
        )

        try:
            # 1. Read CID from snapshot
            cid_path = snapshot_path / CID_FILENAME
            cid = int(cid_path.read_text().strip())
            self._cid_allocator.claim_cid(cid)
            instance.cid = cid

            # 2. Allocate network resources
            instance.tap_device = self._tap_manager.create_tap_device()
            allocated_ip = self._ip_allocator.allocate_ip()
            instance.ip_address = str(allocated_ip)
            instance.ip_bare = str(allocated_ip.ip)

            # 3. Copy stateful disk from snapshot to VM state
            instance.stateful_disk_path = str(vm_state_dir / STATEFUL_DISK_FILENAME)
            _copy_file(
                str(snapshot_path / STATEFUL_DISK_FILENAME),
                instance.stateful_disk_path,
            )

            # 4. Spawn CHV process (for restore mode)
            instance.api_socket_path = str(vm_state_dir / f"{vm_id}.sock")
            log_file = open(vm_state_dir / "log", "w")
            cmd = [self._chv_binary, "--api-socket", instance.api_socket_path]
            instance.process = subprocess.Popen(
                cmd, stdout=log_file, stderr=log_file, preexec_fn=os.setpgrp,
            )

            # 5. Wait for API and restore
            instance.chv_client = CHVClient(instance.api_socket_path)
            instance.chv_client.wait_for_api(timeout=10.0)

            instance.chv_client.restore_vm(f"file://{snapshot_path}")
            logger.info("VM %s restored from snapshot %s", vm_id, snapshot_id)

            instance.chv_client.resume_vm()
            instance.status = VMStatus.RUNNING

            # 6. Setup vsock/HTTP clients
            instance.vsock_path = str(vm_state_dir / "vsock.sock")
            instance.vsock_client = VsockClient(
                instance.vsock_path, port=self._vsock_port
            )
            instance.guest_http_client = GuestHTTPClient(
                instance.ip_bare, port=self._cmd_server_port
            )

            # 7. Wait for guest readiness
            try:
                await instance.guest_http_client.wait_for_ready(
                    timeout=CMD_SERVER_READY_TIMEOUT
                )
            except Exception as exc:
                logger.warning("Guest not ready after restore: %s", exc)

        except Exception:
            self._cleanup_vm_resources(instance)
            raise

        self.instances[vm_id] = instance
        return instance
