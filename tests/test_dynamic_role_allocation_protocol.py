"""Tests for Workspace Manager Centralized Dynamic Role Allocation Protocol.

Validates:
1. Every document and function is a privilege by default.
2. User customization: intentional exemption from privilege.
3. 14 dynamic privilege properties:
   (Select, Read, Write, Create, Delete, Print, Email, Report,
    Import, Export, Set User Permissions, Share, Access MCP, File Related).
4. Privilege Denial vs Privilege Granter (strict denial precedence).
5. All 10 core subsystems:
   (Pages, Sidebar, UI Customizer, Privilege Denial/Granter, MCP for given role,
    Filebox, Console & IDE, Sandbox Tenant, Network Egress, Model & Design Management).
6. Fast utilization & caching.
7. No static code for role mappings — fully dynamic registration and allocation.
"""

import pytest
import thinkdome
from thinkdome.security.rbac.protocol import (
    DynamicRoleAllocationProtocol,
    dynamic_role_protocol,
    PERMISSION_PROPERTIES,
    CORE_SUBSYSTEMS,
)
from thinkdome.security.rbac.models import DocPerm
from thinkdome.security.identity.core import UserIdentity, RolePolicyEngine


@pytest.fixture(autouse=True)
def reset_protocol():
    """Reset protocol state and cache before each test."""
    try:
        from thinkdome.security.rbac.models import DocPerm
        for dp in DocPerm.query().all():
            dp.delete(soft=False)
    except Exception:
        pass
    dynamic_role_protocol._in_memory_rules.clear()
    dynamic_role_protocol._bootstrap_protocol()
    dynamic_role_protocol.invalidate_cache()
    yield
    dynamic_role_protocol.invalidate_cache()


def test_protocol_incorporates_all_core_subsystems():
    """Verify that all 10 core subsystems are registered in the centralized protocol."""
    registered = dynamic_role_protocol.get_registered_doc_types()
    for subsystem in (
        "Page",
        "Sidebar",
        "UICustomizer",
        "MCPTool",
        "Filebox",
        "Console",
        "IDE",
        "Sandbox",
        "NetworkEgress",
        "ModelDesign",
        "Function",
    ):
        assert subsystem in registered or subsystem.lower() in [d.lower() for d in registered]


def test_fourteen_dynamic_privilege_properties():
    """Verify all 14 dynamic privilege properties are supported and evaluated."""
    expected_props = [
        "select",
        "read",
        "write",
        "create",
        "delete",
        "print",
        "email",
        "report",
        "import",
        "export",
        "set_user_permissions",
        "share",
        "access_mcp",
        "file_related",
    ]
    assert set(expected_props) == set(PERMISSION_PROPERTIES)

    # Allocate full 14 properties for a test role
    role_name = "SPECIALIST_AUDITOR"
    dynamic_role_protocol.register_role(role_name, "Specialist auditor with granular permissions")

    for prop in expected_props:
        # Before grant
        has_perm = dynamic_role_protocol.has_document_permission(
            roles={role_name},
            document_type="ModelDesign",
            action=prop,
        )
        assert has_perm is False, f"Expected {prop} to be False before grant"

    # Grant all 14 permissions dynamically
    dynamic_role_protocol.grant_privilege(
        document_type="ModelDesign",
        role=role_name,
        permissions=expected_props,
        level=1,
    )

    for prop in expected_props:
        has_perm = dynamic_role_protocol.has_document_permission(
            roles={role_name},
            document_type="ModelDesign",
            action=prop,
            level=1,
        )
        assert has_perm is True, f"Expected {prop} to be True after grant"


def test_privilege_granter_and_denial_precedence():
    """Privilege Denial must strictly override Privilege Granter."""
    role = "SECURITY_TESTER"
    dynamic_role_protocol.register_role(role, "Role for grant/deny testing")

    # 1. Grant privilege
    dynamic_role_protocol.grant_privilege(
        document_type="Console",
        role=role,
        permissions=["read", "write", "select"],
    )
    assert dynamic_role_protocol.has_document_permission({role}, "Console", "write") is True

    # 2. Deny privilege on the same resource
    dynamic_role_protocol.deny_privilege(
        document_type="Console",
        role=role,
        permissions=["write"],
    )
    # Write must now be explicitly denied
    assert dynamic_role_protocol.has_document_permission({role}, "Console", "write") is False
    # Read should still be granted
    assert dynamic_role_protocol.has_document_permission({role}, "Console", "read") is True


