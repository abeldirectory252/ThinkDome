"""Cloud Hypervisor REST API client over UNIX domain socket.

Speaks to the Cloud Hypervisor (CHV) VMM via its local HTTP API exposed
on a UNIX socket. Mirrors the ``createApiClient`` / API call patterns in
Arrakis server.go.

Reference: Ref/arrakis-main/api/chv-api.yaml (OpenAPI 3.0 spec)
"""

from __future__ import annotations

import json
import logging
import socket
import time
from dataclasses import dataclass, field, asdict
from http.client import HTTPConnection
from typing import Optional, Dict, Any, List
from urllib.parse import quote

logger = logging.getLogger(__name__)

# ─── Custom HTTP connection over UNIX socket ─────────────────────────────────

class UnixSocketHTTPConnection(HTTPConnection):
    """HTTPConnection subclass that connects via a UNIX domain socket."""

    def __init__(self, socket_path: str, timeout: float = 30.0) -> None:
        # Use "localhost" as a dummy host; the actual transport is the socket.
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._socket_path)


# ─── VmConfig data structures ────────────────────────────────────────────────

@dataclass
class PayloadConfig:
    """Kernel/initramfs payload for the VM."""
    kernel: Optional[str] = None
    cmdline: Optional[str] = None
    initramfs: Optional[str] = None
    firmware: Optional[str] = None


@dataclass
class DiskConfig:
    """Virtual block device (disk) configuration."""
    path: str
    readonly: Optional[bool] = None
    num_queues: Optional[int] = None

    def to_api_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"path": self.path}
        if self.readonly is not None:
            d["readonly"] = self.readonly
        if self.num_queues is not None:
            d["num_queues"] = self.num_queues
        return d


@dataclass
class CpusConfig:
    """vCPU configuration."""
    boot_vcpus: int = 2
    max_vcpus: int = 2

    def to_api_dict(self) -> Dict[str, Any]:
        return {"boot_vcpus": self.boot_vcpus, "max_vcpus": self.max_vcpus}


@dataclass
class MemoryConfig:
    """Guest memory configuration (size in bytes)."""
    size: int  # bytes

    def to_api_dict(self) -> Dict[str, Any]:
        return {"size": self.size}


@dataclass
class NetConfig:
    """Network device configuration."""
    tap: str
    num_queues: int = 2
    queue_size: int = 256
    id: str = "_net0"

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "tap": self.tap,
            "num_queues": self.num_queues,
            "queue_size": self.queue_size,
            "id": self.id,
        }


@dataclass
class VsockConfig:
    """Vsock device configuration."""
    cid: int
    socket: str

    def to_api_dict(self) -> Dict[str, Any]:
        return {"cid": self.cid, "socket": self.socket}


@dataclass
class ConsoleConfig:
    """Serial/console configuration."""
    mode: str = "Tty"

    def to_api_dict(self) -> Dict[str, Any]:
        return {"mode": self.mode}


