"""ThinkDome Package and Application Manager.

Handles source retrieval via Git, metadata verification, version validation,
dependency tree resolution, symlink linking, and registry updates.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from thinkdome.core.config import get_workspace_root

WORKSPACE_ROOT = get_workspace_root()
SITES_DIR = WORKSPACE_ROOT / "sites"
COMMON_APPS_JSON = SITES_DIR / "common" / "apps.json"
APPS_DIR = WORKSPACE_ROOT / "thinkdome" / "apps"


# ── Metadata Schema Validator ─────────────────────────────────────────────────

def validate_app_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Load and validate app.json fields for strict schema compliance."""
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing app.json manifest at {manifest_path}")

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise ValueError(f"Malformed JSON in manifest: {e}")

    # Required fields
    required = ["name", "version"]
    for field in required:
        if field not in data:
            raise ValueError(f"App manifest missing required field: {field}")

    return data


# ── Dependency Resolver ───────────────────────────────────────────────────────

def parse_version_specifier(spec: str) -> Tuple[str, str]:
    """Split comparison operator from target version (e.g. '>=2.0' -> ('>=', '2.0'))."""
    for op in [">=", "<=", "==", ">", "<"]:
        if spec.startswith(op):
            return op, spec[len(op):].strip()
    return "==", spec.strip()


def compare_versions(current: str, required: str, op: str) -> bool:
    """Evaluate simple semantic version comparisons."""
    try:
        cur_parts = [int(x) for x in current.split(".")]
        req_parts = [int(x) for x in required.split(".")]
        
        # Normalize lengths
        max_len = max(len(cur_parts), len(req_parts))
        cur_parts += [0] * (max_len - len(cur_parts))
        req_parts += [0] * (max_len - len(req_parts))

        if op == "==":
            return cur_parts == req_parts
        elif op == ">=":
            return cur_parts >= req_parts
        elif op == "<=":
            return cur_parts <= req_parts
        elif op == ">":
            return cur_parts > req_parts
        elif op == "<":
            return cur_parts < req_parts
    except Exception:
        # Fallback to direct string match if parsing fails
        return current == required
    return False


def resolve_dependencies(manifest: Dict[str, Any], registry: List[Dict[str, Any]]) -> None:
    """Check that all required dependency versions are met in the active registry."""
    dependencies = manifest.get("dependencies", [])
    installed_map = {item["name"]: item["version"] for item in registry}

    for dep in dependencies:
        if isinstance(dep, str):
            dep_name = dep
            dep_ver_req = None
        elif isinstance(dep, dict):
            dep_name = dep.get("name")
            dep_ver_req = dep.get("version")
        else:
            continue

        # Check if installed
        if dep_name == "core":
            continue  # The framework core is always present

        if dep_name not in installed_map:
            raise ValueError(f"Missing dependency: App requires '{dep_name}' to be installed first.")

        if dep_ver_req:
            op, req_val = parse_version_specifier(dep_ver_req)
            cur_val = installed_map[dep_name]
            if not compare_versions(cur_val, req_val, op):
                raise ValueError(
                    f"Dependency version conflict: '{dep_name}' is version {cur_val}, "
                    f"but this app requires version {dep_ver_req}"
                )


# ── Git Repository Downloader ─────────────────────────────────────────────────

def clone_git_repo(
    source_url: str,
    target_dir: Path,
    branch: Optional[str] = None,
    version: Optional[str] = None,
    commit: Optional[str] = None,
) -> None:
    """Download source code from remote Git source using checkout tags."""
    if target_dir.exists():
        shutil.rmtree(target_dir)

    try:
        # Clone repository
        clone_cmd = ["git", "clone", source_url, str(target_dir)]
        subprocess.run(clone_cmd, check=True, capture_output=True)

        # Checkout specific version indicator if requested
        ref = branch or version or commit
        if ref:
            checkout_cmd = ["git", "checkout", ref]
            subprocess.run(checkout_cmd, cwd=str(target_dir), check=True, capture_output=True)
            logger.info(f"✓ Checked out Git reference: {ref}")
            
    except subprocess.CalledProcessError as e:
        # Clean up directory on error
        if target_dir.exists():
            shutil.rmtree(target_dir)
        raise RuntimeError(f"Git cloning failed: {e.stderr.decode('utf-8').strip()}")


# ── Registry Operations ───────────────────────────────────────────────────────

