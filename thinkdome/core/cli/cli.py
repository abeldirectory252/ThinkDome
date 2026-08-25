#!/usr/bin/env python3
"""ThinkDome Framework CLI.

Exposes commands to manage multi-tenant sites, register packages, run DB schema
migrations, execute background job loops, and manage execution sandboxes.
"""

from __future__ import annotations

import argparse
import os
import sys
import json
import shutil
import warnings
from pathlib import Path
from typing import List, Optional

from thinkdome.core.config import get_workspace_root

WORKSPACE_ROOT = get_workspace_root()
SITES_DIR = WORKSPACE_ROOT / "sites"
APPS_DIR = WORKSPACE_ROOT / "thinkdome" / "apps"

# Paramiko 2.x emits this warning while importing against modern
# cryptography. The project requires Paramiko 3.4+, but keep the CLI clean
# when a host-provided legacy Paramiko is discovered before dependencies are
# reinstalled. This narrowly targets the known deprecated TripleDES message.
warnings.filterwarnings(
    "ignore",
    message=r"TripleDES has been moved to cryptography\.hazmat\.decrepit.*",
    module=r"paramiko\..*",
)


def main() -> None:
    """Main framework CLI router."""
    parser = argparse.ArgumentParser(
        prog="think",
        description="ThinkDome Framework CLI - Sandbox Application OS",
    )
    parser.add_argument(
        "--site",
        default=os.environ.get("THINKDOME_SITE", "think.local"),
        help="Target site context (default: think.local)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # ── Site Management ───────────────────────────────────────────────────────
    create_site_p = subparsers.add_parser("create-site", help="Create a new multi-tenant site")
    create_site_p.add_argument("site_name", help="Name of the site to create")
    create_site_p.add_argument("--db-url", help="Database connection URL (defaults to SQLite)")

    # ── App Packaging Management ──────────────────────────────────────────────
    new_app_p = subparsers.add_parser("new-app", help="Scaffold a new application package")
    new_app_p.add_argument("app_name", help="Name of the application")

    install_app_p = subparsers.add_parser("install-app", help="Download and install an app package")
    install_app_p.add_argument("source", help="Source Git URL or local folder path")
    install_app_p.add_argument("--branch", help="Git branch to checkout")
    install_app_p.add_argument("--version", help="Version tag to checkout")
    install_app_p.add_argument("--commit", help="Commit hash to checkout")

    uninstall_app_p = subparsers.add_parser("uninstall-app", help="Completely remove an installed app")
    uninstall_app_p.add_argument("app_name", help="Name of the application to uninstall")

    link_app_p = subparsers.add_parser("link-app", help="Link local app directory for active development")
    link_app_p.add_argument("local_path", help="Local directory path containing app.json")

    subparsers.add_parser("list-apps", help="List all installed framework applications")

    app_info_p = subparsers.add_parser("app-info", help="Show manifest information for a registered app")
    app_info_p.add_argument("app_name", help="Name of the target app")

    enable_app_p = subparsers.add_parser("enable-app", help="Enable an installed application")
    enable_app_p.add_argument("app_name", help="Name of the application to enable")

    disable_app_p = subparsers.add_parser("disable-app", help="Disable an installed application")
    disable_app_p.add_argument("app_name", help="Name of the application to disable")

    update_app_p = subparsers.add_parser("update-app", help="Pull latest updates for installed app")
    update_app_p.add_argument("app_name", help="Name of the app to update")

    search_app_p = subparsers.add_parser("search-app", help="Search the marketplace for available apps")
    search_app_p.add_argument("query", help="Search query string")

    # ── Database Migration System ─────────────────────────────────────────────
    makemigrations_p = subparsers.add_parser("makemigrations", help="Create an application migration skeleton")
    makemigrations_p.add_argument("target_app", help="Application whose migration directory should be updated")
    makemigrations_p.add_argument("--name", required=True, help="Migration name, for example add_storage_quota")

    migrate_p = subparsers.add_parser("migrate", help="Run database migrations and schema sync")
    migrate_p.add_argument("target_app", nargs="?", help="Optional specific app to migrate")
    migrate_p.add_argument("--rollback", action="store_true", help="Rollback the last migration step")

    subparsers.add_parser("migration-status", help="Show applied status of all known migrations")

    # ── Process Workers & Execution ───────────────────────────────────────────
    serve_p = subparsers.add_parser("serve", help="Start the ThinkDome REST/WS application server")
    serve_p.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    serve_p.add_argument("--port", type=int, default=8000, help="Port to bind")
    serve_p.add_argument("--reload", action="store_true", help="Enable reload mode")

    subparsers.add_parser("worker", help="Start background queue worker")
    subparsers.add_parser("scheduler", help="Start cron scheduler process")
    subparsers.add_parser("shell", help="Open an interactive Python shell pre-loaded with site context")
    subparsers.add_parser("test", help="Run framework test suite")
    subparsers.add_parser("list-tools", help="List all registered tools and their active status")
    subparsers.add_parser("mcp", help="Start the Model Context Protocol (MCP) stdio server")

    # ── Backup & Restore ──────────────────────────────────────────────────────
    subparsers.add_parser("backup", help="Create a full backup of the site (database + files)")

    restore_p = subparsers.add_parser("restore", help="Restore a site from a database dump")
    restore_p.add_argument("db_dump", help="Path to .sql.gz or .sql database dump")
    restore_p.add_argument("--with-public-files", dest="public_files", help="Path to public files tar archive")
    restore_p.add_argument("--with-private-files", dest="private_files", help="Path to private files tar archive")
    restore_p.add_argument("--admin-password", dest="admin_password", help="Set a new Administrator password after restore")

    # ── Password Management ───────────────────────────────────────────────────
    admin_pw_p = subparsers.add_parser("set-admin-password", help="Reset the Administrator (superadmin) password")
    admin_pw_p.add_argument("password", help="New Administrator password")

    user_pw_p = subparsers.add_parser("set-password", help="Reset any user's password by username or email")
    user_pw_p.add_argument("identifier", help="Username or email address")
    user_pw_p.add_argument("password", help="New password")

    superadmin_p = subparsers.add_parser(
        "create-superadmin", help="Create or provision the Administrator account"
    )
    superadmin_p.add_argument(
        "--password",
        dest="password",
        help="Administrator password; if omitted, prompt securely",
    )

    filebox_p = subparsers.add_parser("create-filebox", help="Create an encrypted .box virtual disk for a user")
    filebox_p.add_argument("username", help="Owner username")
    filebox_p.add_argument("--tenant", default="default", help="Tenant identifier")
    filebox_p.add_argument("--rotate", action="store_true", help="Lock the existing volume and create a new one")

    # ── Console (interactive REPL) ────────────────────────────────────────────
    subparsers.add_parser("console", help="Open an interactive Python console with site context")

    # ── Code Execution ────────────────────────────────────────────────────────
    run_p = subparsers.add_parser("run", help="Execute code in the sandbox")
    run_p.add_argument("code", nargs="?", help="Code string to execute")
    run_p.add_argument("-f", "--file", help="Path to a script file to execute")
    run_p.add_argument("--timeout", type=int, default=10, help="Timeout in seconds")
    run_p.add_argument("--backend", default="auto", choices=["auto", "docker", "subprocess", "microvm"])

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    os.environ["THINKDOME_SITE"] = args.site

    try:
        if args.command == "run":
            handle_run(args.code, args.file, args.timeout, args.backend)
        elif args.command == "create-site":
            handle_create_site(args.site_name, args.db_url)
        elif args.command == "new-app":
            handle_new_app(args.app_name)
        elif args.command == "install-app":
            handle_install_app(args.site, args.source, args.branch, args.version, args.commit)
        elif args.command == "uninstall-app":
            handle_uninstall_app(args.site, args.app_name)
        elif args.command == "link-app":
            handle_link_app(args.site, args.local_path)
        elif args.command == "list-apps":
            handle_list_apps()
        elif args.command == "app-info":
            handle_app_info(args.app_name)
        elif args.command == "enable-app":
            handle_enable_app(args.site, args.app_name)
        elif args.command == "disable-app":
            handle_disable_app(args.site, args.app_name)
        elif args.command == "update-app":
            handle_update_app(args.site, args.app_name)
        elif args.command == "search-app":
            handle_search_app(args.query)
        elif args.command == "makemigrations":
            handle_makemigrations(args.site, args.target_app, args.name)
        elif args.command == "migrate":
            handle_migrate(args.site, args.target_app, args.rollback)
        elif args.command == "migration-status":
            handle_migration_status(args.site)
        elif args.command == "serve":
            handle_serve(args.host, args.port, args.reload)
        elif args.command == "worker":
            handle_worker(args.site)
        elif args.command == "scheduler":
            handle_scheduler(args.site)
        elif args.command == "shell":
            handle_shell(args.site)
        elif args.command == "test":
            handle_test()
        elif args.command == "list-tools":
            handle_list_tools(args.site)
        elif args.command == "mcp":
            handle_mcp(args.site)
        elif args.command == "backup":
            handle_backup(args.site)
        elif args.command == "restore":
            handle_restore(args.site, args.db_dump, args.public_files, args.private_files, args.admin_password)
        elif args.command == "set-admin-password":
            handle_set_admin_password(args.site, args.password)
        elif args.command == "set-password":
            handle_set_password(args.site, args.identifier, args.password)
        elif args.command == "console":
            handle_console(args.site)
        elif args.command == "create-superadmin":
            handle_create_superadmin(args.site, args.password)
        elif args.command == "create-filebox":
            handle_create_filebox(args.tenant, args.username, args.rotate)
        else:
            parser.print_help()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ── Handler Functions ─────────────────────────────────────────────────────────

def handle_create_site(site_name: str, db_url: Optional[str]) -> None:
    """Create directory structure and site_config.json for a new site."""
    site_dir = SITES_DIR / site_name
    if site_dir.exists():
        raise FileExistsError(f"Site '{site_name}' already exists at {site_dir}")

    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "storage").mkdir(exist_ok=True)
    (site_dir / "private").mkdir(exist_ok=True)

    config = {
        "db_url": db_url or f"sqlite:///{site_dir / 'storage' / 'thinkbox.db'}",
        "installed_apps": ["sandbox", "agents", "workflows", "monitoring"],
        "site_name": site_name,
        "created_at": time_now_iso(),
    }

    with open(site_dir / "site_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

    print(f"✓ Site '{site_name}' successfully created at {site_dir}")


def handle_new_app(app_name: str) -> None:
    """Scaffold a new application directory structure."""
    app_dir = APPS_DIR / app_name
    if app_dir.exists():
        raise FileExistsError(f"App '{app_name}' already exists at {app_dir}")

    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "backend").mkdir(exist_ok=True)
    (app_dir / "frontend").mkdir(exist_ok=True)
    (app_dir / "migrations").mkdir(exist_ok=True)

    manifest = {
        "name": app_name,
        "version": "1.0.0",
        "description": f"Custom plugin app for {app_name}",
        "dependencies": ["core"],
        "author": "anonymous",
        "license": "MIT"
    }

    with open(app_dir / "app.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4)

    with open(app_dir / "hooks.py", "w", encoding="utf-8") as f:
        f.write('"""App hook registration."""\n\nhooks = {}\n')

    print(f"✓ Application scaffold created successfully for '{app_name}'")


def handle_install_app(
    site_name: str,
    source: str,
    branch: Optional[str] = None,
    version: Optional[str] = None,
    commit: Optional[str] = None,
) -> None:
    """Install an app from Git/Local path, resolving dependencies, and updating registry."""
    from thinkdome.core.kernel.manager import AppInstaller

    # 1. Download and register application files
    app_name = AppInstaller.install(source, branch, version, commit)

    # 2. Append app to site's active config
    config_path = SITES_DIR / site_name / "site_config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        if app_name not in config.get("installed_apps", []):
            config.setdefault("installed_apps", []).append(app_name)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)

    # 3. Auto-trigger database migrations
    print("Running database migrations for installed app...")
    handle_migrate(site_name, app_name, rollback=False)
    print(f"\n✓ Application '{app_name}' installed successfully on site '{site_name}'")


