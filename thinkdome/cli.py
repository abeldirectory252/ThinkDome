"""ThinkDome CLI - Command-line interface for the ThinkDome server.

Usage::

    thinkdome serve --host 0.0.0.0 --port 8000
    thinkdome version
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import os



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

    node_parser = subparsers.add_parser("node-agent", help="Start the private node-local sandbox agent")
    node_parser.add_argument("--host", default=None, help="Node-agent bind host")
    node_parser.add_argument("--port", type=int, default=None, help="Node-agent bind port")

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

    # stop command
    stop_parser = subparsers.add_parser("stop", help="Stop the running ThinkDome API server")
    stop_parser.add_argument("--force", "-f", action="store_true", help="Forcefully kill the server process (SIGKILL)")

    # reset-admin-password / reset-password commands
    admin_pw_parser = subparsers.add_parser("reset-admin-password", help="Reset Administrator password")
    admin_pw_parser.add_argument("--password", "-p", help="New administrator password")
    admin_pw_parser.add_argument("--username", "-u", default="admin", help="Administrator username (default: admin)")

    pw_parser = subparsers.add_parser("reset-password", help="Reset password for any user account")
    pw_parser.add_argument("username", nargs="?", default="admin", help="Username to reset")
    pw_parser.add_argument("--password", "-p", help="New password")

    # filebox command
    fb_parser = subparsers.add_parser("filebox", help="Manage AI Agent Filebox persistent filesystems")
    fb_sub = fb_parser.add_subparsers(dest="filebox_action", help="Filebox action")

    init_p = fb_sub.add_parser("init", help="Bootstrap a fresh Filebox layout")
    init_p.add_argument("--root", help="Filebox root directory")
    init_p.add_argument("--agent-id", default="agent-001", help="Agent identifier")
    init_p.add_argument("--force", action="store_true", help="Force overwrite manifest")

    stat_p = fb_sub.add_parser("status", help="Show Filebox status and statistics")
    stat_p.add_argument("--root", help="Filebox root directory")

    ver_p = fb_sub.add_parser("verify", help="Validate Filebox structure and permissions")
    ver_p.add_argument("--root", help="Filebox root directory")

    idx_p = fb_sub.add_parser("index", help="Build or rebuild SQLite FTS5 search index")
    idx_p.add_argument("--root", help="Filebox root directory")
    idx_p.add_argument("--force", action="store_true", help="Force full rebuild")

    tree_p = fb_sub.add_parser("tree", help="Display recursive tree view")
    tree_p.add_argument("--root", help="Filebox root directory")
    tree_p.add_argument("--depth", type=int, default=3, help="Max depth (default: 3)")

    search_p = fb_sub.add_parser("search", help="Search content in Filebox")
    search_p.add_argument("query", help="Text search query")
    search_p.add_argument("--root", help="Filebox root directory")

    mig_p = fb_sub.add_parser("migrate", help="Migrate legacy directory or storage into Filebox")
    mig_p.add_argument("--source", help="Source directory (e.g. /sandbox or legacy folder)")
    mig_p.add_argument("--target", help="Target Filebox root directory")
    mig_p.add_argument("--tenant", default="default", help="Tenant ID for platform storage migration")
    mig_p.add_argument("--user", default=None, help="User/owner ID")
    mig_p.add_argument("--dry-run", action="store_true", help="Simulate without writing")

    args = parser.parse_args()

    if args.command == "serve":
        _serve(args)
    elif args.command == "stop":
        _stop(args)
    elif args.command == "reset-admin-password":
        _reset_password(getattr(args, "username", "admin"), args.password)
    elif args.command == "reset-password":
        _reset_password(args.username, args.password)
    elif args.command == "node-agent":
        _node_agent(args)
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
    elif args.command == "filebox":
        _filebox(args)
    else:
        parser.print_help()
        sys.exit(1)




def _serve(args) -> None:
    """Start the FastAPI server."""
    import os
    import uvicorn
    from thinkdome.core.config import get_settings

    pid = os.getpid()
    storage_dir = Path(get_settings().FILE_STORAGE_DIR)
    storage_dir.mkdir(parents=True, exist_ok=True)
    pid_file = storage_dir / "thinkdome.pid"

    try:
        pid_file.write_text(str(pid), encoding="utf-8")
    except Exception:
        pass

    print(f"Starting ThinkDome API server on {args.host}:{args.port} (PID: {pid})")
    try:
        uvicorn.run(
            "thinkdome.api.server:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
            reload_dirs=["thinkdome"] if args.reload else None,
            workers=args.workers,
        )
    finally:
        if pid_file.exists():
            try:
                pid_file.unlink()
            except Exception:
                pass


def _stop(args) -> None:
    """Stop running ThinkDome server process gracefully (SIGTERM) or forcefully (SIGKILL)."""
    import os
    import signal
    import time
    from thinkdome.core.config import get_settings

    storage_dir = Path(get_settings().FILE_STORAGE_DIR)
    pid_file = storage_dir / "thinkdome.pid"
    pids_to_kill: set[int] = set()

    if pid_file.exists():
        try:
            pid_str = pid_file.read_text(encoding="utf-8").strip()
            if pid_str.isdigit():
                pids_to_kill.add(int(pid_str))
        except Exception:
            pass

    # Inspect process list in /proc to find active ThinkDome server processes
    try:
        my_pid = os.getpid()
        for proc_dir in Path("/proc").glob("[0-9]*"):
            try:
                cmdline = (proc_dir / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="ignore")
                if "thinkdome" in cmdline and "serve" in cmdline and str(my_pid) not in cmdline:
                    pids_to_kill.add(int(proc_dir.name))
            except Exception:
                continue
    except Exception:
        pass

    if not pids_to_kill:
        print("No active ThinkDome server process found.")
        return

    force = getattr(args, "force", False)
    sig = signal.SIGKILL if force else signal.SIGTERM
    sig_name = "SIGKILL (forceful)" if force else "SIGTERM (graceful)"

    stopped_count = 0
    for pid in pids_to_kill:
        try:
            print(f"Sending {sig_name} to ThinkDome server process (PID: {pid})...")
            os.kill(pid, sig)
            stopped_count += 1
            if not force:
                for _ in range(10):
                    time.sleep(0.2)
                    try:
                        os.kill(pid, 0)
                    except OSError:
                        break
        except ProcessLookupError:
            print(f"Process {pid} is no longer running.")
        except Exception as e:
            print(f"Failed to signal PID {pid}: {e}", file=sys.stderr)

    if pid_file.exists():
        try:
            pid_file.unlink()
        except Exception:
            pass

    print(f"✓ ThinkDome stop command finished ({stopped_count} process(es) signaled).")


def _reset_password(username: str | None, password: str | None) -> None:
    """Reset password for administrator or specified user account across auth databases."""
    import getpass
    import hashlib
    import secrets
    from thinkdome.core.config import get_settings
    from thinkdome.platform.database.service import DatabaseService
    from thinkdome.security.auth.service import AuthService
    from thinkdome.security.rbac.models import User

    target_user = (username or "admin").strip().lower()
    if not password:
        password = getpass.getpass(f"Enter new password for user '{target_user}': ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Error: Passwords do not match.", file=sys.stderr)
            sys.exit(1)

    if len(password) < 6:
        print("Error: Password must be at least 6 characters long.", file=sys.stderr)
        sys.exit(1)

    settings = get_settings()
    db_svc = DatabaseService(settings)
    auth_svc = AuthService(settings, db_svc)

    # 1. Update SQLite AuthService users table
    salt = secrets.token_hex(16)
    hashed_password = auth_svc._hash_password(password, salt)

    existing = db_svc.fetch_one("SELECT username FROM users WHERE username = ?", (target_user,))
    if existing:
        db_svc.execute(
            "UPDATE users SET hashed_password = ?, salt = ? WHERE username = ?",
            (hashed_password, salt, target_user)
        )
    else:
        auth_svc.register(target_user, password, role="ADMIN")

    # If resetting admin user, also update 'administrator' / 'admin' alias
    if target_user in ("admin", "administrator"):
        alt_user = "administrator" if target_user == "admin" else "admin"
        alt_existing = db_svc.fetch_one("SELECT username FROM users WHERE username = ?", (alt_user,))
        if alt_existing:
            alt_salt = secrets.token_hex(16)
            alt_hashed = auth_svc._hash_password(password, alt_salt)
            db_svc.execute(
                "UPDATE users SET hashed_password = ?, salt = ? WHERE username = ?",
                (alt_hashed, alt_salt, alt_user)
            )

    # 2. Update Custom ORM User model
    try:
        from thinkdome.core.cli.site_ops import _init_kernel_for_site
        site_name = os.environ.get("THINKDOME_SITE", "think.local")
        _init_kernel_for_site(site_name)

        orm_user = User.query().filter(username=target_user).first()
        if not orm_user and target_user in ("admin", "administrator"):
            orm_user = User.query().filter(username="administrator").first() or User.query().filter(username="admin").first()

        if orm_user:
            orm_user.password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
            orm_user.save()
    except Exception:
        pass

    print(f"✓ Password updated successfully for user '{target_user}'.")


def _node_agent(args) -> None:
    """Start the private node-local MicroVM agent."""
    import uvicorn
    from thinkdome.core.config import Settings
    from thinkdome.control_plane.node_server import create_node_app

    settings = Settings()
    tls = settings.node_tls_config()
    uvicorn.run(
        create_node_app(settings),
        host=args.host or settings.NODE_AGENT_HOST,
        port=args.port or settings.NODE_AGENT_PORT,
        **tls,
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
            if result.error_code:
                print(f"[{result.error_code}]", file=sys.stderr)
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


def _filebox(args) -> None:
    """Manage AI agent Filebox persistent filesystem."""
    import os
    import sys
    from thinkdome.core.config import get_settings, get_workspace_root
    from thinkdome.filebox import bootstrap, Filebox, FileboxMigrator

    if not getattr(args, "filebox_action", None):
        print("Usage: thinkdome filebox <init|status|verify|index|tree|search|migrate> [options]")
        sys.exit(1)

    action = args.filebox_action
    root_str = getattr(args, "root", None)
    if not root_str:
        if os.environ.get("FILEBOX_ROOT"):
            root_path = Path(os.environ["FILEBOX_ROOT"])
        else:
            storage_dir = Path(get_settings().FILE_STORAGE_DIR)
            if not storage_dir.is_absolute():
                storage_dir = get_workspace_root() / storage_dir
            tenant = getattr(args, "tenant", "default") or "default"
            agent_id = getattr(args, "agent_id", None) or getattr(args, "user", None) or "agent-001"
            root_path = storage_dir / "filebox_data" / tenant / agent_id
    else:
        root_path = Path(root_str).resolve()

    if action == "init":
        agent_id = getattr(args, "agent_id", "agent-001")
        force = getattr(args, "force", False)
        print(f"Bootstrapping Filebox at: {root_path}")
        fb = bootstrap.init(root_path, agent_id=agent_id, force=force)
        print(f"✓ Initialized Filebox (agent: {fb.agent_id}, version: {fb.version})")
        print(f"  Root: {root_path}")

    elif action == "status":
        if not root_path.exists():
            print(f"✘ Filebox not found at: {root_path}")
            sys.exit(1)
        fb = Filebox(root_path)
        v = bootstrap.verify(root_path)
        files = list(root_path.rglob("*"))
        file_count = sum(1 for f in files if f.is_file())
        dir_count = sum(1 for f in files if f.is_dir())
        total_size = sum(f.stat().st_size for f in files if f.is_file())

        print("=" * 60)
        print(" 📦 ThinkDome Filebox Status")
        print("=" * 60)
        print(f"  Root:         {root_path}")
        print(f"  Valid:        {'✓ Yes' if v['valid'] else '✘ Issues detected'}")
        print(f"  Directories:  {dir_count}")
        print(f"  Files:        {file_count}")
        print(f"  Total Size:   {total_size:,} bytes ({total_size / (1024*1024):.2f} MB)")
        print(f"  FTS Index:    {'✓ Ready' if fb.search_engine.is_index_ready() else 'Not built (run `thinkdome filebox index`)'}")
        if v["issues"]:
            print("\n  Issues:")
            for issue in v["issues"]:
                print(f"    - {issue}")

    elif action == "verify":
        if not root_path.exists():
            print(f"✘ Filebox not found at: {root_path}")
            sys.exit(1)
        v = bootstrap.verify(root_path)
        if v["valid"]:
            print(f"✓ Filebox structure and manifest valid at {root_path}")
        else:
            print(f"✘ Filebox verification failed at {root_path}:")
            for issue in v["issues"]:
                print(f"  - {issue}")
            sys.exit(1)

    elif action == "index":
        if not root_path.exists():
            print(f"✘ Filebox not found at: {root_path}")
            sys.exit(1)
        fb = Filebox(root_path)
        force = getattr(args, "force", False)
        print(f"Building SQLite FTS5 search index for {root_path} (force={force})...")
        res = fb.build_index(force=force)
        print(f"✓ Index complete: {res['indexed']} indexed, {res['updated']} updated, {res['deleted']} deleted (total: {res['total']})")

    elif action == "tree":
        if not root_path.exists():
            print(f"✘ Filebox not found at: {root_path}")
            sys.exit(1)
        fb = Filebox(root_path)
        depth = getattr(args, "depth", 3)
        tree_node = fb.tree("", depth=depth)

        def print_tree(node, prefix=""):
            icon = "📁 " if node.type == "directory" else "📄 "
            size_str = f" ({node.size} bytes)" if node.type == "file" else ""
            print(f"{prefix}{icon}{node.name}{size_str}")
            if node.children:
                for idx, child in enumerate(node.children):
                    is_last = (idx == len(node.children) - 1)
                    sub_prefix = prefix + ("    " if is_last else "│   ")
                    print_tree(child, sub_prefix)

        print(f"Tree for {root_path} (depth={depth}):")
        print_tree(tree_node)

    elif action == "search":
        if not root_path.exists():
            print(f"✘ Filebox not found at: {root_path}")
            sys.exit(1)
        fb = Filebox(root_path)
        query = args.query
        results = fb.search(query)
        print(f"Search results for '{query}' in {root_path} ({len(results)} found):")
        for r in results:
            cat = f"[{r.get('category')}] " if r.get("category") else ""
            print(f"\n  • {cat}{r['path']}")
            if "snippet" in r:
                print(f"    {r['snippet']}")
            elif "matches" in r:
                for m in r["matches"][:3]:
                    print(f"    Line {m['line']}: {m['text']}")

    elif action == "migrate":
        migrator = FileboxMigrator()
        source_dir = getattr(args, "source", None)
        target_dir = getattr(args, "target", None) or str(root_path)
        dry_run = getattr(args, "dry_run", False)

        print(f"Running Filebox migration (dry_run={dry_run})...")
        if source_dir:
            print(f"Source: {source_dir} -> Target: {target_dir}")
            report = migrator.migrate_directory(source_dir, target_dir, dry_run=dry_run)
            _print_migration_report(report)
        else:
            tenant = getattr(args, "tenant", "default")
            user = getattr(args, "user", None)
            print(f"Migrating legacy platform storage: tenant={tenant}, user={user or 'all'}")
            reports = migrator.migrate_legacy_storage(tenant_id=tenant, owner_id=user, dry_run=dry_run)
            if not reports:
                print("No legacy storage volumes found to migrate.")
            for rep in reports:
                _print_migration_report(rep)


def _print_migration_report(report) -> None:
    print("-" * 60)
    print(f" Migration Report: {report.status.upper()}")
    print(f" Source:            {report.source}")
    print(f" Target:            {report.target}")
    print(f" Files copied:      {len(report.files_copied)}")
    print(f" Files transformed: {len(report.files_transformed)}")
    print(f" Warnings:          {len(report.warnings)}")
    print(f" Errors:            {len(report.errors)}")
    for w in report.warnings:
        print(f"   ! {w}")
    for e in report.errors:
        print(f"   ✘ {e}")


if __name__ == "__main__":
    main()