def get_common_registry() -> List[Dict[str, Any]]:
    """Retrieve list of registered apps from global apps.json registry."""
    if not COMMON_APPS_JSON.exists():
        COMMON_APPS_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(COMMON_APPS_JSON, "w", encoding="utf-8") as f:
            json.dump({"installed_apps": []}, f, indent=4)
        return []

    with open(COMMON_APPS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("installed_apps", [])


def save_common_registry(apps: List[Dict[str, Any]]) -> None:
    """Persist modified app records back to global apps.json registry."""
    with open(COMMON_APPS_JSON, "w", encoding="utf-8") as f:
        json.dump({"installed_apps": apps}, f, indent=4)


# ── App Manager Implementation ────────────────────────────────────────────────

class AppInstaller:
    """Lifecycle executor handling framework package installations, updates, and links."""

    @staticmethod
    def install(
        source: str,
        branch: Optional[str] = None,
        version: Optional[str] = None,
        commit: Optional[str] = None,
    ) -> str:
        """Download, check, and register an app into the active framework layout."""
        logger.info(f"Installing application from: {source}")

        # Define temporary workspace folder for downloads
        temp_dir = WORKSPACE_ROOT / "storage" / "temp_install"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

        # 1. Download application source
        is_git = source.startswith("http") or source.startswith("git@")
        is_local = os.path.exists(source)

        if is_git:
            clone_git_repo(source, temp_dir, branch, version, commit)
        elif is_local:
            shutil.copytree(source, temp_dir)
        else:
            raise ValueError(f"Unrecognized application source: {source}")

        # 2. Verify metadata
        manifest = validate_app_manifest(temp_dir / "app.json")
        app_name = manifest["name"]

        # 3. Resolve dependencies
        registry = get_common_registry()
        resolve_dependencies(manifest, registry)

        # 4. Copy to framework apps folder
        app_target_dir = APPS_DIR / app_name
        if app_target_dir.exists():
            shutil.rmtree(app_target_dir)
        shutil.copytree(temp_dir, app_target_dir)

        # Clean up temporary downloads
        shutil.rmtree(temp_dir)

        # 5. Register in common apps registry
        registry_map = {item["name"]: item for item in registry}
        registry_map[app_name] = {
            "name": app_name,
            "version": manifest["version"],
            "source": source,
            "enabled": True,
        }
        save_common_registry(list(registry_map.values()))

        # Register in the active site context if set
        site_name = os.environ.get("THINKDOME_SITE")
        if site_name:
            config_path = SITES_DIR / site_name / "site_config.json"
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    if app_name not in config.get("installed_apps", []):
                        config.setdefault("installed_apps", []).append(app_name)
                        with open(config_path, "w", encoding="utf-8") as f:
                            json.dump(config, f, indent=4)
                except Exception:
                    pass

        logger.info(f"✓ Application '{app_name}' successfully installed.")
        return app_name

    @staticmethod
    def uninstall(app_name: str) -> None:
        """Completely purge application package from system registry and filesystem."""
        logger.info(f"Uninstalling application: {app_name}")

        app_target_dir = APPS_DIR / app_name
        if app_target_dir.exists():
            # If it's a symlink, just remove the symlink
            if app_target_dir.is_symlink():
                app_target_dir.unlink()
            else:
                shutil.rmtree(app_target_dir)

        registry = get_common_registry()
        updated_registry = [item for item in registry if item["name"] != app_name]
        save_common_registry(updated_registry)

        # De-register from active site config if set
        site_name = os.environ.get("THINKDOME_SITE")
        if site_name:
            config_path = SITES_DIR / site_name / "site_config.json"
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    if app_name in config.get("installed_apps", []):
                        config["installed_apps"].remove(app_name)
                        with open(config_path, "w", encoding="utf-8") as f:
                            json.dump(config, f, indent=4)
                except Exception:
                    pass

        logger.info(f"✓ Application '{app_name}' successfully uninstalled.")

    @staticmethod
    def link(local_path: str) -> str:
        """Create a symlink pointing to a local development package."""
        source_dir = Path(local_path).resolve()
        if not source_dir.exists():
            raise FileNotFoundError(f"Local package source path not found: {source_dir}")

        manifest = validate_app_manifest(source_dir / "app.json")
        app_name = manifest["name"]

        app_target_dir = APPS_DIR / app_name
        if app_target_dir.exists():
            if app_target_dir.is_symlink():
                app_target_dir.unlink()
            else:
                shutil.rmtree(app_target_dir)

        # Create symlink
        os.symlink(source_dir, app_target_dir)
        logger.info(f"✓ Linked development app '{app_name}' -> {source_dir}")

        # Register in registry
        registry = get_common_registry()
        registry_map = {item["name"]: item for item in registry}
        registry_map[app_name] = {
            "name": app_name,
            "version": manifest["version"],
            "source": str(source_dir),
            "enabled": True,
            "linked": True,
        }
        save_common_registry(list(registry_map.values()))

        # Register in the active site context if set
        site_name = os.environ.get("THINKDOME_SITE")
        if site_name:
            config_path = SITES_DIR / site_name / "site_config.json"
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    if app_name not in config.get("installed_apps", []):
                        config.setdefault("installed_apps", []).append(app_name)
                        with open(config_path, "w", encoding="utf-8") as f:
                            json.dump(config, f, indent=4)
                except Exception:
                    pass

        return app_name