def handle_uninstall_app(site_name: str, app_name: str) -> None:
    """Purge application package from framework and site config."""
    from thinkdome.core.kernel.manager import AppInstaller
    
    # 1. Remove files and registry entries
    AppInstaller.uninstall(app_name)

    # 2. Remove app from site's active config
    config_path = SITES_DIR / site_name / "site_config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        if app_name in config.get("installed_apps", []):
            config["installed_apps"].remove(app_name)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)

    print(f"✓ Application '{app_name}' uninstalled successfully.")


def handle_link_app(site_name: str, local_path: str) -> None:
    """Link local app for dev mode and add it to site config."""
    from thinkdome.core.kernel.manager import AppInstaller
    
    app_name = AppInstaller.link(local_path)
    
    config_path = SITES_DIR / site_name / "site_config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        if app_name not in config.get("installed_apps", []):
            config.setdefault("installed_apps", []).append(app_name)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
                
    print(f"✓ App '{app_name}' linked for development on site '{site_name}'.")


def handle_list_apps() -> None:
    """Print the contents of the installed apps registry."""
    from thinkdome.core.kernel.manager import get_common_registry
    
    registry = get_common_registry()
    if not registry:
        print("No applications currently installed.")
        return

    print("Installed Applications:")
    print("-" * 65)
    print(f"{'App Name':<20} | {'Version':<10} | {'Status':<10} | {'Source'}")
    print("-" * 65)
    for app in registry:
        status_str = "Enabled" if app.get("enabled", True) else "Disabled"
        if app.get("linked"):
            status_str += " (Linked)"
        print(f"{app['name']:<20} | {app['version']:<10} | {status_str:<10} | {app['source']}")


