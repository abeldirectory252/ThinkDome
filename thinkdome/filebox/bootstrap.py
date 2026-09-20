"""Bootstrap a fresh Filebox directory tree with sensible defaults.

The ``init()`` function is idempotent — it can be called repeatedly
without destroying existing content.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from thinkdome.filebox.core import Filebox
from thinkdome.filebox.schemas import (
    FileboxManifest,
    MemoryIndex,
    PermissionRule,
    PermissionsConfig,
    SkillIndex,
    SkillMeta,
)

logger = logging.getLogger(__name__)

# ── Directory skeleton ──────────────────────────────────────────────────────

_DIRS = [
    "identity",
    "memory",
    "memory/archive",
    "skills",
    "skills/coding",
    "skills/coding/examples",
    "skills/coding/resources",
    "skills/research",
    "skills/writing",
    "knowledge",
    "knowledge/notes",
    "knowledge/documents",
    "knowledge/references",
    "models",
    "models/prompts",
    "models/checkpoints",
    "designs",
    "designs/architectures",
    "designs/workflows",
    "workspace",
    "workspace/projects",
    "workspace/drafts",
    "workspace/scratch",
    "state",
    "config",
    "logs",
]


# ── Default file content ───────────────────────────────────────────────────

def _default_manifest(root: str, agent_id: str) -> str:
    m = FileboxManifest(agent_id=agent_id, filebox_root=root)
    return yaml.dump(m.model_dump(), default_flow_style=False, sort_keys=False)


_AGENT_MD = """\
# Agent Identity

## Name
ThinkDome Agent

## Role
General-purpose AI assistant with persistent memory and skills.

## Personality
Professional, helpful, and thorough. Prefers clarity over brevity.
Admits uncertainty and asks for clarification when needed.
"""

_INSTRUCTIONS_MD = """\
# Global Instructions

## Core Principles
1. Always verify before making destructive changes.
2. Log important decisions to memory.
3. Follow the active project's instructions when working on a project.
4. Keep workspace/scratch clean — delete temporary files after use.

## Memory Protocol
- Record user preferences automatically.
- Note important decisions and their rationale.
- Consolidate session insights at the end of long sessions.
- Never store raw API responses or debug output in memory.
"""

_CORE_MEMORY_MD = """\
# Memory: Core

This file contains fundamental long-term memories.

---
"""

_PREFERENCES_MD = """\
# Memory: Preferences

User preferences discovered through interaction.

---
"""

_DEFAULT_PERMISSIONS = PermissionsConfig(
    rules=[
        PermissionRule(path="identity/**", access="read-only"),
        PermissionRule(path="config/permissions.yaml", access="read-only"),
        PermissionRule(path="filebox.yaml", access="system-only"),
        PermissionRule(path="logs/**", access="append-only"),
        PermissionRule(path="**/_index.json", access="system-only"),
        PermissionRule(path="memory/**", access="read-write"),
        PermissionRule(path="skills/**", access="read-write"),
        PermissionRule(path="knowledge/**", access="read-write"),
        PermissionRule(path="workspace/**", access="read-write"),
        PermissionRule(path="state/**", access="read-write"),
        PermissionRule(path="config/settings.yaml", access="read-write"),
    ],
    defaults={"access": "read-write"},
)

_SETTINGS_YAML = """\
# Filebox Settings
# User-configurable behaviour.

memory:
  auto_consolidate: true
  max_entries_per_topic: 200
  archive_after_days: 90

search:
  max_results: 50
  index_on_boot: false

workspace:
  auto_clean_scratch: true
  scratch_ttl_hours: 24
"""

_CODING_SKILL = """\
---
name: coding
version: "1.0"
description: Software development and code analysis
enabled: true
tags: [programming, software, development]
triggers: [code, program, implement, debug, fix, build]
---

# Coding

## When to Use
Use this skill when asked to write, review, debug, or analyse code.

## Workflow
1. Understand the requirements
2. Plan the approach
3. Write clean, documented code
4. Test the implementation
5. Review for edge cases

## Constraints
- Follow the project's existing code style
- Add docstrings to all public functions
- Include error handling
"""

_RESEARCH_SKILL = """\
---
name: research
version: "1.0"
description: Information gathering and analysis
enabled: true
tags: [research, analysis, investigation]
triggers: [research, investigate, find, look up, analyse]
---

# Research

## When to Use
Use when the user needs information gathered, compared, or analysed.

## Workflow
1. Clarify the research question
2. Identify reliable sources
3. Gather relevant information
4. Synthesise findings
5. Present with citations
"""

_WRITING_SKILL = """\
---
name: writing
version: "1.0"
description: Content creation and editing
enabled: true
tags: [writing, editing, content]
triggers: [write, draft, edit, compose, summarise]
---

# Writing

## When to Use
Use when asked to create, edit, or improve written content.

## Workflow
1. Understand the audience and purpose
2. Outline the structure
3. Write the first draft
4. Revise for clarity and tone
5. Proofread
"""

_SESSION_YAML = """\
session_id: ""
started_at: ""
active_project: ""
context_files: []
"""

_TASKS_YAML = """\
version: 1
tasks: []
"""

_MODEL_CONFIG_YAML = """\
model_id: "deepseek-coder-v2"
provider: "thinkdome-local"
context_window: 65536
temperature: 0.2
top_p: 0.95
quantization: "Q4_K_M"
system_instruction_ref: "models/prompts/system_prompt.md"
capabilities:
  - code_generation
  - tool_use
  - rag_search
"""

_MODEL_PROMPT_MD = """\
# Autonomous AI Agent System Prompt

