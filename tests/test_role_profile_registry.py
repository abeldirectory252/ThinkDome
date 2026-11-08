"""Comprehensive Tests for Dynamic Role Names, Role Profiles, and Redis Caching Architecture.

Validates:
1. Low-level Role Names holding low-level privileges/DocPerms in DB.
2. Role Profiles as collections of low-level Role Names for easy user assignment.
3. User assignment: assigning a Role Profile automatically expands into all low-level Role Names.
4. Redis caching (RbacCache) for role definitions, role profiles, user roles, and privileges.
5. Cache invalidation on role/profile update or user re-assignment.
6. Elimination of hardcoded role checks in favor of dynamic privilege evaluation.
"""

import pytest
from thinkdome.security.rbac.models import (
    Role,
    RoleProfile,
    RoleProfileRole,
    UserRoleProfile,
    User,
    DocPerm,
)
from thinkdome.security.rbac.cache import rbac_cache, RbacCache
from thinkdome.security.rbac.registry import rbac_registry, RoleProfileRegistry
from thinkdome.security.identity.core import UserIdentity, is_admin_role, select_effective_role
from thinkdome.sandbox.executors.docker.python_executor import get_resource_profile


@pytest.fixture(autouse=True)
def clean_registry():
    """Ensure clean registry state and invalidate cache before and after test."""
    rbac_cache.invalidate_all()
    rbac_registry.bootstrap_standard_roles_and_profiles()
    yield
    rbac_cache.invalidate_all()


def test_standard_roles_and_profiles_bootstrapped():
    """Verify standard low-level role names and role profiles are seeded in the database."""
    # Check low-level role names
    sandbox_exec = rbac_registry.get_role("sandbox_executor")
    assert sandbox_exec is not None
    assert sandbox_exec["name"] == "SANDBOX_EXECUTOR"
    assert sandbox_exec["is_admin"] is False

    admin_role = rbac_registry.get_role("super_admin")
    assert admin_role is not None
    assert admin_role["is_admin"] is True

    # Check Role Profiles (collections of role names)
    dev_prof = rbac_registry.get_role_profile("Developer")
    assert dev_prof is not None
    assert "SANDBOX_EXECUTOR" in dev_prof["role_names"]
    assert "NETWORK_EGRESS_MANAGER" in dev_prof["role_names"]
    assert "CONSOLE_OPERATOR" in dev_prof["role_names"]

    admin_prof = rbac_registry.get_role_profile("Administrator")
    assert admin_prof is not None
    assert "SUPER_ADMIN" in admin_prof["role_names"]
    assert "SANDBOX_ADMIN" in admin_prof["role_names"]


def test_custom_low_level_role_registration():
    """Verify registering a custom low-level Role Name with low-level DocPerm privileges."""
    custom_role = rbac_registry.register_role(
        name="metrics_collector",
        description="Low level privilege to collect sandbox metrics",
        is_admin=False,
        doc_perms=[
            {"document_type": "Console", "perm_read": True},
            {"document_type": "Sandbox", "perm_read": True},
        ],
    )
    assert custom_role.name == "METRICS_COLLECTOR"

    # Verify cached on Redis / memory
    cached = rbac_cache.get_role("METRICS_COLLECTOR")
    assert cached is not None
    assert cached["name"] == "METRICS_COLLECTOR"

    # Verify DocPerm created in DB
    dp = DocPerm.query().filter(document_type="Sandbox", role="METRICS_COLLECTOR").first()
    assert dp is not None
    assert dp.perm_read is True
    assert dp.perm_write is False


def test_custom_role_profile_creation():
    """Verify creating a custom Role Profile aggregating multiple low-level Role Names."""
    # Register two low-level roles
    rbac_registry.register_role("data_reader", description="Read data access")
    rbac_registry.register_role("model_trainer", description="Train models in sandbox")

    # Create a Role Profile grouping them
    profile = rbac_registry.register_role_profile(
        name="Data Scientist",
        description="Profile for ML researchers",
        role_names=["data_reader", "model_trainer", "sandbox_executor"],
    )
    assert profile.name == "Data Scientist"

    # Verify cached in Redis
    cached_prof = rbac_cache.get_role_profile("Data Scientist")
    assert cached_prof is not None
    assert "DATA_READER" in cached_prof["role_names"]
    assert "MODEL_TRAINER" in cached_prof["role_names"]
    assert "SANDBOX_EXECUTOR" in cached_prof["role_names"]


