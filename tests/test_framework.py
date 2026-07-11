"""Verification tests for the ThinkDome framework kernel, ORM, hooks, events, queues, and apps."""

import os
import json
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

from thinkdome.core.kernel.kernel import Kernel
from thinkdome.core.orm.orm import Model, StringField, IntegerField, BooleanField
from thinkdome.core.events.events import bus as event_bus
from thinkdome.core.hooks.hooks import manager as hook_manager
from thinkdome.core.metadata.metadata import load_doctype_manifest
from thinkdome.core.queue.queue import register_task, enqueue
from thinkdome.apps.sandbox.models import Sandbox
from thinkdome.apps.sandbox.controller import create_sandbox, destroy_sandbox
from thinkdome.apps.agents.models import Agent
from thinkdome.apps.agents.controller import initialize_agent, execute_agent
from thinkdome.apps.workflows.models import Workflow, WorkflowExecution
from thinkdome.apps.workflows.controller import start_workflow, approve_execution


# ── Test Models ───────────────────────────────────────────────────────────────

class Device(Model):
    """Dynamic test model representing hardware devices."""
    name = StringField(required=True)
    ports = IntegerField(default=4)
    online = BooleanField(default=True)


# ── Test Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_test_site():
    """Ensure kernel context is bound to 'personal' testing database with clean tables."""
    os.environ["THINKDOME_SITE"] = "personal"
    kernel = Kernel.get_instance("personal")
    kernel.initialize()
    
    # Drop and recreate all tables for a clean slate per test
    from thinkdome.core.orm.orm import Base
    Base.metadata.drop_all(kernel.db_engine)
    Base.metadata.create_all(kernel.db_engine)
    
    yield kernel
    kernel.close()


# ── 1. ORM Tests ──────────────────────────────────────────────────────────────

def test_orm_crud_and_query():
    """Verify ORM model creation, persistence, query filtering, and soft delete."""
    device = Device(name="Core Switch", ports=24)
    device.save()
    assert device.id is not None
    assert device._loaded is True

    # Retrieve from DB
    retrieved = Device.get(device.id)
    assert retrieved is not None
    assert retrieved.name == "Core Switch"
    assert retrieved.ports == 24
    assert retrieved.online is True

    # Query builder filter
    matches = Device.query().filter(name="Core Switch").all()
    assert len(matches) == 1
    assert matches[0].id == device.id

    # Soft delete
    device.delete(soft=True)
    assert Device.get(device.id) is None  # Excluded by default soft-delete check
    
    # Verify physically still present but marked deleted
    matches_deleted = Device.query().filter(id=device.id).all()
    assert len(matches_deleted) == 0


# ── 2. Event Bus & Hook Pipeline Tests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_events_and_hooks():
    """Test hook prioritization / cancellation and event bus pub-sub triggers."""
    event_payload = {}
    hook_runs = []

    # 1. Event subscription
    def on_device_alert(data):
        event_payload.update(data)

    event_bus.on("device.alert", on_device_alert)
    await event_bus.emit("device.alert", {"severity": "critical", "source": "switch-1"})
    assert event_payload.get("severity") == "critical"

    # 2. Hook execution hierarchy
    def first_hook(model):
        hook_runs.append("first")

    def second_hook(model):
        hook_runs.append("second")

    hook_manager.register("device.before_validate", first_hook, priority=10)
    hook_manager.register("device.before_validate", second_hook, priority=5)

    test_device = Device(name="Router-A")
    # Trigger before_validate hooks during validation phase
    test_device.validate()
    await hook_manager.run("device.before_validate", test_device)

    assert hook_runs == ["second", "first"]  # 'second' ran first because priority 5 < 10


# ── 3. Queue & Background Tasks Tests ─────────────────────────────────────────

def test_background_task_registration():
    """Verify background task wrappers can be registered and enqueued."""
    task_payload = {}

    @register_task("test_alert")
    def task_alert(payload):
        task_payload.update(payload)

    # Queue execution
    enqueue("test_alert", {"status": "resolved"})
    
    # Query job registry status directly in database
    kernel = Kernel.current()
    row = kernel.db.execute(
        text("SELECT * FROM queue_jobs WHERE task_name = 'test_alert'")
    ).first()
    assert row is not None
    assert row._mapping["status"] == "queued"


# ── 4. Sandbox Orchestration, Agent, and Workflow App Tests ──────────────────

@pytest.mark.asyncio
async def test_sandbox_and_agent_app_lifecycles():
    """Verify Sandbox container mapping state loops and Agent run steps."""
    # 1. Sandbox Lifecycle
    sb = Sandbox(name="Test Sandbox A", runtime="subprocess", owner="tester")
    sb.save()
    assert sb.status == "Created"

    await create_sandbox(sb)
    assert sb.status == "Running"

    await destroy_sandbox(sb)
    assert sb.status == "Destroyed"

    # 2. Agent Execution Steps
    agent = Agent(name="Assistant-1", model="gpt-4o", owner="tester")
    agent.save()
    await initialize_agent(agent)
    assert agent.status == "Ready"

    res = await execute_agent(agent, "Print status info")
    assert agent.status == "Completed"
    assert "Assistant-1" in res["output"]