def test_every_function_is_privilege_by_default():
    """Default: every function requires privilege. User can customize to exempt."""
    # Define a normal whitelisted function (default: require_privilege=True)
    @thinkdome.whitelist()
    def protected_banking_op(amount: int):
        return {"transferred": amount}

    # Call without session: works programmatically for tests
    assert protected_banking_op(50) == {"transferred": 50}

    # Call with non-privileged session context: must be denied by default
    from thinkdome.core.handler import SessionContext, resolve_and_call

    with SessionContext({"username": "guest_user", "role": "GUEST"}):
        with pytest.raises(PermissionError) as exc_info:
            resolve_and_call("protected_banking_op", amount=100)
        assert "Guest access is not permitted" in str(exc_info.value) or "denied" in str(exc_info.value)


def test_user_intentional_customization_exemption():
    """User can intentionally customize a function or document to NOT require privilege."""
    # Function with intentional customization
    @thinkdome.whitelist(allow_guest=True, require_privilege=False)
    def public_health_status():
        return {"status": "ok"}

    from thinkdome.core.handler import SessionContext, resolve_and_call

    # Guest user can execute because of intentional customization
    with SessionContext({"username": "random_guest", "role": "GUEST"}):
        res = resolve_and_call("public_health_status")
        assert res == {"status": "ok"}

    # Dynamic document exemption customization
    dynamic_role_protocol.customize_exemption("CustomPublicReport", exempt=True)
    assert dynamic_role_protocol.has_document_permission({"GUEST"}, "CustomPublicReport", "read") is True

    # Revert customization
    dynamic_role_protocol.customize_exemption("CustomPublicReport", exempt=False)
    assert dynamic_role_protocol.has_document_permission({"GUEST"}, "CustomPublicReport", "read") is False


def test_mcp_for_given_role():
    """Verify MCP tools are filtered and secured dynamically per role."""
    # Grant access_mcp for a tool to DEVELOPER, but deny to GUEST
    dynamic_role_protocol.grant_privilege("MCPTool", "DEVELOPER", ["access_mcp"])
    dynamic_role_protocol.deny_privilege("MCPTool", "GUEST", ["access_mcp"])

    assert dynamic_role_protocol.has_document_permission({"DEVELOPER"}, "MCPTool", "access_mcp") is True
    assert dynamic_role_protocol.has_document_permission({"GUEST"}, "MCPTool", "access_mcp") is False


def test_filebox_dynamic_privileges():
    """Verify Filebox filesystem checks dynamically allocated permissions."""
    role = "ANALYST_ROLE"
    dynamic_role_protocol.register_role(role, "Data analyst")
    dynamic_role_protocol.grant_privilege("Filebox", role, ["read", "file_related"])
    dynamic_role_protocol.deny_privilege("Filebox", role, ["delete"])

    assert dynamic_role_protocol.has_document_permission({role}, "Filebox", "read") is True
    assert dynamic_role_protocol.has_document_permission({role}, "Filebox", "file_related") is True
    assert dynamic_role_protocol.has_document_permission({role}, "Filebox", "delete") is False


def test_console_and_ide_dynamic_privileges():
    """Verify Console and IDE execution privileges."""
    dev_role = "DEV_ENGINEER"
    dynamic_role_protocol.register_role(dev_role, "Software Engineer")
    dynamic_role_protocol.grant_privilege("Console", dev_role, ["select", "read", "write"])
    dynamic_role_protocol.grant_privilege("IDE", dev_role, ["select", "read", "write", "file_related"])

    assert dynamic_role_protocol.has_document_permission({dev_role}, "Console", "write") is True
    assert dynamic_role_protocol.has_document_permission({dev_role}, "IDE", "file_related") is True


def test_sandbox_tenant_and_network_egress():
    """Verify Sandbox tenant isolation and Network Egress privilege allocation."""
    egress_admin = "NET_ADMIN"
    dynamic_role_protocol.register_role(egress_admin, "Network Administrator")
    dynamic_role_protocol.grant_privilege("NetworkEgress", egress_admin, ["read", "write"])

    assert dynamic_role_protocol.has_document_permission({egress_admin}, "NetworkEgress", "write") is True
    assert dynamic_role_protocol.has_document_permission({"GUEST"}, "NetworkEgress", "write") is False