def test_user_assigned_role_profile_inherits_all_role_names():
    """Verify that assigning a Role Profile to a user dynamically provides all role names in the collection."""
    # Create test user
    username = "alice_dev"
    user = User.query().filter(username=username).first()
    if not user:
        user = User(
            username=username,
            email="alice@example.com",
            password_hash="testhash",
            status="active"
        )
        user.save()

    # Assign Developer Role Profile to alice
    assigned = rbac_registry.assign_role_profile_to_user(username, "Developer")
    assert assigned is True

    # Resolve roles for alice
    resolved_roles = rbac_registry.get_user_roles(username)
    assert "SANDBOX_EXECUTOR" in resolved_roles
    assert "NETWORK_EGRESS_MANAGER" in resolved_roles
    assert "CONSOLE_OPERATOR" in resolved_roles

    # Verify cached on Redis
    cached_user_roles = rbac_cache.get_user_roles(username)
    assert cached_user_roles is not None
    assert "SANDBOX_EXECUTOR" in cached_user_roles

    # UserIdentity resolution from dict
    identity = UserIdentity.from_dict({"username": username})
    assert "SANDBOX_EXECUTOR" in identity.roles
    assert "NETWORK_EGRESS_MANAGER" in identity.roles


def test_cache_invalidation_on_profile_update():
    """Verify Redis cache is properly invalidated when a Role Profile is updated."""
    username = "bob_analyst"
    user = User.query().filter(username=username).first()
    if not user:
        user = User(
            username=username,
            email="bob_analyst@example.com",
            password_hash="testhash",
            status="active"
        )
        user.save()

    # Register initial profile
    rbac_registry.register_role("report_viewer", "Can view reports")
    rbac_registry.register_role_profile("Report Specialist", role_names=["report_viewer"])
    rbac_registry.assign_role_profile_to_user(username, "Report Specialist")

    roles1 = rbac_registry.get_user_roles(username)
    assert "REPORT_VIEWER" in roles1
    assert "METRICS_EXPORTER" not in roles1

    # Update profile with a new low-level role
    rbac_registry.register_role("metrics_exporter", "Can export metrics")
    rbac_registry.register_role_profile("Report Specialist", role_names=["report_viewer", "metrics_exporter"])

    # Old user cache should be invalidated
    roles2 = rbac_registry.get_user_roles(username)
    assert "REPORT_VIEWER" in roles2
    assert "METRICS_EXPORTER" in roles2


def test_dynamic_resource_profile_resolution():
    """Verify Docker execution limits are dynamically resolved rather than statically bound."""
    # An administrative role gets admin resources (2 CPU cores, 1024m)
    admin_prof = get_resource_profile("super_admin")
    assert admin_prof["cpu_quota"] == 2.0
    assert admin_prof["memory"] == "1024m"

    # An unknown unprivileged role gets standard safe defaults (LLM profile)
    unprivileged_prof = get_resource_profile("UNKNOWN_GUEST_ROLE")
    assert unprivileged_prof["cpu_quota"] == 0.5
    assert unprivileged_prof["memory"] == "256m"


def test_dynamic_effective_role_selection():
    """Verify select_effective_role dynamically prioritizes administrative roles over guest/anonymous."""
    # When user has custom roles + an admin role, admin role is prioritized
    assert select_effective_role(["DATA_READER", "super_admin", "GUEST"]) == "SUPER_ADMIN"

    # Non-guest custom role is prioritized over GUEST
    assert select_effective_role(["METRICS_COLLECTOR", "GUEST"]) == "METRICS_COLLECTOR"