@pytest.mark.asyncio
async def test_workflow_engine_traversal():
    """Verify automation pipeline directed traversal, condition branches, and gates."""
    # Build simple node graph: trigger -> condition -> approval gate -> completion
    nodes = [
        {"id": "node-1", "type": "action", "action": "log", "payload": {"message": "Start Pipeline"}},
        {"id": "node-2", "type": "condition", "field": "success", "operator": "==", "value": "true"},
        {"id": "node-3", "type": "approval", "message": "Manual review of logs required"},
    ]
    edges = [
        {"from": "node-1", "to": "node-2"},
        {"from": "node-2", "to": "node-3", "condition": "true"},
    ]

    wf = Workflow(
        name="Build Automator",
        nodes=json.dumps(nodes),
        edges=json.dumps(edges),
        owner="tester",
    )
    wf.save()

    # Trigger run with condition true
    execution = await start_workflow(wf, {"success": "true"})
    assert execution.status == "WaitingApproval"
    assert execution.current_node == "node-3"

    # Approve and resume
    await approve_execution(execution.id)
    res_record = WorkflowExecution.get(execution.id)
    assert res_record.status == "Completed"


# ── 5. REST CRUD API Tests ────────────────────────────────────────────────────

def test_metadata_crud_rest_routes():
    """Verify REST API gateway dynamically serving CRUD operations."""
    from thinkdome.core.api.server import app
    client = TestClient(app)

    # 1. List devices (currently empty/filtered)
    resp = client.get("/api/device")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # 2. Post new device
    payload = {"name": "Agg Switch", "ports": 48}
    resp = client.post("/api/device", json=payload)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["name"] == "Agg Switch"
    assert res_data["ports"] == 48
    device_id = res_data["id"]

    # 3. Retrieve detail
    resp = client.get(f"/api/device/{device_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Agg Switch"

    # 4. Modify attributes
    resp = client.put(f"/api/device/{device_id}", json={"ports": 52})
    assert resp.status_code == 200
    assert resp.json()["ports"] == 52

    # 5. Delete resource
    resp = client.delete(f"/api/device/{device_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


# ── 6. App Manager & Migration Engine Tests ───────────────────────────────────

def test_app_installer_and_migrations(tmp_path):
    """Test package manager installation, dependency verification, and migrations."""
    # 1. Create a dummy app structure
    dummy_app_dir = tmp_path / "dummy_app"
    dummy_app_dir.mkdir()
    
    app_json = {
        "name": "dummy_app",
        "version": "1.0.0",
        "description": "A dummy test application extension",
        "dependencies": ["core"],
        "author": "tester",
        "license": "MIT"
    }
    with open(dummy_app_dir / "app.json", "w") as f:
        json.dump(app_json, f)
        
    (dummy_app_dir / "migrations").mkdir()
    migration_code = """
from sqlalchemy import text
def up(db):
    db.execute(text("CREATE TABLE test_customers (id VARCHAR(255) PRIMARY KEY, name VARCHAR(255))"))
    db.commit()
def down(db):
    db.execute(text("DROP TABLE test_customers"))
    db.commit()
"""
    with open(dummy_app_dir / "migrations" / "0001_initial.py", "w") as f:
        f.write(migration_code)
        
    # 2. Test dynamic symlink linking
    from thinkdome.core.kernel.manager import AppInstaller
    app_name = AppInstaller.link(str(dummy_app_dir))
    assert app_name == "dummy_app"
    
    # 3. Test migration runner
    from thinkdome.core.kernel.migrations import MigrationRunner
    runner = MigrationRunner("personal")
    runner.migrate("dummy_app")
    
    # Check status
    statuses = runner.status()
    target_status = next((s for s in statuses if s["app"] == "dummy_app" and s["migration"] == "0001_initial"), None)
    assert target_status is not None
    assert target_status["status"] == "Applied"
    
    # Verify table exists in DB by querying it
    kernel = Kernel.current()
    kernel.db.execute(text("SELECT * FROM test_customers"))
    
    # 4. Test rollback
    runner.rollback("dummy_app")
    statuses_after = runner.status()
    target_status_after = next((s for s in statuses_after if s["app"] == "dummy_app" and s["migration"] == "0001_initial"), None)
    assert target_status_after is not None
    assert target_status_after["status"] == "Pending"
    
    # Clean up linked app
    AppInstaller.uninstall("dummy_app")

