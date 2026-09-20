"""Unit and integration tests for the Filebox architecture."""

from __future__ import annotations

import base64
import json
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thinkdome.filebox import (
    Filebox,
    FileboxManifest,
    FileboxMemory,
    FileboxMigrator,
    FileboxProjects,
    FileboxSearch,
    FileboxSkills,
    bootstrap,
)
from thinkdome.filebox.audit import AuditLogger
from thinkdome.filebox.permissions import PermissionChecker


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="filebox_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def bootstrapped_filebox(temp_dir):
    root = temp_dir / "agent_filebox"
    bootstrap.init(root, agent_id="test-agent-01")
    return Filebox(root, actor="test-user")


# ── Bootstrap & Verification ────────────────────────────────────────────────

def test_bootstrap_creates_all_standard_directories(temp_dir):
    root = temp_dir / "fb"
    manifest = bootstrap.init(root, agent_id="agent-xyz")

    assert root.exists()
    assert (root / "filebox.yaml").exists()
    assert manifest.agent_id == "agent-xyz"

    expected_dirs = [
        "identity", "memory", "memory/archive", "skills",
        "knowledge", "workspace", "workspace/projects",
        "workspace/drafts", "workspace/scratch", "state",
        "config", "logs",
    ]
    for ed in expected_dirs:
        assert (root / ed).is_dir(), f"Expected directory missing: {ed}"

    # Verify default files
    assert (root / "identity" / "agent.md").exists()
    assert (root / "identity" / "instructions.md").exists()
    assert (root / "memory" / "core.md").exists()
    assert (root / "memory" / "_index.json").exists()
    assert (root / "skills" / "_index.json").exists()
    assert (root / "config" / "permissions.yaml").exists()


def test_bootstrap_idempotency(temp_dir):
    root = temp_dir / "fb"
    bootstrap.init(root, agent_id="agent-1")

    # Add custom user file
    custom_file = root / "memory" / "custom.md"
    custom_file.write_text("# Custom Memory\nSome data", encoding="utf-8")

    # Re-run init without force
    bootstrap.init(root, agent_id="agent-1")
    assert custom_file.exists()
    assert "Some data" in custom_file.read_text(encoding="utf-8")


def test_verify_structure(bootstrapped_filebox):
    root = bootstrapped_filebox.root
    res = bootstrap.verify(root)
    assert res["valid"] is True
    assert len(res["issues"]) == 0

    # Tamper with structure (remove manifest)
    (root / "filebox.yaml").unlink()
    res2 = bootstrap.verify(root)
    assert res2["valid"] is False
    assert any("manifest" in i.lower() for i in res2["issues"])


# ── Core Operations & Permissions ───────────────────────────────────────────

def test_core_read_write_append(bootstrapped_filebox):
    fb = bootstrapped_filebox

    # Write in workspace
    fb.write("workspace/drafts/test.txt", "Hello Filebox!")
    assert fb.read_text("workspace/drafts/test.txt") == "Hello Filebox!"

    # Append
    fb.append("workspace/drafts/test.txt", "\nSecond line.")
    content = fb.read_text("workspace/drafts/test.txt")
    assert "Hello Filebox!" in content
    assert "Second line." in content

    # Stat
    st = fb.stat("workspace/drafts/test.txt")
    assert st["type"] == "file"
    assert st["size"] > 0

    # List
    items = fb.list("workspace/drafts")
    assert any(i["name"] == "test.txt" for i in items)

    # Delete
    deleted = fb.delete("workspace/drafts/test.txt")
    assert deleted is True
    assert not fb.exists("workspace/drafts/test.txt")


def test_path_traversal_prevention(bootstrapped_filebox):
    fb = bootstrapped_filebox

    with pytest.raises(PermissionError):
        fb.read("../../etc/passwd")

    with pytest.raises(PermissionError):
        fb.write("../escape.txt", "evil")

    with pytest.raises(PermissionError):
        fb.delete("../escape.txt")


def test_permission_model_enforcement(bootstrapped_filebox):
    fb = bootstrapped_filebox

    # 1. Read-only: identity/
    with pytest.raises(PermissionError):
        fb.write("identity/agent.md", "Modified identity")

    with pytest.raises(PermissionError):
        fb.delete("identity/instructions.md")

    # 2. System-only: filebox.yaml
    with pytest.raises(PermissionError):
        fb.write("filebox.yaml", "new: manifest")

    # System write is allowed
    fb.write("filebox.yaml", "version: '1.0'\nagent_id: system", system=True)

    # 3. Append-only: logs/
    fb.append("logs/audit.log", "Event 1\n")
    with pytest.raises(PermissionError):
        fb.delete("logs/audit.log")

    # 4. Read-write: workspace, memory, knowledge
    fb.write("workspace/scratch/temp.json", '{"ok": true}')
    assert fb.exists("workspace/scratch/temp.json")


