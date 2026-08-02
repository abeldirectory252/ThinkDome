"""Thread-safe resource allocators for MicroVM infrastructure.

Provides pool-based allocators for IP addresses, vsock Context IDs (CIDs),
and TAP device IDs. Ported from the Arrakis Go reference implementation:
  - ipallocator.go   → IPAllocator
  - cidallocator.go   → CIDAllocator
  - fountain.go       → TapDeviceManager
"""

from __future__ import annotations

import ipaddress
import logging
import subprocess
import threading
from dataclasses import dataclass
from typing import Optional, List

logger = logging.getLogger(__name__)


# ─── TAP Device ──────────────────────────────────────────────────────────────

@dataclass
class TapDevice:
    """Represents a created TAP network device."""
    name: str
    device_id: int


class TapDeviceManager:
    """Thread-safe TAP device lifecycle manager.

    Mirrors Arrakis ``Fountain`` (fountain.go). Manages a pool of TAP device
    IDs and calls real ``ip tuntap`` / ``ip link`` commands to create and
    destroy TAP interfaces attached to a Linux bridge.
    """

    LOW_ID = 0
    HIGH_ID = 65535

    def __init__(self, bridge_name: str, low_id: int = LOW_ID, high_id: int = HIGH_ID) -> None:
        self.bridge_name = bridge_name
        self._lock = threading.Lock()
        self._available: List[int] = list(range(low_id, high_id + 1))
        self._low_id = low_id
        self._high_id = high_id

    # ── Internal pool management ──

    def _allocate_id(self) -> int:
        if not self._available:
            raise RuntimeError(
                f"No available TAP device IDs in range {self._low_id}–{self._high_id}"
            )
        return self._available.pop(0)

    def _free_id(self, device_id: int) -> None:
        if device_id < self._low_id or device_id > self._high_id:
            raise ValueError(
                f"TAP ID {device_id} outside range {self._low_id}–{self._high_id}"
            )
        if device_id in self._available:
            raise ValueError(f"TAP ID {device_id} is already free")
        self._available.append(device_id)

    def _claim_id(self, device_id: int) -> None:
        if device_id < self._low_id or device_id > self._high_id:
            raise ValueError(
                f"TAP ID {device_id} outside range {self._low_id}–{self._high_id}"
            )
        try:
            self._available.remove(device_id)
        except ValueError:
            raise ValueError(f"TAP ID {device_id} is not available")

    # ── Public API ──

    def create_tap_device(self, claim_id: Optional[int] = None) -> TapDevice:
        """Create a real Linux TAP device and attach it to the bridge.

        If ``claim_id`` is given, that specific ID is claimed from the pool
        instead of auto-allocating.

        Runs (as root / with CAP_NET_ADMIN):
            ip tuntap add dev tapN mode tap
            ip link set dev tapN master <bridge>
            ip link set tapN up
        """
        with self._lock:
            if claim_id is not None:
                self._claim_id(claim_id)
                allocated_id = claim_id
            else:
                allocated_id = self._allocate_id()

        device_name = f"tap{allocated_id}"
        try:
            subprocess.run(
                ["ip", "tuntap", "add", "dev", device_name, "mode", "tap"],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["ip", "link", "set", "dev", device_name, "master", self.bridge_name],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["ip", "link", "set", device_name, "up"],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:
            # Roll back the ID allocation on failure
            with self._lock:
                self._free_id(allocated_id)
            raise RuntimeError(
                f"Failed to create TAP device {device_name}: {exc.stderr}"
            ) from exc

        logger.info("Created TAP device %s (id=%d) on bridge %s", device_name, allocated_id, self.bridge_name)
        return TapDevice(name=device_name, device_id=allocated_id)

    def destroy_tap_device(self, device: TapDevice) -> None:
        """Destroy a TAP device: remove from bridge, bring down, delete."""
        logger.info("Destroying TAP device %s (id=%d)", device.name, device.device_id)

        for cmd in [
            ["ip", "link", "set", device.name, "nomaster"],
            ["ip", "link", "set", device.name, "down"],
            ["ip", "tuntap", "del", "dev", device.name, "mode", "tap"],
        ]:
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as exc:
                logger.warning("TAP cleanup command %s failed: %s", cmd, exc.stderr)

        with self._lock:
            if self._low_id <= device.device_id <= self._high_id:
                try:
                    self._free_id(device.device_id)
                except ValueError:
                    pass  # Already freed


# ─── IP Allocator ────────────────────────────────────────────────────────────

class IPAllocator:
    """Thread-safe subnet-based IP address pool allocator.

    Mirrors Arrakis ``IPAllocator`` (ipallocator.go). Given a subnet CIDR
    (e.g. ``10.20.1.0/24``), generates all usable host IPs (skipping the
    network address and first host reserved as gateway).
    """

    def __init__(self, subnet_cidr: str) -> None:
        self._network = ipaddress.IPv4Network(subnet_cidr, strict=False)
        self._lock = threading.Lock()

        # Skip network address (.0) and gateway (.1), start from .2
        all_hosts = list(self._network.hosts())
        self._available: List[ipaddress.IPv4Address] = all_hosts[1:]  # skip .1 (gateway)

    def allocate_ip(self) -> ipaddress.IPv4Interface:
        """Allocate the next available IP address from the pool."""
        with self._lock:
            if not self._available:
                raise RuntimeError(f"No available IPs in subnet {self._network}")
            ip = self._available.pop(0)
        return ipaddress.IPv4Interface(f"{ip}/{self._network.prefixlen}")

    def free_ip(self, ip: ipaddress.IPv4Address) -> None:
        """Return an IP address to the available pool."""
        if isinstance(ip, ipaddress.IPv4Interface):
            ip = ip.ip
        with self._lock:
            if ip not in self._network:
                raise ValueError(f"IP {ip} is not in subnet {self._network}")
            self._available.append(ip)

    def claim_ip(self, ip: ipaddress.IPv4Address) -> None:
        """Claim a specific IP from the pool (used during snapshot restore)."""
        if isinstance(ip, ipaddress.IPv4Interface):
            ip = ip.ip
        with self._lock:
            if ip not in self._network:
                raise ValueError(f"IP {ip} is not in subnet {self._network}")
            try:
                self._available.remove(ip)
            except ValueError:
                pass  # IP may already be allocated (idempotent claim)


# ─── CID Allocator ──────────────────────────────────────────────────────────

class CIDAllocator:
    """Thread-safe Context ID allocator for vsock guest addressing.

    Mirrors Arrakis ``CIDAllocator`` (cidallocator.go). CIDs must be >= 3
    (0 = hypervisor, 1 = loopback, 2 = host).
    """

    def __init__(self, low_cid: int = 3, high_cid: int = 1000) -> None:
        if low_cid < 3:
            raise ValueError("CID must be >= 3")
        if low_cid > high_cid:
            raise ValueError(f"Invalid CID range: {low_cid}–{high_cid}")

        self._low = low_cid
        self._high = high_cid
        self._lock = threading.Lock()
        self._available: List[int] = list(range(low_cid, high_cid + 1))

    def allocate_cid(self) -> int:
        """Allocate the next available CID."""
        with self._lock:
            if not self._available:
                raise RuntimeError(
                    f"No available CIDs in range {self._low}–{self._high}"
                )
            return self._available.pop(0)

    def free_cid(self, cid: int) -> None:
        """Return a CID to the pool."""
        with self._lock:
            if cid < self._low or cid > self._high:
                raise ValueError(
                    f"CID {cid} outside range {self._low}–{self._high}"
                )
            if cid in self._available:
                raise ValueError(f"CID {cid} is already free")
            self._available.append(cid)

    def claim_cid(self, cid: int) -> None:
        """Claim a specific CID (used during snapshot restore)."""
        with self._lock:
            try:
                self._available.remove(cid)
            except ValueError:
                raise ValueError(f"CID {cid} is not available")