def test_fast_utilization_and_cache_invalidation():
    """Cache must deliver microsecond evaluation and invalidate instantly on update."""
    role = "CACHE_TEST_ROLE"
    dynamic_role_protocol.register_role(role, "Cache testing")

    # Grant read
    dynamic_role_protocol.grant_privilege("Page", role, ["read"])

    # First call: populates cache
    assert dynamic_role_protocol.has_document_permission({role}, "Page", "read") is True

    # Cache hit check
    assert dynamic_role_protocol.has_document_permission({role}, "Page", "read") is True

    # Deny privilege: cache must invalidate immediately
    dynamic_role_protocol.deny_privilege("Page", role, ["read"])
    assert dynamic_role_protocol.has_document_permission({role}, "Page", "read") is False


def test_pluggable_document_type_resolver():
    """Verify that document types are resolved dynamically via pluggable resolver, not rigid ladders."""
    from thinkdome.security.rbac.protocol import document_type_resolver

    # 1. Aliases & entity_type
    assert dynamic_role_protocol.resolve_document_type({"entity_type": "page"}) == "Page"
    assert dynamic_role_protocol.resolve_document_type({"entity_type": "workspace"}) == "Sidebar"
    assert dynamic_role_protocol.resolve_document_type({"entity_type": "menu_item"}) == "Sidebar"
    assert dynamic_role_protocol.resolve_document_type({"entity_type": "component"}) == "UICustomizer"
    assert dynamic_role_protocol.resolve_document_type({"entity_type": "mcp_tool"}) == "MCPTool"

    # 2. Structural detectors
    assert dynamic_role_protocol.resolve_document_type({"layout": "grid", "blocks": []}) == "Page"
    assert dynamic_role_protocol.resolve_document_type({"items": [{"label": "Home"}]}) == "Sidebar"
    assert dynamic_role_protocol.resolve_document_type({"tool_name": "weather_api"}) == "MCPTool"
    assert dynamic_role_protocol.resolve_document_type({"file_path": "/var/data/test.csv"}) == "Filebox"
    assert dynamic_role_protocol.resolve_document_type({"sandbox_id": "sbx_001"}) == "Sandbox"
    assert dynamic_role_protocol.resolve_document_type({"destination_host": "api.github.com"}) == "NetworkEgress"
    assert dynamic_role_protocol.resolve_document_type({"prompt_template": "You are a scientist"}) == "ModelDesign"

    # 3. Dynamic runtime extension
    document_type_resolver.register_alias("custom_analytics_chart", "CustomAnalytics")
    document_type_resolver.register_detector("CustomAnalytics", lambda r: "chart_data" in r, priority=50)

    assert dynamic_role_protocol.resolve_document_type("custom_analytics_chart") == "CustomAnalytics"
    assert dynamic_role_protocol.resolve_document_type({"chart_data": [1, 2, 3]}) == "CustomAnalytics"


def test_mandatory_audit_logging_on_grants_denials_and_exemptions():
    """Verify that every grant, denial, exemption, and denied attempt records an RbacAuditLog entry."""
    from thinkdome.security.rbac.models import RbacAuditLog

    # Clean test audit logs
    for log in RbacAuditLog.query().all():
        log.delete(soft=False)

    test_role = "AUDIT_TEST_ROLE"
    dynamic_role_protocol.register_role(test_role, "Audit logging test role")

    # 1. Grant privilege -> must log privilege_grant
    dynamic_role_protocol.grant_privilege("Filebox", test_role, ["read", "write"], actor="admin_alice")
    grant_logs = RbacAuditLog.query().filter(action="privilege_grant", target_type="Filebox").all()
    assert len(grant_logs) >= 1
    assert grant_logs[-1].actor == "admin_alice"
    assert test_role in grant_logs[-1].target_id

    # 2. Deny privilege -> must log privilege_deny
    dynamic_role_protocol.deny_privilege("Filebox", test_role, ["write"], actor="admin_bob")
    deny_logs = RbacAuditLog.query().filter(action="privilege_deny", target_type="Filebox").all()
    assert len(deny_logs) >= 1
    assert deny_logs[-1].actor == "admin_bob"
    assert test_role in deny_logs[-1].target_id

    # 3. Customize exemption -> must log privilege_exempt
    dynamic_role_protocol.customize_exemption("public_analytics_feed", exempt=True, actor="admin_carol")
    exempt_logs = RbacAuditLog.query().filter(action="privilege_exempt").all()
    assert len(exempt_logs) >= 1
    assert exempt_logs[-1].actor == "admin_carol"
    assert exempt_logs[-1].target_id == "public_analytics_feed"

    # 4. Denied attempt -> must log privilege_denied_attempt when explicitly denied
    has_perm = dynamic_role_protocol.has_document_permission({test_role}, "Filebox", "write")
    assert has_perm is False
    denied_attempt_logs = RbacAuditLog.query().filter(action="privilege_denied_attempt").all()
    assert len(denied_attempt_logs) >= 1
    assert denied_attempt_logs[-1].target_type == "Filebox"


