"""Vsock IPC client for host-to-guest command execution.

Connects to the Cloud Hypervisor vsock UNIX domain socket proxy on the host
side, sends a ``CONNECT <port>`` handshake to reach the in-guest vsockserver
daemon, and then executes commands / transfers files over the connection.

Mirrors the Arrakis ``vsockclient`` (cmd/vsockclient/main.go) and the
``cmdserver`` JSON protocol (pkg/cmdserver/cmdserver.go).

The in-guest server exposes:
  - Command execution via vsock text protocol (port 4032)
  - HTTP JSON API on guest IP port 4031 for ``/cmd``, ``/files`` endpoints
"""

from __future__ import annotations

import json
import asyncio
import logging
import socket
import time
from typing import Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)


class VsockClient:
    """Client for communicating with the in-guest vsock command server.

    The Cloud Hypervisor vsock implementation exposes a UNIX domain socket
    on the host. Sending ``CONNECT <port>\\n`` to this socket opens a
    tunnel to the guest process listening on that vsock port.

    Usage::

        client = VsockClient("/path/to/vsock.sock", port=4032)
        output = client.execute_command("echo hello")
    """

    def __init__(self, socket_path: str, port: int = 4032) -> None:
        self.socket_path = socket_path
        self.port = port

    def _connect(self, timeout: float = 10.0) -> socket.socket:
        """Open a connection to the guest vsock server via CHV's UNIX socket proxy.

        Sends the ``CONNECT <port>`` handshake and validates the ``OK`` response.
        """
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(self.socket_path)

        # CHV vsock proxy handshake: send "CONNECT <port>\n"
        connect_cmd = f"CONNECT {self.port}\n"
        sock.sendall(connect_cmd.encode("utf-8"))

        # Read response line
        response = b""
        while not response.endswith(b"\n"):
            chunk = sock.recv(1024)
            if not chunk:
                raise ConnectionError("Vsock proxy closed connection during handshake")
            response += chunk

        response_str = response.decode("utf-8").strip()
        if not response_str.startswith("OK"):
            sock.close()
            raise ConnectionError(f"Vsock CONNECT handshake failed: {response_str}")

        logger.debug("Vsock connected to guest port %d via %s", self.port, self.socket_path)
        return sock

    def execute_command(self, cmd: str, timeout: float = 30.0) -> str:
        """Execute a shell command inside the guest via the vsock text protocol.

        This mirrors the Arrakis vsockserver: the guest reads a line from the
        connection, executes it via ``/bin/bash -c``, and writes the combined
        output back.

        Args:
            cmd: Shell command string to execute.
            timeout: Socket timeout in seconds.

        Returns:
            Combined stdout+stderr output from the guest.
        """
        sock = self._connect(timeout=timeout)
        try:
            # Send command (must end with newline)
            if not cmd.endswith("\n"):
                cmd += "\n"
            sock.sendall(cmd.encode("utf-8"))

            # Read response until the connection yields a complete response.
            # The vsockserver sends output followed by a newline.
            response_chunks = []
            sock.settimeout(timeout)
            while True:
                try:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    response_chunks.append(chunk)
                    # Check if we got a complete line
                    if chunk.endswith(b"\n"):
                        break
                except socket.timeout:
                    break

            return b"".join(response_chunks).decode("utf-8", errors="replace")
        finally:
            sock.close()

    def is_ready(self, timeout: float = 5.0) -> bool:
        """Check if the vsock server inside the guest is reachable."""
        try:
            sock = self._connect(timeout=timeout)
            sock.close()
            return True
        except Exception:
            return False


class GuestHTTPClient:
    """HTTP-based client for the in-guest command/file server.

    Communicates with the ``cmdserver`` running on the guest's network IP
    at port 4031 (matching Arrakis ``waitForCmdServerReady`` and
    ``VMCommand`` / ``VMFileUpload`` / ``VMFileDownload`` in server.go).

    This is the higher-level, structured API alternative to the raw vsock
    text protocol. Used when the guest has network connectivity.

    Usage::

        client = GuestHTTPClient("10.20.1.2", port=4031)
        await client.wait_for_ready(timeout=60)
        result = await client.run_command("python3 /workspace/main.py")
    """

    def __init__(self, guest_ip: str, port: int = 4031, timeout: float = 30.0) -> None:
        self.base_url = f"http://{guest_ip}:{port}"
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def wait_for_ready(
        self, timeout: float = 60.0, poll_interval: float = 0.01
    ) -> None:
        """Poll the guest command server until it's ready.

        Mirrors Arrakis ``waitForCmdServerReady`` in server.go.
        """
        deadline = time.monotonic() + timeout
        last_error = None
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            while time.monotonic() < deadline:
                try:
                    async with session.get(f"{self.base_url}/") as resp:
                        if resp.status == 200:
                            logger.info("Guest command server ready at %s", self.base_url)
                            return
                except Exception as exc:
                    last_error = exc
                await asyncio.sleep(poll_interval)
        raise TimeoutError(
            f"Guest command server at {self.base_url} not ready after {timeout}s: {last_error}"
        )

    async def run_command(
        self, cmd: str, blocking: bool = True
    ) -> Tuple[str, str]:
        """Execute a command inside the guest via the HTTP ``/cmd`` endpoint.

        Mirrors Arrakis ``vm.handleRun`` in server.go.

        Returns:
            Tuple of (output, error) strings.
        """
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            payload = {"cmd": cmd, "blocking": blocking}
            async with session.post(
                f"{self.base_url}/cmd", json=payload
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Guest command execution failed with status {resp.status}"
                    )
                data = await resp.json()
                return data.get("output", ""), data.get("error", "")

    async def upload_files(self, files: Dict[str, bytes]) -> None:
        """Upload files to the guest via the HTTP ``/files`` POST endpoint.

        Mirrors Arrakis ``VMFileUpload`` in server.go.
        """
        import base64

        file_list = []
        for path, content in files.items():
            # The cmdserver expects base64-encoded content for binary safety
            if isinstance(content, bytes):
                encoded = base64.b64encode(content).decode("ascii")
            else:
                encoded = content
            file_list.append({"path": path, "content": encoded})

        payload = {"files": file_list}
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(
                f"{self.base_url}/files", json=payload
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(
                        f"Guest file upload failed ({resp.status}): {body}"
                    )

    async def download_files(self, paths: List[str]) -> Dict[str, str]:
        """Download files from the guest via the HTTP ``/files`` GET endpoint.

        Mirrors Arrakis ``VMFileDownload`` in server.go.

        Returns:
            Dict mapping file path → file content string.
        """
        paths_param = ",".join(paths)
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(
                f"{self.base_url}/files", params={"paths": paths_param}
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Guest file download failed with status {resp.status}"
                    )
                data = await resp.json()
                result = {}
                for file_info in data.get("files", []):
                    path = file_info.get("path", "")
                    content = file_info.get("content", "")
                    error = file_info.get("error", "")
                    if error:
                        logger.warning("Error downloading %s from guest: %s", path, error)
                    else:
                        result[path] = content
                return result