def handle_app_info(app_name: str) -> None:
    """Show details of the specified app manifest."""
    manifest_path = APPS_DIR / app_name / "app.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Application '{app_name}' is not installed.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    print(f"App Information: {app_name}")
    print("=" * 40)
    for k, v in manifest.items():
        print(f"{k.capitalize()}: {v}")


def handle_enable_app(site_name: str, app_name: str) -> None:
    """Activate an app on the specified site."""
    config_path = SITES_DIR / site_name / "site_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Site '{site_name}' config not found.")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    if app_name not in config.get("installed_apps", []):
        config.setdefault("installed_apps", []).append(app_name)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)

    # Update common registry status
    from thinkdome.core.kernel.manager import get_common_registry, save_common_registry
    registry = get_common_registry()
    for app in registry:
        if app["name"] == app_name:
            app["enabled"] = True
    save_common_registry(registry)

    print(f"✓ Enabled app '{app_name}' on site '{site_name}'")


def handle_disable_app(site_name: str, app_name: str) -> None:
    """Deactivate an app on the specified site."""
    config_path = SITES_DIR / site_name / "site_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Site '{site_name}' config not found.")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    if app_name in config.get("installed_apps", []):
        config["installed_apps"].remove(app_name)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)

    # Update common registry status
    from thinkdome.core.kernel.manager import get_common_registry, save_common_registry
    registry = get_common_registry()
    for app in registry:
        if app["name"] == app_name:
            app["enabled"] = False
    save_common_registry(registry)

    print(f"✓ Disabled app '{app_name}' on site '{site_name}'")


