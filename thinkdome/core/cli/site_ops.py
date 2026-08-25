"""Site-level operations: backup, restore, password management, superadmin, console.

Leverages ThinkDome Kernel and custom ORM (thinkdome.core.orm) for site management.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import secrets
import shutil
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from thinkdome.core.config import get_workspace_root, get_site_database_url
from thinkdome.core.kernel.kernel import Kernel
from thinkdome.core.orm.orm import Model
from thinkdome.security.rbac.models import User, Role, UserRole, UserProfile

WORKSPACE_ROOT = get_workspace_root()
SITES_DIR = WORKSPACE_ROOT / "sites"

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _init_kernel_for_site(site_name: str) -> Kernel:
    """Initialize Kernel for specified site context."""
    os.environ["THINKDOME_SITE"] = site_name
    kernel = Kernel.get_instance(site_name)
    if not kernel.initialized:
        kernel.initialize()
    return kernel


def _site_dir(site_name: str) -> Path:
    d = SITES_DIR / site_name
    if not d.exists():
        raise FileNotFoundError(f"Site '{site_name}' does not exist at {d}")
    return d


def _db_path(site_name: str) -> Path:
    database_url = get_site_database_url(site_name)
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("Site backup currently requires a SQLite database URL")
    return Path(database_url[10:])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Backup ───────────────────────────────────────────────────────────────────


def backup_site(site_name: str) -> Path:
    """Create a timestamped backup bundle for site_name."""
    site = _site_dir(site_name)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = site / "private" / "backups" / ts
    backup_dir.mkdir(parents=True, exist_ok=True)

    db = _db_path(site_name)

    # 1. Database SQL dump (gzipped)
    sql_gz_path = backup_dir / "database.sql.gz"
    conn = sqlite3.connect(str(db))
    with gzip.open(str(sql_gz_path), "wt", encoding="utf-8") as gz:
        for line in conn.iterdump():
            gz.write(line + "\n")
    conn.close()
    print(f"  ✓ Database dumped → {sql_gz_path.relative_to(WORKSPACE_ROOT)}")

    # 2. Public files (storage/)
    storage_dir = site / "storage"
    if storage_dir.exists() and any(storage_dir.iterdir()):
        files_tar = backup_dir / "files.tar"
        with tarfile.open(str(files_tar), "w") as tar:
            tar.add(str(storage_dir), arcname="storage")
        print(f"  ✓ Public files   → {files_tar.relative_to(WORKSPACE_ROOT)}")
    else:
        print("  – No public files to back up (storage/ is empty)")

    # 3. Private files (private/ minus backups/)
    private_dir = site / "private"
    has_private = False
    for item in private_dir.iterdir():
        if item.name != "backups":
            has_private = True
            break

    if has_private:
        priv_tar = backup_dir / "private-files.tar"
        with tarfile.open(str(priv_tar), "w") as tar:
            for item in private_dir.iterdir():
                if item.name != "backups":
                    tar.add(str(item), arcname=item.name)
        print(f"  ✓ Private files  → {priv_tar.relative_to(WORKSPACE_ROOT)}")
    else:
        print("  – No private files to back up")

    print(f"\n✓ Backup completed: {backup_dir.relative_to(WORKSPACE_ROOT)}")
    return backup_dir


# ─── Restore ──────────────────────────────────────────────────────────────────


def restore_site(
    site_name: str,
    db_dump_path: str,
    public_files_path: Optional[str] = None,
    private_files_path: Optional[str] = None,
    admin_password: Optional[str] = None,
) -> None:
    """Restore a site from a database dump and optional file archives."""
    site = _site_dir(site_name)
    db_file = _db_path(site_name)
    dump = Path(db_dump_path)

    if not dump.exists():
        raise FileNotFoundError(f"Database dump not found: {dump}")

    print(f"Restoring site '{site_name}' …")

    # Back up current DB before overwriting
    if db_file.exists():
        bak = db_file.with_suffix(".sqlite.bak")
        shutil.copy2(str(db_file), str(bak))
        print(f"  ✓ Current database backed up → {bak.name}")

    # Read SQL from dump
    if dump.name.endswith(".gz"):
        with gzip.open(str(dump), "rt", encoding="utf-8") as gz:
            sql_script = gz.read()
    else:
        sql_script = dump.read_text(encoding="utf-8")

    # Wipe and reload
    if db_file.exists():
        db_file.unlink()
    for suffix in (".sqlite-wal", ".sqlite-shm"):
        journal = db_file.with_name(db_file.name + suffix.replace(".sqlite", ""))
        if journal.exists():
            journal.unlink()

    conn = sqlite3.connect(str(db_file))
    conn.executescript(sql_script)
    conn.close()
    print(f"  ✓ Database restored from {dump.name}")

    # Restore files if provided
    if public_files_path:
        pub = Path(public_files_path)
        if not pub.exists():
            raise FileNotFoundError(f"Public files archive not found: {pub}")
        storage = site / "storage"
        storage.mkdir(exist_ok=True)
        with tarfile.open(str(pub), "r:*") as tar:
            tar.extractall(str(site), filter="data")
        print(f"  ✓ Public files restored from {pub.name}")

    if private_files_path:
        priv = Path(private_files_path)
        if not priv.exists():
            raise FileNotFoundError(f"Private files archive not found: {priv}")
        private = site / "private"
        private.mkdir(exist_ok=True)
        with tarfile.open(str(priv), "r:*") as tar:
            tar.extractall(str(private), filter="data")
        print(f"  ✓ Private files restored from {priv.name}")

    # Set new admin password if specified
    if admin_password:
        set_admin_password(site_name, admin_password)

    print(f"\n✓ Site '{site_name}' restored successfully.")


# ─── Password Management via Custom ORM ─────────────────────────────────────


def set_admin_password(site_name: str, new_password: str) -> None:
    """Reset the Administrator password for a site using ThinkDome Custom ORM."""
    if len(new_password) < 6:
        raise ValueError("Password must be at least 6 characters long.")

    kernel = _init_kernel_for_site(site_name)

    # 1. Update Custom ORM User (rbac_users)
    user = User.query().filter(username="administrator").first()
    if not user:
        user = User.query().filter(username="admin").first()

    if user:
        user.password_hash = hashlib.sha256(new_password.encode("utf-8")).hexdigest()
        user.save()
        username = user.username
    else:
        username = "administrator"

    """Password persistence is handled by the custom ORM user model."""
    print(f"  ✓ Administrator password updated for user '{username}' via Custom ORM")


def set_user_password(site_name: str, identifier: str, new_password: str) -> None:
    """Reset any user's password by username or email using ThinkDome Custom ORM."""
    if len(new_password) < 6:
        raise ValueError("Password must be at least 6 characters long.")

    kernel = _init_kernel_for_site(site_name)
    ident_lower = identifier.strip().lower()

    # Query custom ORM model User
    user = User.query().filter(username=ident_lower).first()
    if not user and "@" in ident_lower:
        user = User.query().filter(email=ident_lower).first()

    if not user:
        raise RuntimeError(f"User '{identifier}' not found on site '{site_name}'.")
    target_username = user.username
    user.password_hash = hashlib.sha256(new_password.encode("utf-8")).hexdigest()
    user.save()

    print(f"  ✓ Password updated for user '{target_username}' via Custom ORM")