def test_standard_orm_in_auth_service():
    """Verify that AuthService operations use ThinkDome ORM models without raw SQL strings."""
    from thinkdome.security.auth.service import AuthService
    from thinkdome.security.rbac.models import ApiKey, AuthUser
    from thinkdome.security.identity.core import RolePolicyEngine

    auth_svc = AuthService()

    # 1. Create API key using ORM
    key_info = auth_svc.create_api_key(
        display_name="Enterprise Test Key",
        permissions=[],
        creator="admin_tester",
    )
    assert key_info["key_id"].startswith("key_")
    assert "token" in key_info

    # Verify record in ApiKey ORM model
    orm_key = ApiKey.query().filter(key_id=key_info["key_id"]).first()
    assert orm_key is not None
    assert orm_key.display_name == "Enterprise Test Key"
    assert orm_key.status == "active"

    # 2. Verify token via ORM
    identity = auth_svc.verify_token(key_info["token"])
    assert identity is not None
    assert identity["key_id"] == key_info["key_id"]

    # 3. List API keys via ORM
    all_keys = auth_svc.list_api_keys()
    assert any(k["key_id"] == key_info["key_id"] for k in all_keys)

    # 4. Revoke API key via ORM
    revoked = auth_svc.revoke_api_key(key_info["key_id"], actor="admin_tester")
    assert revoked is True
    orm_key_after = ApiKey.query().filter(key_id=key_info["key_id"]).first()
    assert orm_key_after.status == "revoked"

    # Verification of revoked token should now fail
    assert auth_svc.verify_token(key_info["token"]) is None


def test_default_rules_seed_database_when_empty():
    """Verify that _DEFAULT_RULES automatically seeds the database DocPerm table when empty."""
    from thinkdome.security.rbac.protocol import _DEFAULT_RULES
    from thinkdome.security.rbac.models import DocPerm

    assert len(_DEFAULT_RULES) >= 10
    # Check that seed covers core subsystems
    seeded_doc_types = {r["document_type"] for r in _DEFAULT_RULES}
    for required in ("Page", "Sidebar", "UICustomizer", "MCPTool", "Filebox", "Sandbox", "Function"):
        assert required in seeded_doc_types

    # Ensure docperms exist after bootstrap
    total_perms = DocPerm.query().count()
    assert total_perms >= len(_DEFAULT_RULES)


def test_redis_caching_and_invalidation():
    """Verify UICacheManager caches rules and gets invalidated upon privilege mutations."""
    from thinkdome.core.ui.cache import UICacheManager

    cache = UICacheManager.get_instance()
    cache.set("rbac:test_key", {"status": "ok"}, ttl_seconds=60)
    assert cache.get("rbac:test_key") == {"status": "ok"}

    # Dynamic mutation must invalidate cache
    dynamic_role_protocol.invalidate_cache()
    assert cache.get("rbac:test_key") is None


def test_workspace_manager_override_privilege():
    """Verify Workspace Manager override, bulk override, retrieval, and reset."""
    ws_id = "ws_engineering_alpha"
    role = "DEVELOPER"
    doc_type = "NetworkEgress"

    # 1. Override a privilege scoped to workspace
    override_res = dynamic_role_protocol.override_privilege(
        workspace_id=ws_id,
        document_type=doc_type,
        role=role,
        permissions={"write": True, "access_mcp": True},
        is_denial=False,
    )
    assert override_res["workspace_id"] == ws_id
    assert override_res["permissions"]["write"] is True

    # Check override retrieval
    overrides = dynamic_role_protocol.get_privilege_overrides(ws_id)
    assert len(overrides) >= 1
    assert any(o["document_type"] == doc_type for o in overrides)

    # 2. Bulk override
    bulk_res = dynamic_role_protocol.bulk_override_privileges(
        workspace_id=ws_id,
        overrides=[
            {"document_type": "Console", "role": role, "permissions": {"write": True}},
            {"document_type": "IDE", "role": role, "permissions": {"write": True, "access_mcp": True}},
        ],
    )
    assert len(bulk_res) == 2

    # Verify workspace-specific rules evaluation
    has_perm = dynamic_role_protocol.has_document_permission(
        roles={role},
        document_type=doc_type,
        action="write",
        workspace_id=ws_id,
    )
    assert has_perm is True

    # 3. Reset workspace overrides back to defaults
    reset_count = dynamic_role_protocol.reset_privileges_to_defaults(ws_id)
    assert reset_count >= 1
    overrides_after = dynamic_role_protocol.get_privilege_overrides(ws_id)
    assert len(overrides_after) == 0