def handle_update_app(site_name: str, app_name: str) -> None:
    """Reinstall or fetch updates for the specified app."""
    from thinkdome.core.kernel.manager import get_common_registry
    
    registry = get_common_registry()
    target_app = next((app for app in registry if app["name"] == app_name), None)
    if not target_app:
        raise ValueError(f"App '{app_name}' is not installed.")

    print(f"Updating app '{app_name}' from source: {target_app['source']}...")
    handle_install_app(site_name, target_app["source"])


def handle_search_app(query: str) -> None:
    """Simulate searching the App Marketplace registry."""
    print(f"Searching App Marketplace for: '{query}'...")
    print("-" * 50)
    # Mock marketplace results matching query
    market_apps = [
        {"name": "crm", "version": "1.0.0", "desc": "Customer relation management flow"},
        {"name": "analytics", "version": "1.2.0", "desc": "Grafana-based monitoring tables"},
        {"name": "payments", "version": "2.1.0", "desc": "Stripe/PayPal ledger extensions"},
    ]
    matches = [a for a in market_apps if query.lower() in a["name"] or query.lower() in a["desc"]]
    if not matches:
        print("No matching applications found.")
        return

    for app in matches:
        print(f"{app['name']} (v{app['version']}) — {app['desc']}")


def handle_migrate(site_name: str, target_app: Optional[str] = None, rollback: bool = False) -> None:
    """Run pending DB migrations or rollbacks for installed apps."""
    from thinkdome.core.kernel.migrations import MigrationRunner
    
    runner = MigrationRunner(site_name)
    try:
        if rollback:
            runner.rollback(target_app)
            print(f"Migration rollback completed for {target_app or 'latest migration'}.")
        else:
            backup = runner.migrate(target_app)
            print(f"Migration completed successfully for {target_app or 'all applications' }.")
            if backup:
                print(f"Database backup: {backup}")
    except Exception as exc:
        print(f"Migration failed safely; database transaction was rolled back where supported: {exc}", file=sys.stderr)
        raise