def test_tree_generation(bootstrapped_filebox):
    fb = bootstrapped_filebox
    tree = fb.tree(depth=2)
    assert tree.type == "directory"
    child_names = [c.name for c in tree.children]
    assert "workspace" in child_names
    assert "memory" in child_names
    assert "skills" in child_names


# ── Semantic Memory API ─────────────────────────────────────────────────────

def test_semantic_memory_crud(bootstrapped_filebox):
    fb = bootstrapped_filebox
    mem = FileboxMemory(fb)

    # 1. Remember
    entry = mem.remember(
        content="User prefers dark mode and concise responses.",
        topic="preferences",
        title="UI and communication preferences",
        importance="high",
    )
    assert entry.id.startswith("mem-")
    assert entry.topic == "preferences"

    # 2. Recall
    results = mem.recall("dark mode")
    assert len(results) >= 1
    assert results[0].id == entry.id

    # 3. Recall all
    all_mem = mem.recall()
    assert len(all_mem) >= 1

    # 4. Update
    updated = mem.update(entry.id, "User prefers dark mode and very detailed code explanations.")
    assert updated is not None
    assert "detailed" in updated.content
    recalled = mem.recall("detailed")
    assert len(recalled) >= 1

    # 5. Archive
    archived = mem.archive(entry.id)
    assert archived is True
    # Archived entry should not show in normal recall
    assert len(mem.recall("dark mode")) == 0

    # 6. Forget
    entry2 = mem.remember("Temporary note to forget", topic="core")
    assert mem.forget(entry2.id) is True
    assert len(mem.recall("Temporary note")) == 0


# ── Skills API ──────────────────────────────────────────────────────────────

def test_skills_lifecycle(bootstrapped_filebox):
    fb = bootstrapped_filebox
    skills = FileboxSkills(fb)

    # Default skills loaded
    skill_list = skills.list_skills()
    skill_names = [s.name for s in skill_list]
    assert "coding" in skill_names
    assert "research" in skill_names

    # Load skill
    coding_md = skills.load_skill("coding")
    assert "coding" in coding_md.lower()

    # Create new skill
    new_skill = skills.create_skill(
        name="data-analysis",
        description="Analyze tabular data with pandas",
        instructions="# Data Analysis\n\nRun data analysis workflows.",
        tags=["pandas", "python"],
        triggers=["analyze", "csv", "data"],
    )
    assert new_skill.name == "data-analysis"
    assert fb.exists("skills/data-analysis/SKILL.md")

    # Disable skill
    assert skills.disable_skill("data-analysis") is True
    assert skills.get_skill("data-analysis").enabled is False


# ── Projects API ────────────────────────────────────────────────────────────

def test_projects_lifecycle(bootstrapped_filebox):
    fb = bootstrapped_filebox
    projects = FileboxProjects(fb)

    # Create project
    proj = projects.create_project(
        name="alpha-service",
        description="Autonomous background service",
        tags=["backend", "python"],
    )
    assert proj.name == "alpha-service"
    assert fb.exists("workspace/projects/alpha-service/PROJECT.md")
    assert fb.exists("workspace/projects/alpha-service/src")
    assert fb.exists("workspace/projects/alpha-service/docs")

    # List projects
    projs = projects.list_projects()
    assert any(p.name == "alpha-service" for p in projs)

    # Get project context
    ctx = projects.get_project_context("alpha-service")
    assert ctx["meta"]["name"] == "alpha-service"
    assert "project" in ctx

    # Archive project
    archived = projects.archive_project("alpha-service")
    assert archived is True
    opened = projects.open_project("alpha-service")
    assert opened.status == "archived"


# ── Search Engine (Grep & SQLite FTS5) ──────────────────────────────────────

def test_search_and_sqlite_fts5(bootstrapped_filebox):
    fb = bootstrapped_filebox
    search = fb.search_engine

    # Write searchable documents
    fb.write("knowledge/notes/ai_agents.md", "# AI Agents\nAutonomous agents utilize persistent filesystems for durable memory.")
    fb.write("workspace/drafts/plan.txt", "Phase 1: Build the agent sandbox runtime with tap networking.")

    # 1. Grep search (works immediately)
    grep_res = search.grep("autonomous")
    assert len(grep_res) >= 1
    assert any("ai_agents.md" in r["path"] for r in grep_res)

    # 2. Build FTS5 index
    idx_res = fb.build_index(force=True)
    assert idx_res["indexed"] > 0
    assert search.is_index_ready() is True

    # 3. Search via FTS5 index
    fts_res = search.search_index("autonomous")
    assert len(fts_res) >= 1
    assert "ai_agents.md" in fts_res[0]["path"]
    assert "<mark>" in fts_res[0]["snippet"]

    # 4. Unified search delegates cleanly
    unified = fb.search("sandbox")
    assert len(unified) >= 1


# ── Audit Logging ───────────────────────────────────────────────────────────

