"""Filebox: AI Agent Persistent Filesystem.

Provides a structured, durable environment for agent memory, skills,
knowledge, projects, tasks, configuration, and audit logs.
"""

from thinkdome.filebox import bootstrap
from thinkdome.filebox.core import Filebox
from thinkdome.filebox.memory import FileboxMemory
from thinkdome.filebox.migration import FileboxMigrator, MigrationReport
from thinkdome.filebox.projects import FileboxProjects
from thinkdome.filebox.schemas import FileboxManifest
from thinkdome.filebox.search import FileboxSearch
from thinkdome.filebox.skills import FileboxSkills

__all__ = [
    "Filebox",
    "FileboxManifest",
    "FileboxMemory",
    "FileboxSkills",
    "FileboxProjects",
    "FileboxSearch",
    "FileboxMigrator",
    "MigrationReport",
    "bootstrap",
]