@dataclass
class VmConfig:
    """Full VM configuration for the CHV ``/vm.create`` API.

    Mirrors ``chvapi.VmConfig`` from the Arrakis Go client.
    """
    payload: PayloadConfig
    disks: List[DiskConfig] = field(default_factory=list)
    cpus: Optional[CpusConfig] = None
    memory: Optional[MemoryConfig] = None
    net: List[NetConfig] = field(default_factory=list)
    vsock: Optional[VsockConfig] = None
    serial: Optional[ConsoleConfig] = None
    console: Optional[ConsoleConfig] = None

    def to_api_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict for the CHV API."""
        d: Dict[str, Any] = {}

        # Payload (required)
        payload_d: Dict[str, Any] = {}
        if self.payload.kernel:
            payload_d["kernel"] = self.payload.kernel
        if self.payload.cmdline:
            payload_d["cmdline"] = self.payload.cmdline
        if self.payload.initramfs:
            payload_d["initramfs"] = self.payload.initramfs
        if self.payload.firmware:
            payload_d["firmware"] = self.payload.firmware
        d["payload"] = payload_d

        # Disks
        if self.disks:
            d["disks"] = [disk.to_api_dict() for disk in self.disks]

        # CPUs
        if self.cpus:
            d["cpus"] = self.cpus.to_api_dict()

        # Memory
        if self.memory:
            d["memory"] = self.memory.to_api_dict()

        # Network
        if self.net:
            d["net"] = [n.to_api_dict() for n in self.net]

        # Vsock
        if self.vsock:
            d["vsock"] = self.vsock.to_api_dict()

        # Serial / Console
        if self.serial:
            d["serial"] = self.serial.to_api_dict()
        if self.console:
            d["console"] = self.console.to_api_dict()

        return d


# ─── CHV API Client ──────────────────────────────────────────────────────────

class CHVClient:
    """Client for the Cloud Hypervisor local HTTP API over UNIX socket.

    Mirrors Arrakis ``createApiClient`` + all the ``apiClient.DefaultAPI.*``
    call sites in server.go.

    Usage::

        client = CHVClient("/path/to/api.sock")
        client.wait_for_api(timeout=10.0)
        client.create_vm(vm_config)
        client.boot_vm()
        ...
        client.shutdown_vm()
        client.shutdown_vmm()
    """

    API_BASE = "/api/v1"

    def __init__(self, api_socket_path: str, timeout: float = 30.0) -> None:
        self.api_socket_path = api_socket_path
        self.timeout = timeout

    def _conn(self) -> UnixSocketHTTPConnection:
        return UnixSocketHTTPConnection(self.api_socket_path, timeout=self.timeout)

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        expected_status: int = 204,
    ) -> Optional[Dict[str, Any]]:
        """Send an HTTP request to the CHV API and return parsed JSON (if any)."""
        url = f"{self.API_BASE}{path}"
        conn = self._conn()
        try:
            headers = {}
            body_bytes = None
            if body is not None:
                body_bytes = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"

            conn.request(method, url, body=body_bytes, headers=headers)
            resp = conn.getresponse()
            resp_body = resp.read()

            if resp.status != expected_status and resp.status not in (200, 204):
                raise RuntimeError(
                    f"CHV API {method} {url} returned {resp.status}: "
                    f"{resp_body.decode('utf-8', errors='replace')}"
                )

            if resp_body and resp.status == 200:
                return json.loads(resp_body)
            return None
        finally:
            conn.close()

    # ── VMM-level endpoints ──

    def ping(self) -> Dict[str, Any]:
        """Ping the VMM to verify API availability.

        ``GET /vmm.ping`` → 200 with ``VmmPingResponse``
        """
        result = self._request("GET", "/vmm.ping", expected_status=200)
        return result or {}

    def shutdown_vmm(self) -> None:
        """Shut down the entire Cloud Hypervisor VMM process.

        ``PUT /vmm.shutdown`` → 204
        """
        self._request("PUT", "/vmm.shutdown")

    # ── VM lifecycle endpoints ──

    def create_vm(self, config: VmConfig) -> None:
        """Create a VM instance (not yet booted).

        ``PUT /vm.create`` with VmConfig body → 204
        """
        self._request("PUT", "/vm.create", body=config.to_api_dict())

    def boot_vm(self) -> None:
        """Boot the previously created VM.

        ``PUT /vm.boot`` → 204
        """
        self._request("PUT", "/vm.boot")

    def pause_vm(self) -> None:
        """Pause a running VM.

        ``PUT /vm.pause`` → 204
        """
        self._request("PUT", "/vm.pause")

    def resume_vm(self) -> None:
        """Resume a paused VM.

        ``PUT /vm.resume`` → 204
        """
        self._request("PUT", "/vm.resume")

    def shutdown_vm(self) -> None:
        """Gracefully shut down the VM guest.

        ``PUT /vm.shutdown`` → 204
        """
        self._request("PUT", "/vm.shutdown")

    def delete_vm(self) -> None:
        """Delete the VM instance.

        ``PUT /vm.delete`` → 204
        """
        self._request("PUT", "/vm.delete")

    # ── Snapshot / Restore endpoints ──

    def snapshot_vm(self, destination_url: str) -> None:
        """Take a VM snapshot. VM must be paused first.

        ``PUT /vm.snapshot`` with ``VmSnapshotConfig`` → 204

        Args:
            destination_url: ``file:///path/to/snapshot/dir``
        """
        self._request(
            "PUT", "/vm.snapshot",
            body={"destination_url": destination_url},
        )

    def restore_vm(self, source_url: str) -> None:
        """Restore a VM from a snapshot.

        ``PUT /vm.restore`` with ``RestoreConfig`` → 204

        Args:
            source_url: ``file:///path/to/snapshot/dir``
        """
        self._request(
            "PUT", "/vm.restore",
            body={"source_url": source_url},
        )

    # ── VM info ──

    def vm_info(self) -> Dict[str, Any]:
        """Get VM information.

        ``GET /vm.info`` → 200 with ``VmInfo``
        """
        result = self._request("GET", "/vm.info", expected_status=200)
        return result or {}

    # ── Readiness helpers ──

    def wait_for_api(self, timeout: float = 10.0, poll_interval: float = 0.01) -> None:
        """Poll the VMM ping endpoint until the API is reachable.

        Mirrors Arrakis ``waitForServer`` in server.go.

        Raises:
            TimeoutError: If the API is not ready within *timeout* seconds.
        """
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                info = self.ping()
                build_version = info.get("build_version", "unknown")
                logger.info(
                    "Cloud Hypervisor API ready (build: %s) at %s",
                    build_version, self.api_socket_path,
                )
                return
            except Exception as exc:
                last_error = exc
                time.sleep(poll_interval)
        raise TimeoutError(
            f"CHV API at {self.api_socket_path} not ready after {timeout}s: {last_error}"
        )