def test_audit_logging(bootstrapped_filebox):
    fb = bootstrapped_filebox
    audit = fb.audit

    # Perform mutations
    fb.write("workspace/scratch/audit_test.txt", "data", reason="Testing audit")
    fb.delete("workspace/scratch/audit_test.txt", reason="Cleanup test")

    events = audit.recent(limit=10)
    assert len(events) >= 2
    actions = [e.action for e in events]
    assert "write" in actions
    assert "delete" in actions


# ── Migration Engine ────────────────────────────────────────────────────────

def test_migration_from_legacy_sandbox(temp_dir):
    # Prepare old legacy sandbox layout
    old_sandbox = temp_dir / "old_sandbox"
    old_sandbox.mkdir(parents=True)

    # Flat legacy files
    (old_sandbox / "memory.md").write_text(
        "# Legacy Memory\n\n## User Preference\nUser prefers dark theme.\n", encoding="utf-8"
    )
    (old_sandbox / "context.md").write_text(
        "# Context\nSystem initialized for project Gamma.\n", encoding="utf-8"
    )

    old_skills = old_sandbox / "skills" / "coding"
    old_skills.mkdir(parents=True)
    (old_skills / "skill.md").write_text(
        "# Coding Skill\nWrite python 3.11 code.\n", encoding="utf-8"
    )

    old_workspace = old_sandbox / "workspace" / "projects" / "my-old-app"
    old_workspace.mkdir(parents=True)
    (old_workspace / "app.py").write_text("print('hello')", encoding="utf-8")

    # Run migration
    migrator = FileboxMigrator()
    target_fb = temp_dir / "new_filebox"

    report = migrator.migrate_directory(
        source_dir=old_sandbox,
        target_dir=target_fb,
        agent_id="migrated-agent",
        dry_run=False,
    )

    assert report.status == "success"
    assert len(report.errors) == 0

    # Verify target structure
    fb = Filebox(target_fb)
    assert (target_fb / "filebox.yaml").exists()

    # Memory migrated to core.md & preferences.md
    core_text = fb.read_text("memory/core.md")
    assert "User prefers dark theme" in core_text

    pref_text = fb.read_text("memory/preferences.md")
    assert "project Gamma" in pref_text

    # Memory index rebuilt
    mem_idx = json.loads(fb.read_text("memory/_index.json"))
    assert len(mem_idx["entries"]) > 0

    # Skill migrated to SKILL.md with frontmatter
    skill_text = fb.read_text("skills/coding/SKILL.md")
    assert "name: coding" in skill_text

    # Project preserved
    assert fb.exists("workspace/projects/my-old-app/app.py")


# ── Browse REST API ─────────────────────────────────────────────────────────

def test_browse_api_endpoints(temp_dir, monkeypatch):
    from thinkdome.api.server import create_app
    from thinkdome.core.config import get_settings

    # Route storage to temp_dir
    settings = get_settings()
    monkeypatch.setattr(settings, "FILE_STORAGE_DIR", str(temp_dir / "storage"))

    app = create_app()
    client = TestClient(app)

    # Mock user dependency
    from thinkdome.core.dependencies import get_current_user
    mock_user = {
        "username": "tester",
        "roles": ["DEVELOPER"],
        "tenant_id": "test-tenant",
    }
    app.dependency_overrides[get_current_user] = lambda: mock_user

    # 1. GET /v1/filebox/browse/status (triggers bootstrap)
    resp = client.get("/v1/filebox/browse/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["initialized"] is True
    assert data["valid"] is True

    # 2. GET /v1/filebox/browse/tree
    tree_resp = client.get("/v1/filebox/browse/tree?depth=3")
    assert tree_resp.status_code == 200
    assert tree_resp.json()["name"] in ("tester", "filebox")

    # 3. POST /v1/filebox/browse/write
    write_resp = client.post(
        "/v1/filebox/browse/write",
        json={"path": "workspace/drafts/api_doc.md", "content": "# API Documentation\nTested successfully."},
    )
    assert write_resp.status_code == 200

    # 4. GET /v1/filebox/browse/read
    read_resp = client.get("/v1/filebox/browse/read?path=workspace/drafts/api_doc.md")
    assert read_resp.status_code == 200
    assert "API Documentation" in read_resp.json()["content"]

    # 5. POST /v1/filebox/browse/search
    search_resp = client.post(
        "/v1/filebox/browse/search",
        json={"query": "Documentation"},
    )
    assert search_resp.status_code == 200
    assert search_resp.json()["total"] >= 1

    # 6. POST /v1/filebox/browse/delete
    del_resp = client.post(
        "/v1/filebox/browse/delete",
        json={"path": "workspace/drafts/api_doc.md"},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # 7. Multi-user perspective endpoint: GET /v1/filebox/browse/users
    users_resp = client.get("/v1/filebox/browse/users")
    assert users_resp.status_code == 200
    assert users_resp.json()["current_user"] == "tester"