def handle_makemigrations(site_name: str, target_app: str, name: str) -> None:
    """Generate a migration skeleton without changing the database."""
    from thinkdome.core.kernel.migrations import MigrationRunner

    runner = MigrationRunner(site_name)
    path = runner.make_migration(target_app, name)
    print(f"Created migration: {path}")
    print("Review and implement up()/down() before running 'think migrate'.")


def handle_migration_status(site_name: str) -> None:
    """Print the applied status of all app migrations."""
    from thinkdome.core.kernel.migrations import MigrationRunner
    
    runner = MigrationRunner(site_name)
    statuses = runner.status()
    if not statuses:
        print("No migrations found.")
        return

    print("Migration Status Report:")
    print("-" * 55)
    print(f"{'App Name':<20} | {'Migration Name':<20} | {'Status'}")
    print("-" * 55)
    for m in statuses:
        print(f"{m['app']:<20} | {m['migration']:<20} | {m['status']}")


def handle_run(code: Optional[str], file: Optional[str], timeout: int, backend: str) -> None:
    """Execute code in a sandbox."""
    from thinkdome import Sandbox
    from thinkdome.core.error_codes import classify_sandbox_error, present_sandbox_error

    if file:
        with open(file, "r", encoding="utf-8") as f:
            code = f.read()

    if not code:
        print("Error: Provide code as an argument or use --file", file=sys.stderr)
        sys.exit(1)

    try:
        with Sandbox(timeout=timeout, backend=backend) as dome:
            result = dome.run(code)
    except Exception as exc:
        code = classify_sandbox_error(exc)
        message = present_sandbox_error(exc, code)
        print(message if f"[{code}]" in message else f"Sandbox error [{code}]: {message}", file=sys.stderr)
        sys.exit(1)

    if result.output:
        print(result.output, end="")
    if result.error:
        code = classify_sandbox_error(result.error, result.error_code)
        message = present_sandbox_error(result.error, code)
        print(message if f"[{code}]" in message else f"Sandbox error [{code}]: {message}", file=sys.stderr)
    sys.exit(result.exit_code)


def handle_serve(host: str, port: int, reload: bool) -> None:
    """Launch the FastAPI server."""
    import uvicorn
    print(f"Launching ThinkDome serving gateway on {host}:{port}")
    uvicorn.run(
        "thinkdome.core.api.server:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=["thinkdome"] if reload else None,
    )


def handle_worker(site_name: str) -> None:
    """Run queue task processor worker."""
    print(f"Starting ThinkDome task worker for site '{site_name}'...")
    from thinkdome.core.queue.queue import QueueWorker
    worker = QueueWorker(site_name)
    worker.start()


def handle_scheduler(site_name: str) -> None:
    """Run cron scheduler loop."""
    print(f"Starting ThinkDome cron scheduler for site '{site_name}'...")
    from thinkdome.core.scheduler.scheduler import Scheduler
    scheduler = Scheduler(site_name)
    scheduler.start()


def handle_shell(site_name: str) -> None:
    """Launch an interactive pre-loaded python prompt."""
    import code
    from thinkdome.core.kernel.kernel import Kernel
    kernel = Kernel.get_instance(site_name)
    kernel.initialize()

    banner = (
        f"========================================================\n"
        f" ThinkDome Interactive Shell -- Context Site: {site_name}\n"
        f" Pre-loaded variables: kernel, db (session), site_config\n"
        f"========================================================"
    )
    local_vars = {
        "kernel": kernel,
        "db": kernel.db,
        "site_config": kernel.config,
    }
    code.interact(banner=banner, local=local_vars)


def handle_test() -> None:
    """Run the framework's test suite via pytest."""
    import subprocess
    subprocess.run(["pytest", str(WORKSPACE_ROOT / "tests")], check=True)


def handle_list_tools(site_name: str) -> None:
    """List all registered tools, their app source, description, scope, and status."""
    from thinkdome.platform.orchestration.tools import registry
    from thinkdome.core.kernel.kernel import Kernel

    # Initialize kernel to load apps and register tools
    kernel = Kernel.get_instance(site_name)
    kernel.initialize()

    active_tools = registry.get_active_tools(site_name)
    active_names = {t.name for t in active_tools}

    all_tools = registry.list_all_tools()
    
    if not all_tools:
        print("No tools registered.")
        return

    print(f"Registered Tools (Site Context: {site_name})")
    print("-" * 120)
    print(f"{'Tool Name':<20} | {'App / Source':<15} | {'Scope':<20} | {'Status':<10} | {'Description'}")
    print("-" * 120)
    for tool in sorted(all_tools, key=lambda t: t.name):
        status_str = "Active" if tool.name in active_names else "Inactive"
        print(f"{tool.name:<20} | {tool.app_name:<15} | {tool.required_scope:<20} | {status_str:<10} | {tool.description}")


