import pytest
from thinkdome.security.identity.core import (
    Role,
    UserIdentity,
    RolePolicyEngine,
    is_admin_user,
    is_sandbox_accessible,
)


def test_user_identity_from_dict():
    data = {
        "username": "sarah_finance",
        "role": "FINANCE_MANAGER",
        "tenant_id": "site_enterprise",
        "permissions": ["custom:perm"],
    }
    identity = UserIdentity.from_dict(data)

    assert identity.username == "sarah_finance"
    assert identity.tenant_id == "site_enterprise"
    assert Role.FINANCE_MANAGER.value in identity.roles
    assert "custom:perm" in identity.permissions
    assert identity.is_admin() is False


def test_super_admin_and_role_inheritance():
    admin_id = UserIdentity.from_dict({"username": "admin", "role": "SUPER_ADMIN"})
    assert admin_id.is_admin() is True
    assert RolePolicyEngine.has_permission(admin_id, "erp:finance:post_journal") is True
    assert RolePolicyEngine.has_permission(admin_id, "any:custom:scope") is True


def test_wildcard_permission_matching():
    finance_mgr = UserIdentity.from_dict({
        "username": "mgr_john",
        "role": "FINANCE_MANAGER",
    })
    
    # FINANCE_MANAGER has 'erp:finance:*' permission pattern
    assert RolePolicyEngine.has_permission(finance_mgr, "erp:finance:post_journal") is True
    assert RolePolicyEngine.has_permission(finance_mgr, "erp:finance:view_gl") is True
    assert RolePolicyEngine.has_permission(finance_mgr, "system:admin") is False


def test_auditor_role_permissions():
    auditor = UserIdentity.from_dict({
        "username": "external_auditor",
        "role": "AUDITOR",
    })

    assert RolePolicyEngine.has_permission(auditor, "erp:audit:read") is True
    assert RolePolicyEngine.has_permission(auditor, "erp:finance:read") is True
    assert RolePolicyEngine.has_permission(auditor, "erp:finance:post") is False


def test_sandbox_accessibility_rbac():
    standard_user = UserIdentity.from_dict({
        "username": "user_a",
        "role": "SALES_USER",
    })

    sb_owned = {"sandbox_id": "sb_1", "owner": "user_a"}
    sb_other = {"sandbox_id": "sb_2", "owner": "user_b"}

    assert is_sandbox_accessible(sb_owned, standard_user) is True
    assert is_sandbox_accessible(sb_other, standard_user) is False

    admin_user = UserIdentity.from_dict({
        "username": "sysadmin",
        "role": "ADMIN",
    })
    assert is_sandbox_accessible(sb_other, admin_user) is True