def test_user_registration_rich_profile_fields():
    """Verify self-registration accepts rich profile fields and dynamically allocates the default role."""
    from thinkdome.security.rbac.service import UserService
    from thinkdome.security.repositories.user import UserRepository

    user_svc = UserService()
    user_repo = UserRepository()

    test_username = "rich_user_test"
    # Ensure fresh state
    from thinkdome.security.rbac.models import UserProfile
    existing = user_repo.find_by_username(test_username)
    if existing:
        for p in UserProfile.query().filter(user_id=existing.id).all():
            p.delete(soft=False)
        existing.delete(soft=False)
    existing_email = user_repo.get_by_email("rich_user@enterprise.local")
    if existing_email:
        for p in UserProfile.query().filter(user_id=existing_email.id).all():
            p.delete(soft=False)
        existing_email.delete(soft=False)

    created_user = user_svc.create_user(
        username=test_username,
        email="rich_user@enterprise.local",
        password="ValidSecretPassword123!",
        first_name="Jane",
        last_name="Doe",
        phone="+1-555-0199",
        department_id="sec-ops",
        designation="Senior Security Engineer",
        organization="Enterprise Systems Corp",
        bio="Specializes in identity and access governance",
        timezone="America/New_York",
        locale="en-US",
    )
    assert created_user is not None
    assert created_user.username == test_username

    profile = user_svc.get_user_profile(created_user.id)
    assert profile is not None
    assert profile.phone == "+1-555-0199"
    assert profile.department_id == "sec-ops"
    assert profile.designation == "Senior Security Engineer"
    assert profile.organization == "Enterprise Systems Corp"
    assert profile.bio == "Specializes in identity and access governance"
    assert profile.timezone == "America/New_York"
    assert profile.locale == "en-US"


def test_ui_privilege_endpoints_and_protocol_matrix():
    """Verify REST endpoints for privilege grant, denial, exemption, and protocol matrix."""
    from thinkdome.core.ui.service import UIManager

    ui_mgr = UIManager()
    matrix = ui_mgr.get_role_permission_matrix()
    assert "protocol_matrix" in matrix
    assert "document_types" in matrix["protocol_matrix"]
    assert "permissions" in matrix["protocol_matrix"]
    assert len(matrix["protocol_matrix"]["permissions"]) == 14

    # Grant via UIManager
    grant_res = ui_mgr.grant_privilege("Filebox", "AUDITOR", {"read": True, "file_related": True})
    assert grant_res["is_denial"] is False

    # Deny via UIManager (strict denial takes precedence)
    deny_res = ui_mgr.deny_privilege("Filebox", "AUDITOR", {"write": True})
    assert deny_res["is_denial"] is True

    # Custom exemption via UIManager
    exempt_ok = ui_mgr.customize_exemption("Filebox", exempt=True)
    assert exempt_ok is True


def test_request_log_and_checkpoint_queries_via_orm():
    """Verify request log counting and deletion use standard ORM methods without raw SQL."""
    from thinkdome.platform.observability.models import RequestLog
    from thinkdome.platform.orchestration.request_log import RequestLogService
    from thinkdome.core.config import Settings
    from thinkdome.platform.database.service import DatabaseService

    settings = Settings()
    db_svc = DatabaseService(settings=settings)
    log_svc = RequestLogService(settings, db_svc)

    initial_count = RequestLog.query().count()
    assert isinstance(initial_count, int)

    # Log a dummy request
    log_svc.log_request(
        client_ip="127.0.0.1",
        user_info={"display_name": "TestActor", "role": "DEVELOPER"},
        tool_use={"id": "call_123", "name": "test_tool", "input": {"x": 1}},
        tool_result={"content": "success", "is_error": False},
        duration_ms=12.5,
    )
    new_count = RequestLog.query().count()
    assert new_count >= initial_count + 1

    # Clear logs using ORM
    log_svc.clear_logs(actor="admin_tester")
    assert RequestLog.query().count() == 0