def handle_mcp(site_name: str) -> None:
    """Start the Model Context Protocol (MCP) stdio server."""
    from thinkdome.platform.orchestration.mcp_server import run_mcp_server
    run_mcp_server(site_name)


# ── Backup & Restore Handlers ────────────────────────────────────────────────


def handle_backup(site_name: str) -> None:
    """Create a full site backup (database + files)."""
    from thinkdome.core.cli.site_ops import backup_site

    print(f"Creating backup for site '{site_name}' …")
    backup_site(site_name)


def handle_restore(
    site_name: str,
    db_dump: str,
    public_files: Optional[str],
    private_files: Optional[str],
    admin_password: Optional[str],
) -> None:
    """Restore a site from a database dump and optional file archives."""
    from thinkdome.core.cli.site_ops import restore_site

    restore_site(
        site_name,
        db_dump_path=db_dump,
        public_files_path=public_files,
        private_files_path=private_files,
        admin_password=admin_password,
    )


# ── Password Management Handlers ─────────────────────────────────────────────


def handle_set_admin_password(site_name: str, password: str) -> None:
    """Reset the Administrator password for a site."""
    from thinkdome.core.cli.site_ops import set_admin_password

    set_admin_password(site_name, password)


def handle_set_password(site_name: str, identifier: str, password: str) -> None:
    """Reset any user's password by username or email."""
    from thinkdome.core.cli.site_ops import set_user_password

    set_user_password(site_name, identifier, password)


# ── Console Handler ──────────────────────────────────────────────────────────


def handle_console(site_name: str) -> None:
    """Open an interactive Python console with site context."""
    from thinkdome.core.cli.site_ops import open_console

    open_console(site_name)


# ── Superadmin Handler ───────────────────────────────────────────────────────


def handle_create_superadmin(site_name: str, password: Optional[str] = None) -> None:
    """Create the single Administrator superadmin account for a site."""
    from thinkdome.core.cli.site_ops import create_superadmin

    create_superadmin(site_name, password)


def handle_create_filebox(tenant_id: str, username: str, rotate: bool = False) -> None:
    """Provision one encrypted single-file .box volume through the ORM."""
    from thinkdome.core.kernel.kernel import Kernel
    from thinkdome.platform.storage.filebox.models import FileBox, FileBoxVolume
    from thinkdome.platform.storage.filebox.service import FileBoxService
    from thinkdome.security.rbac.models import User

    owner = username.strip().lower()
    if not owner:
        raise ValueError("username is required")
    kernel = Kernel.current()
    kernel.initialize()
    user = User.query().filter(username=owner).first()
    if user is None:
        raise LookupError(f"User '{owner}' does not exist. Create the user before provisioning a FileBox.")
    if str(user.status).lower() != "active":
        raise PermissionError(f"User '{owner}' is not active (status: {user.status}).")
    existing = FileBoxVolume.query().filter(
        tenant_id=tenant_id, owner_id=owner, volume_name="default", status="active"
    ).first()
    owner_root = Path(FileBoxService().root) / tenant_id / owner
    disk_files = list(owner_root.glob("*.box")) if owner_root.exists() else []
    if disk_files and not existing and not rotate:
        raise FileExistsError(
            f"A .box file already exists for {tenant_id}/{owner}, but its metadata is not active. "
            "Use --rotate only after verifying recovery is intended."
        )
    if existing and not rotate:
        raise FileExistsError("An active FileBox already exists. Use --rotate to create a new disk.")
    if existing:
        existing._values["status"] = "locked"
        existing.save()
        for item in FileBox.query().filter(tenant_id=tenant_id, owner_id=owner, status="active").all():
            item._values["status"] = "expired"
            item.save()
    service = FileBoxService()
    service.ensure_layout(tenant_id=tenant_id, owner_id=owner)
    volume = service.get_volume(tenant_id=tenant_id, owner_id=owner)
    container = Path(volume.root_path).parent / (Path(volume.root_path).name[:-5] if Path(volume.root_path).name.endswith(".data") else Path(volume.root_path).name)
    print(f"✓ FileBox created for {tenant_id}/{owner}: {container}")


def time_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