## Role & Mission
You are ThinkDome Autonomous AI Engineer, executing resilient software engineering, model orchestration, and architectural design.

## Operating Principles
1. Verify before executing destructive commands.
2. Produce structured, typed, self-documenting code.
3. Adhere to RBAC and principle of least privilege.
"""

_AGENT_ARCHITECTURE_JSON = """\
{
  "system_name": "ThinkDome Agent Core",
  "version": "2.4.0",
  "architecture": {
    "orchestrator": "ThinkDome LLM Gateway",
    "memory_layer": "Persistent SQLite + Vector Chunks",
    "sandbox_runtime": "Isolated Container Runtime",
    "tool_protocol": "Model Context Protocol (MCP)"
  },
  "execution_flow": [
    "Prompt Ingestion",
    "Policy Enforcement",
    "DAG Resolution",
    "Tool Invocation",
    "Output Validation"
  ]
}
"""

_WORKFLOW_DAG_YAML = """\
name: "agent_code_generation_dag"
version: "1.0"
trigger: "user_task_request"
steps:
  - id: "analyze"
    action: "analyze_requirements"
    next: "plan"
  - id: "plan"
    action: "generate_implementation_plan"
    next: "execute"
  - id: "execute"
    action: "execute_sandboxed_code"
    next: "verify"
  - id: "verify"
    action: "run_test_suite"
"""



# ── Bootstrap entry point ──────────────────────────────────────────────────

def init(
    root: str | Path,
    *,
    agent_id: str = "default",
    force: bool = False,
) -> Filebox:
    """Create the Filebox directory tree and populate default files.

    This function is idempotent: existing files are not overwritten unless
    *force* is ``True``.

    Returns a ready-to-use :class:`Filebox` instance.
    """
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)

    def _write(rel: str, content: str) -> None:
        target = root_path / rel
        if target.exists() and not force:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    # Create directories.
    for d in _DIRS:
        (root_path / d).mkdir(parents=True, exist_ok=True)

    # Manifest.
    _write("filebox.yaml", _default_manifest(str(root_path), agent_id))

    # Identity.
    _write("identity/agent.md", _AGENT_MD)
    _write("identity/instructions.md", _INSTRUCTIONS_MD)

    # Memory.
    _write("memory/core.md", _CORE_MEMORY_MD)
    _write("memory/preferences.md", _PREFERENCES_MD)
    _write("memory/_index.json", MemoryIndex().model_dump_json(indent=2))

    # Skills.
    _write("skills/coding/SKILL.md", _CODING_SKILL)
    _write("skills/research/SKILL.md", _RESEARCH_SKILL)
    _write("skills/writing/SKILL.md", _WRITING_SKILL)
    _write(
        "skills/_index.json",
        SkillIndex(
            skills=[
                SkillMeta(name="coding", description="Software development and code analysis", tags=["programming"]),
                SkillMeta(name="research", description="Information gathering and analysis", tags=["research"]),
                SkillMeta(name="writing", description="Content creation and editing", tags=["writing"]),
            ]
        ).model_dump_json(indent=2),
    )

    # Config.
    perms_data = {
        "rules": [r.model_dump(mode="json") for r in _DEFAULT_PERMISSIONS.rules],
        "defaults": _DEFAULT_PERMISSIONS.defaults,
    }
    _write("config/permissions.yaml", yaml.dump(perms_data, default_flow_style=False))
    _write("config/settings.yaml", _SETTINGS_YAML)

    # State.
    _write("state/session.yaml", _SESSION_YAML)
    _write("state/tasks.yaml", _TASKS_YAML)

    # Models and Prompts
    _write("models/model_config.yaml", _MODEL_CONFIG_YAML)
    _write("models/prompts/system_prompt.md", _MODEL_PROMPT_MD)

    # Designs and Workflows
    _write("designs/agent_architecture.json", _AGENT_ARCHITECTURE_JSON)
    _write("designs/workflow_dag.yaml", _WORKFLOW_DAG_YAML)

    # Gitkeep placeholders.
    for placeholder in (
        "models/checkpoints/.gitkeep",
        "designs/architectures/.gitkeep",
        "designs/workflows/.gitkeep",
        "memory/archive/.gitkeep",
        "knowledge/notes/.gitkeep",
        "knowledge/documents/.gitkeep",
        "knowledge/references/.gitkeep",
        "workspace/projects/.gitkeep",
        "workspace/drafts/.gitkeep",
        "workspace/scratch/.gitkeep",
    ):
        _write(placeholder, "")

    logger.info("Filebox initialised at %s (agent: %s)", root_path, agent_id)
    return Filebox(root_path)


def verify(root: str | Path) -> dict:
    """Validate an existing Filebox structure.

    Returns a dict with ``valid`` (bool) and ``issues`` (list of strings).
    """
    root_path = Path(root).resolve()
    issues: list[str] = []

    if not root_path.exists():
        return {"valid": False, "issues": ["Root directory does not exist"]}

    if not (root_path / "filebox.yaml").exists():
        issues.append("Missing filebox.yaml manifest")

    for d in _DIRS:
        if not (root_path / d).exists():
            issues.append(f"Missing directory: {d}")

    required_files = [
        "identity/agent.md",
        "identity/instructions.md",
        "config/permissions.yaml",
        "config/settings.yaml",
        "memory/_index.json",
        "skills/_index.json",
    ]
    for f in required_files:
        if not (root_path / f).exists():
            issues.append(f"Missing required file: {f}")

    return {"valid": len(issues) == 0, "issues": issues}
