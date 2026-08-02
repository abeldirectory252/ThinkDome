"""Comprehensive tests for Enterprise Dynamic RBAC System."""

import uuid
import pytest
from thinkdome.security.rbac.service import UserService, RoleService, PermissionService
from thinkdome.security.repositories.user import UserRepository
from thinkdome.security.repositories.role import RoleRepository
from thinkdome.security.repositories.permission import PermissionRepository
from thinkdome.security.repositories.audit import AuditRepository
from thinkdome.security.identity.evaluator import permission_evaluator


@pytest.fixture
def rbac_services():
    user_svc = UserService()
    role_svc = RoleService()
    perm_svc = PermissionService()
    audit_repo = AuditRepository()
    return user_svc, role_svc, perm_svc, audit_repo


def test_user_creation_and_profile(rbac_services):
    user_svc, _, _, _ = rbac_services
    uid = uuid.uuid4().hex[:8]
    user = user_svc.create_user(
        username=f"john_{uid}",
        email=f"john_{uid}@enterprise.com",
        password="Password123!",
        first_name="John",
        last_name="Doe",
    )
    assert user.id is not None
    assert user.username == f"john_{uid}"
    assert user.status == "active"

    profile = UserRepository().get_profile(user.id)
    assert profile is not None
    assert profile.first_name == "John"
    assert profile.last_name == "Doe"


def test_dynamic_role_creation_and_permission_assignment(rbac_services):
    user_svc, role_svc, perm_svc, _ = rbac_services
    uid = uuid.uuid4().hex[:8]

    # 1. Create permission
    perm = perm_svc.create_permission(
        module=f"erp_{uid}",
        resource="sales_invoice",
        action="approve",
        description="Approve Sales Invoice",
    )
    assert perm.id is not None

    # 2. Create role
    role = role_svc.create_role(
        name=f"SalesApprover_{uid}",
        description="Can approve sales invoices",
    )
    assert role.id is not None

    # 3. Assign permission to role
    role_svc.assign_permission_to_role(role.id, perm.id)

    # 4. Create user and assign role
    user = user_svc.create_user(
        username=f"approver_{uid}",
        email=f"bob_{uid}@enterprise.com",
        password="Password123!",
    )
    user_svc.assign_role_to_user(user.id, role.id)

    # 5. Evaluate permissions (Level 3: Assigned Roles)
    allowed = permission_evaluator.has_permission(
        user_id=user.id,
        module=f"erp_{uid}",
        resource="sales_invoice",
        action="approve",
    )
    assert allowed is True

    denied = permission_evaluator.has_permission(
        user_id=user.id,
        module=f"erp_{uid}",
        resource="accounting",
        action="delete",
    )
    assert denied is False


def test_role_hierarchy_inheritance(rbac_services):
    user_svc, role_svc, perm_svc, _ = rbac_services
    uid = uuid.uuid4().hex[:8]

    # Base permission
    perm = perm_svc.create_permission(
        module=f"file_{uid}",
        resource="workspace",
        action="read",
    )

    # Parent Role
    parent_role = role_svc.create_role(name=f"BaseViewer_{uid}", description="Parent Role")
    role_svc.assign_permission_to_role(parent_role.id, perm.id)

    # Child Role inheriting from Parent Role
    child_role = role_svc.create_role(
        name=f"SeniorViewer_{uid}",
        description="Child Role inheriting BaseViewer",
        parent_role_id=parent_role.id,
    )

    # Assign child role to user
    user = user_svc.create_user(
        username=f"alice_{uid}",
        email=f"alice_{uid}@enterprise.com",
        password="Password123!",
    )
    user_svc.assign_role_to_user(user.id, child_role.id)

    # User should inherit permission through role tree (Level 4: Inherited Roles)
    allowed = permission_evaluator.has_permission(
        user_id=user.id,
        module=f"file_{uid}",
        resource="workspace",
        action="read",
    )
    assert allowed is True


def test_instant_permission_cache_invalidation(rbac_services):
    user_svc, role_svc, perm_svc, _ = rbac_services
    uid = uuid.uuid4().hex[:8]

    user = user_svc.create_user(
        username=f"cache_{uid}",
        email=f"cache_{uid}@enterprise.com",
        password="Password123!",
    )

    role = role_svc.create_role(name=f"DynamicRole_{uid}", description="Test Cache Invalidation")
    perm = perm_svc.create_permission(module=f"analytics_{uid}", resource="dashboard", action="view")

    user_svc.assign_role_to_user(user.id, role.id)

    # Initial check (denied and cached)
    assert permission_evaluator.has_permission(user.id, f"analytics_{uid}", "dashboard", "view") is False

    # Dynamically assign permission to role (should immediately invalidate cache)
    role_svc.assign_permission_to_role(role.id, perm.id)

    # Check again without app restart -> must evaluate to True immediately
    assert permission_evaluator.has_permission(user.id, f"analytics_{uid}", "dashboard", "view") is True


@pytest.mark.asyncio
async def test_rbac_api_routes(client, app):
    auth_svc = app.state.auth_service
    admin_token = auth_svc.create_api_key("Admin Key", token_type="ADMIN")["token"]
    headers = {"Authorization": f"Bearer {admin_token}"}
    uid = uuid.uuid4().hex[:8]

    # 1. Create Role via REST API
    resp = await client.post("/v1/roles", json={
        "name": f"ApiTestRole_{uid}",
        "description": "Created via API"
    }, headers=headers)
    assert resp.status_code == 201
    role_id = resp.json()["role"]["id"]

    # 2. List Roles via REST API
    resp = await client.get("/v1/roles", headers=headers)
    assert resp.status_code == 200
    assert any(r["id"] == role_id for r in resp.json())

    # 3. Create Permission via REST API
    resp = await client.post("/v1/permissions", json={
        "module": f"system_{uid}",
        "resource": "audit",
        "action": "export"
    }, headers=headers)
    assert resp.status_code == 201
    perm_id = resp.json()["permission"]["id"]

    # 4. Assign Permission to Role via REST API
    resp = await client.post(f"/v1/roles/{role_id}/permissions", json={
        "permission_id": perm_id
    }, headers=headers)
    assert resp.status_code == 200

    # 5. Create User via REST API
    resp = await client.post("/v1/users", json={
        "username": f"api_user_{uid}",
        "email": f"api_{uid}@enterprise.com",
        "password": "Password123!",
        "first_name": "API",
        "last_name": "User"
    }, headers=headers)
    assert resp.status_code == 201
    user_id = resp.json()["user"]["id"]

    # 6. Assign Role to User via REST API
    resp = await client.post(f"/v1/users/{user_id}/roles", json={
        "role_id": role_id
    }, headers=headers)
    assert resp.status_code == 200

    # 7. Check Audit Logs via REST API
    resp = await client.get("/v1/audit/logs", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) > 0