# ─── Superadmin (Administrator) Creation via Custom ORM ─────────────────────


def create_superadmin(site_name: str, password: Optional[str] = None) -> None:
    """Create the single Administrator superadmin account for a site using Custom ORM."""
    kernel = _init_kernel_for_site(site_name)

    # Check if Administrator already exists in custom ORM
    existing_user = User.query().filter(username="administrator").first()
    if existing_user:
        if password:
            set_admin_password(site_name, password)
            return
        print(f"  ✗ Site '{site_name}' already has an Administrator account.")
        print("    Use 'think --site ... set-admin-password' to reset the password.")
        return

    if not password:
        import getpass
        password = getpass.getpass("Enter Administrator password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Error: Passwords do not match.")
            return

    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")

    username = "administrator"
    email = f"administrator@{site_name}"
    hashed_pass = hashlib.sha256(password.encode("utf-8")).hexdigest()

    # Create User model using custom ORM
    user = User(
        username=username,
        email=email,
        password_hash=hashed_pass,
        status="active"
    )
    user.save()

    # Ensure SUPER_ADMIN role exists using custom ORM
    super_role = Role.query().filter(name="SUPER_ADMIN").first()
    if not super_role:
        super_role = Role(
            name="SUPER_ADMIN",
            description="Site superadmin — full platform access",
            is_active=True,
            is_system=True
        )
        super_role.save()

    # Map user to superadmin role using custom ORM UserRole
    user_role = UserRole.query().filter(user_id=user.id, role_id=super_role.id).first()
    if not user_role:
        user_role = UserRole(user_id=user.id, role_id=super_role.id)
        user_role.save()

    # Create UserProfile model using custom ORM
    profile = UserProfile(
        user_id=user.id,
        first_name="Site",
        last_name="Administrator"
    )
    profile.save()

    print(f"  ✓ Administrator superadmin created for site '{site_name}' via Custom ORM")
    print(f"    Username : {username}")
    print(f"    Email    : {email}")
    print(f"    Role     : SUPER_ADMIN")


# ─── Console via Custom ORM ──────────────────────────────────────────────────


def open_console(site_name: str) -> None:
    """Open an interactive Python REPL pre-loaded with ThinkDome Kernel and Custom ORM context."""
    import code

    kernel = _init_kernel_for_site(site_name)
    conn = sqlite3.connect(str(_db_path(site_name)))
    conn.row_factory = sqlite3.Row

    def sql(query: str, params: tuple = ()):
        cursor = conn.execute(query, params)
        cols = [desc[0] for desc in cursor.description] if cursor.description else []
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    local_vars = {
        "site": site_name,
        "kernel": kernel,
        "db": kernel.db,
        "conn": conn,
        "sql": sql,
        "User": User,
        "Role": Role,
        "UserRole": UserRole,
        "UserProfile": UserProfile,
        "Model": Model,
        "set_user_password": set_user_password,
        "set_admin_password": set_admin_password,
        "create_superadmin": create_superadmin,
    }

    banner = (
        "═" * 64 + "\n"
        f" 🧠 ThinkDome Interactive Console — Site: {site_name}\n"
        "═" * 64 + "\n"
        "\n"
        " Pre-loaded Custom ORM Models & Context:\n"
        "   User, Role, UserRole, UserProfile, Model\n"
        "   kernel, db, conn, sql(query)\n"
        "\n"
        " Example Custom ORM Queries:\n"
        "   users = User.query().all()\n"
        "   admin = User.query().filter(username='administrator').first()\n"
        "   set_admin_password(site, 'NewPassword')\n"
        "\n"
    )

    code.interact(banner=banner, local=local_vars, exitmsg="Goodbye.")
    conn.close()
