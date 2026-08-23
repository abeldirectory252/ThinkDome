"""ThinkDome Application Kernel.

Coordinates multi-tenant site configurations, boots plugins and installed apps,
initializes site-specific database sessions, and aggregates hooks/event listeners.
"""

from __future__ import annotations

import os
import json
import importlib
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

from thinkdome.core.config import get_workspace_root

WORKSPACE_ROOT = get_workspace_root()
SITES_DIR = WORKSPACE_ROOT / "sites"
APPS_DIR = WORKSPACE_ROOT / "thinkdome" / "apps"


class Kernel:
    """Core framework controller managing configuration, databases, apps, and events per site."""

    _instances: Dict[str, Kernel] = {}

    def __init__(self, site_name: str) -> None:
        self.site_name = site_name
        self.site_dir = SITES_DIR / site_name
        self.config_path = self.site_dir / "site_config.json"
        
        self.config: Dict[str, Any] = {}
        self.db_engine = None
        self.db_session_factory = None
        self.db: Optional[Session] = None
        
        # Registries
        self.hooks: Dict[str, List[Any]] = {}
        self.event_listeners: Dict[str, List[Any]] = {}
        self.models: Dict[str, Any] = {}
        self.apps: Dict[str, Any] = {}
        self.initialized = False

    @classmethod
    def get_instance(cls, site_name: str) -> Kernel:
        """Fetch or create Kernel singleton context for a specific site."""
        if site_name not in cls._instances:
            cls._instances[site_name] = cls(site_name)
        return cls._instances[site_name]

    @classmethod
    def current(cls) -> Kernel:
        """Get Kernel instance corresponding to THINKDOME_SITE env var."""
        site_name = os.environ.get("THINKDOME_SITE", "think.local")
        return cls.get_instance(site_name)

    def initialize(self) -> None:
        """Initialize configurations, database connections, and load all registered apps."""
        if self.initialized:
            return

        self._load_config()
        self._init_database()
        self._load_apps()
        self.initialized = True
        logger.info(f"✓ Kernel successfully booted for site: {self.site_name}")

    def _load_config(self) -> None:
        """Load site_config.json from site directory."""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found for site '{self.site_name}' at {self.config_path}"
            )
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

    def _init_database(self) -> None:
        """Build SQLAlchemy connection pool for current site database context."""
        db_url = self.config.get("db_url")
        if not db_url:
            raise ValueError(f"db_url not specified in config for site '{self.site_name}'")

        # Create connection engine
        if db_url.startswith("sqlite"):
            self.db_engine = create_engine(
                db_url,
                connect_args={"check_same_thread": False, "timeout": 15},
            )
        else:
            self.db_engine = create_engine(
                db_url,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
            )

        self.db_session_factory = sessionmaker(bind=self.db_engine)
        self.db = self.db_session_factory()

        # Build schema using database metadata models dynamically loaded later
        from thinkdome.core.orm.orm import Base
        Base.metadata.create_all(self.db_engine)

    def _load_apps(self) -> None:
        """Discover and load each plugin app defined in installed_apps config."""
        installed = self.config.get("installed_apps", [])
        for app_name in installed:
            app_dir = APPS_DIR / app_name
            if not app_dir.exists():
                logger.warning(f"Skipping app '{app_name}': App folder not found at {app_dir}")
                continue

            # Load app manifest metadata
            manifest_path = app_dir / "app.json"
            if manifest_path.exists():
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            else:
                manifest = {"name": app_name}

            self.apps[app_name] = manifest

            # Load hooks and registers
            try:
                hooks_module = importlib.import_module(f"thinkdome.apps.{app_name}.hooks")
                app_hooks = getattr(hooks_module, "hooks", {})
                self._register_hooks(app_hooks)
            except ModuleNotFoundError:
                pass  # App has no custom hooks

            # Load tools
            try:
                importlib.import_module(f"thinkdome.apps.{app_name}.tools")
                logger.info(f"Successfully loaded tools for app '{app_name}'")
            except ModuleNotFoundError:
                pass  # App has no tools.py

    def _register_hooks(self, app_hooks: Dict[str, Any]) -> None:
        """Merge app-defined hook listeners into kernel registry."""
        for hook_name, callback in app_hooks.items():
            if isinstance(callback, list):
                self.hooks.setdefault(hook_name, []).extend(callback)
            else:
                self.hooks.setdefault(hook_name, []).append(callback)

    def get_installed_apps(self) -> List[str]:
        """Return list of active installed app names, dynamically refreshing from config."""
        try:
            self._load_config()
        except Exception:
            pass
        installed = self.config.get("installed_apps", [])
        for app_name in installed:
            if app_name not in self.apps:
                app_dir = APPS_DIR / app_name
                if app_dir.exists():
                    manifest_path = app_dir / "app.json"
                    if manifest_path.exists():
                        try:
                            with open(manifest_path, "r", encoding="utf-8") as f:
                                self.apps[app_name] = json.load(f)
                        except Exception:
                            self.apps[app_name] = {"name": app_name}
                    else:
                        self.apps[app_name] = {"name": app_name}
        return list(self.apps.keys())

    def close(self) -> None:
        """Gracefully release database sessions and dispose engines."""
        if self.db:
            try:
                self.db.close()
            except Exception:
                pass
            self.db = None
        if self.db_engine:
            try:
                self.db_engine.dispose()
            except Exception:
                pass
            self.db_engine = None
        self.initialized = False
