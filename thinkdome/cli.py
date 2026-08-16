"""ThinkDome CLI - Command-line interface for the ThinkDome server.

Usage::

    thinkdome serve --host 0.0.0.0 --port 8000
    thinkdome version
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path



def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="thinkdome",
        description="ThinkDome - Secure code execution sandbox for AI agents",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start the ThinkDome API server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    serve_parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")

    # version command
    subparsers.add_parser("version", help="Show ThinkDome version")

    # run command
    run_parser = subparsers.add_parser("run", help="Execute code in the sandbox")
    run_parser.add_argument("code", nargs="?", help="Code string to execute")
    run_parser.add_argument("-f", "--file", help="Path to a script file to execute")
    run_parser.add_argument("--timeout", type=int, default=10, help="Timeout in seconds")
    run_parser.add_argument("--backend", default="auto", choices=["auto", "docker", "subprocess", "microvm"])

    # snapshot command
    snap_parser = subparsers.add_parser("snapshot", help="Manage sandbox snapshots")
    snap_parser.add_argument("action", choices=["create", "restore", "list"], help="Snapshot action")
    snap_parser.add_argument("--sandbox", default="default_sandbox", help="Sandbox ID")
    snap_parser.add_argument("--id", help="Snapshot ID for restore")
    snap_parser.add_argument("--tag", help="Tag/name for snapshot")

    # microvm command
    mvm_parser = subparsers.add_parser("microvm", help="Manage MicroVM instances")
    mvm_parser.add_argument("action", choices=["start", "list"], help="MicroVM action")
    mvm_parser.add_argument("--name", default="agent-microvm", help="MicroVM instance name")
    mvm_parser.add_argument("--vcpus", type=int, default=2, help="vCPUs count")
    mvm_parser.add_argument("--memory", type=int, default=512, help="Memory MB")

    # check / doctor command
    subparsers.add_parser("check", help="Check host hypervisor readiness & system diagnostics")
    subparsers.add_parser("doctor", help="Alias for check: diagnose host hypervisor & container runtimes")

    # setup / setup-microvm command
    subparsers.add_parser("setup", help="Download and provision all MicroVM & sandbox prerequisites automatically")
    subparsers.add_parser("setup-microvm", help="Alias for setup: provision hypervisor binaries, kernel, and rootfs")

    args = parser.parse_args()

    if args.command == "serve":
        _serve(args)
    elif args.command == "version":
        _version()
    elif args.command == "run":
        _run(args)
    elif args.command == "snapshot":
        _snapshot(args)
    elif args.command == "microvm":
        _microvm(args)
    elif args.command in ("check", "doctor"):
        _check(args)
    elif args.command in ("setup", "setup-microvm"):
        _setup(args)
    else:
        parser.print_help()
        sys.exit(1)




def _serve(args) -> None:
    """Start the FastAPI server."""
    import uvicorn

    print(f"Starting ThinkDome API server on {args.host}:{args.port}")
    uvicorn.run(
        "thinkdome.api.server:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=["thinkdome"] if args.reload else None,
        workers=args.workers,
    )


def _version() -> None:
    """Print version info."""
    from thinkdome._version import __version__

    print(f"ThinkDome v{__version__}")


def _run(args) -> None:
    """Execute code in a sandbox."""
    from thinkdome import Sandbox

    code = args.code
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            code = f.read()

    if not code:
        print("Error: Provide code as an argument or use --file", file=sys.stderr)
        sys.exit(1)

    with Sandbox(timeout=args.timeout, backend=args.backend) as dome:
        result = dome.run(code)
        if result.output:
            print(result.output, end="")
        if result.error:
            print(result.error, file=sys.stderr, end="")
        sys.exit(result.exit_code)


def _snapshot(args) -> None:
    """Execute snapshot actions from CLI."""
    from thinkdome.sandbox.snapshots.service import SnapshotService
    svc = SnapshotService()

    if args.action == "create":
        meta = svc.create_snapshot(sandbox_id=args.sandbox, tag=args.tag)
        print(f"Created snapshot: {meta['snapshot_id']} (tag: {meta['tag']})")
    elif args.action == "restore":
        if not args.id:
            print("Error: --id is required for restore action", file=sys.stderr)
            sys.exit(1)
        res = svc.restore_snapshot(sandbox_id=args.sandbox, snapshot_id=args.id)
        print(f"Restored sandbox '{args.sandbox}' to snapshot '{args.id}' (success={res['success']})")
    elif args.action == "list":
        snaps = svc.list_snapshots(sandbox_id=args.sandbox)
        print(f"Snapshots for '{args.sandbox}': {len(snaps)}")
        for s in snaps:
            print(f" - [{s['snapshot_id']}] {s['name']} (created: {s['created_at']})")


def _microvm(args) -> None:
    """Execute microvm actions from CLI."""
    from thinkdome.sandbox.executors.microvm import MicroVMExecutor
    executor = MicroVMExecutor()

    if args.action == "start":
        inst = executor.spawn_vm(name=args.name, memory_mb=args.memory, vcpus=args.vcpus)
        print(f"Started MicroVM '{inst.name}' [ID: {inst.vm_id}] IP: {inst.ip_address} TAP: {inst.tap_device}")
    elif args.action == "list":
        print(f"Active MicroVM instances: {len(executor.instances)}")
        for inst in executor.instances.values():
            print(f" - [{inst.vm_id}] {inst.name} ({inst.vcpus} vCPUs, {inst.memory_mb}MB RAM) -> {inst.ip_address}")


def _check(args) -> None:
    """Check host system prerequisites and recommend optimal execution mode."""
    from thinkdome.sandbox.provisioning import SystemProvisioner, StatusLevel

    provisioner = SystemProvisioner()
    report = provisioner.run_diagnostics()

    print("=" * 80)
    print(" 🧠 ThinkDome Host System & Hypervisor Diagnostic Tool")
    print("=" * 80)
    print()
    print(f"[+] OS Platform    : {report.os_info}")
    print(f"[+] User Privilege : {'Root (UID 0)' if report.is_root else f'Unprivileged (UID {report.user_uid})'}")

    if report.is_root:
        print("    ✓ Full privileges to configure TAP interfaces and Linux bridge network.")
    else:
        print("    ! Running non-root: Host TAP/bridge setup requires root or sudo.")

    print()
    print("--- ⚡ MicroVM & KVM Hardware Isolation ---")
    for item in report.items[:5]:
        sym = "✓" if item.level == StatusLevel.OK else "!"
        print(f"  [{sym}] {item.name:<18}: {item.details}")
        if item.suggestion:
            print(f"      ➜ Suggestion: {item.suggestion}")

    print()
    print("--- 🐳 Docker & Secure OCI Runtimes ---")
    for item in report.items[5:]:
        sym = "✓" if item.level == StatusLevel.OK else "!"
        print(f"  [{sym}] {item.name:<18}: {item.details}")
        if item.suggestion:
            print(f"      ➜ Suggestion: {item.suggestion}")

    print()
    print("=" * 80)
    print(" 💡 SUGGESTED CONFIGURATION FOR THIS MACHINE")
    print("=" * 80)

    if report.recommended_backend == "microvm":
        print(" ★ Optimal Mode: Native MicroVM Hardware Virtualization")
        print("   export EXECUTOR_BACKEND=\"microvm\"")
    elif report.recommended_backend == "docker":
        print(" ★ Recommended Mode: Docker Container Isolation")
        print("   export EXECUTOR_BACKEND=\"docker\"")
    else:
        print(" ★ Dev Fallback Mode: Process Isolation with Automatic Fallback")
        print("   export EXECUTOR_BACKEND_USE_FALLBACK=\"True\"")

    print()
    print(" Command to start server:")
    print("   ./venv/bin/python -m thinkdome.cli serve --host 127.0.0.1 --port 8000")


def _setup(args) -> None:
    """Download and provision all MicroVM & sandbox prerequisites automatically."""
    import sys
    from thinkdome.sandbox.provisioning import SystemProvisioner

    print("=" * 80)
    print(" 🚀 ThinkDome Setup - Provisioning All MicroVM & Sandbox Requirements")
    print("=" * 80)
    print()

    provisioner = SystemProvisioner()
    try:
        report = provisioner.setup_prerequisites()
        print()
        print("=" * 80)
        print(" ✅ Provisioning complete! Running diagnostic check now...")
        print("=" * 80)
        print()
        _check(args)
    except PermissionError as pe:
        print()
        print(f" ✘ ERROR: {pe}")
        print()
        print("   Usage:  sudo ./venv/bin/python -m thinkdome.cli setup")
        print("       or: sudo ./scripts/setup_hypervisors.sh")
        print()
        sys.exit(1)




if __name__ == "__main__":
    main()


