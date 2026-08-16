"""Host-side Linux networking management for MicroVM isolation.

Provides utilities for setting up and tearing down:
  - Linux bridges (br0)
  - iptables NAT/MASQUERADE rules for outbound traffic
  - iptables DNAT PREROUTING rules for port forwarding into guest VMs
  - IP forwarding (sysctl)
  - TAP device cleanup

Ported from the Arrakis Go reference:
  - setupBridgeAndFirewall()   → setup_bridge_and_firewall()
  - cleanupBridge()            → cleanup_bridge()
  - setupSinglePortForward()   → setup_port_forward()
  - cleanupAllIPTablesRulesForIP() → cleanup_iptables_for_ip()
  - cleanupTapDevices()        → cleanup_all_tap_devices()

All functions require root or CAP_NET_ADMIN capabilities.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional

from thinkdome.sandbox.executors.microvm.exceptions import (
    InsufficientPrivilegesError,
    NetworkConfigurationError,
)

logger = logging.getLogger(__name__)


@dataclass
class PortForward:
    """A DNAT port forwarding rule mapping host_port -> guest_ip:guest_port."""
    host_port: int
    guest_port: int
    description: str


def has_net_admin_privileges() -> bool:

    """Check if process has root (UID 0) privileges required for host network manipulation."""
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _run(cmd: List[str], check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:

    """Run a command with logging."""
    logger.debug("Running: %s", " ".join(cmd))
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def _get_default_interface() -> str:
    """Get the host's default network interface name.

    Equivalent to: ``ip r | grep default | awk '{print $5}'``
    """
    result = _run(["sh", "-c", "ip r | grep default | awk '{print $5}'"])
    iface = result.stdout.strip()
    if not iface:
        raise RuntimeError("Could not determine default network interface")
    return iface


def bridge_exists(bridge_name: str) -> bool:
    """Check if a Linux bridge with the given name exists."""
    result = _run(["ip", "link", "show", "type", "bridge"], check=False)
    if result.returncode != 0:
        return False
    return f"{bridge_name}:" in result.stdout


# ─── Bridge & Firewall Setup ────────────────────────────────────────────────

def setup_bridge_and_firewall(
    bridge_name: str,
    bridge_ip: str,
    bridge_subnet: str,
    backup_file: Optional[str] = None,
) -> None:
    """Set up the Linux bridge and iptables firewall rules for MicroVM networking.

    Mirrors Arrakis ``setupBridgeAndFirewall`` in server.go.

    This creates:
      1. A Linux bridge (e.g. ``br0``)
      2. Assigns the bridge IP (e.g. ``10.20.1.1/24``)
      3. Enables IP forwarding for the bridge and default interface
      4. Adds MASQUERADE rule for outbound NAT
      5. Adds FORWARD rules for the subnet

    Args:
        bridge_name: Name for the bridge device (e.g. ``"br0"``).
        bridge_ip: Bridge IP with CIDR (e.g. ``"10.20.1.1/24"``).
        bridge_subnet: Subnet CIDR (e.g. ``"10.20.1.0/24"``).
        backup_file: Optional path to save iptables backup before modifications.
    """
    # Upfront privilege check
    if not has_net_admin_privileges():
        raise InsufficientPrivilegesError(
            f"Configuring Linux bridge '{bridge_name}' and firewall rules requires root (UID 0) or CAP_NET_ADMIN privileges."
        )

    # Save iptables backup
    if backup_file is None:
        backup_file = f"/tmp/iptables-backup-{int(time.time())}.rules"
    try:
        result = _run(["iptables-save"], check=False)
        if result.returncode == 0:
            with open(backup_file, "w") as f:
                f.write(result.stdout)
            logger.info("Saved iptables backup to %s", backup_file)
    except Exception as exc:
        logger.warning("Could not save iptables backup: %s", exc)

    # Get default network interface
    host_iface = _get_default_interface()
    logger.info("Host default interface: %s", host_iface)

    # Check if bridge already exists
    if bridge_exists(bridge_name):
        logger.info("Bridge %s already exists, skipping setup", bridge_name)
        return

    # Setup bridge and firewall rules
    commands = [
        ["ip", "link", "add", bridge_name, "type", "bridge"],
        ["ip", "link", "set", bridge_name, "up"],
        ["ip", "addr", "add", bridge_ip, "dev", bridge_name, "scope", "host"],
        ["iptables", "-t", "nat", "-A", "POSTROUTING", "-s", bridge_subnet, "-o", host_iface, "-j", "MASQUERADE"],
        ["sysctl", "-w", f"net.ipv4.conf.{host_iface}.forwarding=1"],
        ["sysctl", "-w", f"net.ipv4.conf.{bridge_name}.forwarding=1"],
        ["iptables", "-t", "filter", "-I", "FORWARD", "-s", bridge_subnet, "-j", "ACCEPT"],
        ["iptables", "-t", "filter", "-I", "FORWARD", "-d", bridge_subnet, "-j", "ACCEPT"],
    ]

    for cmd in commands:
        try:
            _run(cmd)
        except (subprocess.CalledProcessError, RuntimeError) as exc:
            stderr = getattr(exc, "stderr", None) or str(exc)
            raise NetworkConfigurationError(
                f"Failed to execute bridge setup command '{' '.join(cmd)}': {stderr.strip()}"
            ) from exc



    logger.info(
        "Bridge %s created with IP %s, subnet %s",
        bridge_name, bridge_ip, bridge_subnet,
    )


# ─── Port Forwarding ────────────────────────────────────────────────────────

def setup_port_forward(
    vm_ip: str,
    guest_port: int,
    host_port: int,
    description: str = "",
) -> PortForward:
    """Create an iptables DNAT rule to forward a host port to a guest VM port.

    Mirrors Arrakis ``setupSinglePortForward`` in server.go.

    Creates: ``iptables -t nat -A PREROUTING -p tcp --dport <host_port>
                -j DNAT --to-destination <vm_ip>:<guest_port>``
    """
    logger.info(
        "Setting up port forward: host:%d → %s:%d (%s)",
        host_port, vm_ip, guest_port, description,
    )

    _run([
        "iptables", "-t", "nat", "-A", "PREROUTING",
        "-p", "tcp", "--dport", str(host_port),
        "-j", "DNAT", "--to-destination", f"{vm_ip}:{guest_port}",
    ])

    return PortForward(
        host_port=host_port,
        guest_port=guest_port,
        description=description,
    )


# ─── Cleanup ────────────────────────────────────────────────────────────────

def cleanup_iptables_for_ip(ip: str) -> None:
    """Delete all iptables NAT PREROUTING rules targeting the given IP.

    Mirrors Arrakis ``cleanupAllIPTablesRulesForIP`` in server.go.
    Rules are deleted in reverse order to maintain correct line numbering.
    """
    logger.info("Cleaning up iptables rules for IP: %s", ip)

    result = _run(
        ["iptables", "-t", "nat", "-L", "PREROUTING", "-n", "--line-numbers"],
        check=False,
    )
    if result.returncode != 0:
        logger.warning("Could not list iptables rules: %s", result.stderr)
        return

    # Parse rule numbers targeting this IP
    rule_numbers = []
    for line in result.stdout.splitlines()[2:]:  # Skip header lines
        if f"to:{ip}:" in line:
            fields = line.split()
            if fields:
                try:
                    rule_numbers.append(int(fields[0]))
                except ValueError:
                    pass

    # Delete in reverse order to avoid renumbering issues
    for rule_num in sorted(rule_numbers, reverse=True):
        logger.info("Deleting iptables rule %d for IP %s", rule_num, ip)
        _run(
            ["iptables", "-t", "nat", "-D", "PREROUTING", str(rule_num)],
            check=False,
        )


def cleanup_bridge(bridge_name: str = "br0") -> None:
    """Delete a Linux bridge if it exists.

    Mirrors Arrakis ``cleanupBridge`` in server.go.
    """
    result = _run(["ip", "link", "show", bridge_name], check=False)
    if result.returncode != 0:
        # Bridge doesn't exist
        return

    _run(["ip", "link", "delete", bridge_name], check=False)
    logger.info("Deleted bridge: %s", bridge_name)


def cleanup_all_tap_devices() -> None:
    """Delete all TAP network interfaces.

    Mirrors Arrakis ``cleanupTapDevices`` in server.go.
    """
    import re

    result = _run(["ip", "link", "show"], check=False)
    if result.returncode != 0:
        return

    # Find all interface names starting with "tap"
    for line in result.stdout.splitlines():
        match = re.match(r'\d+:\s+(tap\d+)', line)
        if match:
            device_name = match.group(1)
            _run(["ip", "link", "delete", device_name], check=False)
            logger.info("Deleted TAP device: %s", device_name)


def get_ip_prefix(cidr: str) -> str:
    """Extract the IP prefix octets from a CIDR based on mask.

    Mirrors Arrakis ``getIPPrefix`` in server.go.
    E.g. ``"10.20.1.0/24"`` → ``"10.20.1"``
    """
    import ipaddress
    network = ipaddress.IPv4Network(cidr, strict=False)
    prefix_len = network.prefixlen
    complete_octets = prefix_len // 8
    octets = str(network.network_address).split(".")
    if 0 < complete_octets <= len(octets):
        return ".".join(octets[:complete_octets])
    raise ValueError(f"Invalid mask size: {prefix_len}")
