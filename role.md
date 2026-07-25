# ThinkDome — Enterprise Role-Based Access Control (RBAC) & MCP Sandbox Guide

## Overview

ThinkDome features a production-ready, dynamic **Role-Based & Attribute-Based Access Control (RBAC/ABAC)** engine built natively on top of ThinkDome's custom ORM (`thinkdome.core.orm.orm.Model`). 

All user identities, dynamic roles, permissions, departments, user groups, and audit trails are persisted and queried pythonically via ORM models—**without raw SQL strings or static DB queries**.

---

## Architectural & Security Flow

```text
  ┌────────────────┐
  │ User Identity  │ (Created via UserService / REST API)
  └───────┬────────┘
          │
          ▼
  ┌────────────────┐
  │  Assigned      │ (Assigned direct & inherited roles: e.g. SUPER_ADMIN,
  │  Roles & Perms │  FINANCE_MANAGER, AUDITOR, LLM, AGENT_STANDARD)
  └───────┬────────┘
          │
          ▼
  ┌────────────────┐
  │ 7-Level        │ (Resolves effective permissions & checks accessibility:
  │ Policy Engine  │  RolePolicyEngine.is_sandbox_accessible(sandbox, identity))
  └───────┬────────┘
          │
    ┌─────┴────────────────────────────────┐
    ▼                                      ▼
┌───────────────────────────┐  ┌───────────────────────────┐
│     MCP Transport Server  │  │   Containerized Sandbox   │
│  (Stdio / HTTP-SSE Stream)│  │   (Code & Command Exec)   │
└───────────────────────────┘  └───────────────────────────┘
```

---

## 1. User Creation & Role Assignment

### A. Pythonic Service & ORM Approach
Create users, assign profiles, and bind dynamic roles using `UserService` and ThinkDome ORM models (`User`, `UserProfile`, `Role`, `UserRole`):

```python
from thinkdome.services.rbac_services import UserService, RoleService

user_svc = UserService()
role_svc = RoleService()

# 1. Create a new user account and profile
user = user_svc.create_user(
    username="finance_auditor_jane",
    email="jane.auditor@enterprise.com",
    password="SecurePassword123!",
    first_name="Jane",
    last_name="Auditor",
    actor="admin"
)

# 2. Dynamically create a enterprise role (or use built-in roles like AUDITOR, FINANCE_MANAGER)
auditor_role = role_svc.create_role(
    name="AuditorRole",
    description="Full read-only audit access across ERP & Sandboxes",
    actor="admin"
)

# 3. Assign role to user
user_svc.assign_role_to_user(
    user_id=user.id,
    role_id=auditor_role.id,
    actor="admin"
)
```

### B. REST API Approach
- **Create User**: `POST /v1/users`
  ```json
  {
    "username": "jane_auditor",
    "email": "jane@enterprise.com",
    "password": "SecurePassword123!",
    "first_name": "Jane",
    "last_name": "Auditor"
  }
  ```

- **Assign Role to User**: `POST /v1/users/{user_id}/roles`
  ```json
  {
    "role_id": "role_auditor_id"
  }
  ```

---

## 2. 7-Level Permission Resolution Order

When a user requests access to a module resource or sandbox action:

1. **Super Admin Check**: Immediate access granted if user holds `SUPER_ADMIN` or `ADMIN` role.
2. **Direct User Permissions**: Explicit grants/denials mapped directly to user ID (`UserPermission`).
3. **Assigned Direct Roles**: Permissions bound to the user's active direct roles.
4. **Inherited Parent Roles**: Recursive role hierarchy tree traversal.
5. **User Group Permissions**: Roles and permissions assigned through `UserGroup` memberships.
6. **Department Permissions**: Access scoping mapped to the user's `Department`.
7. **Default Fallback**: Public default scope checks (`public:read`).

*Note: Changes to roles or permissions immediately invalidate the in-memory `PermissionCache` without requiring an application restart.*

---

## 3. How Users Access MCP (Model Context Protocol)

Users authenticate their session via API headers (`X-User-Role`, `X-Username`, `X-Tenant-Id`, or `Authorization: Bearer <session_token>`). The framework translates incoming headers into a formal `UserIdentity` object.

### A. Local Claude Desktop (Stdio MCP Transport)
Users invoke the stdio transport with site identity context:
```bash
python think mcp --site personal
```

Local `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "thinkdome": {
      "command": "/home/sandbox/ThinkDome/venv/bin/python",
      "args": [
        "/home/sandbox/ThinkDome/think",
        "mcp",
        "--site",
        "personal"
      ]
    }
  }
}
```

### B. Remote / HTTP SSE MCP Transport
Users connect over HTTP/SSE with propagated role headers:
```json
{
  "mcpServers": {
    "thinkdome-remote-sse": {
      "url": "http://192.168.150.91:8000/mcp/sse",
      "headers": {
        "X-Username": "jane_auditor",
        "X-User-Role": "AUDITOR",
        "X-Tenant-Id": "personal"
      }
    }
  }
}
```

---

## 4. How Users Access Containerized Sandboxes

Before a user can execute code (`run_code`) or shell commands (`shell_exec`) inside a sandbox:

1. **Active Sandbox Resolution**: Active sandbox contexts are resolved pythonically via `Sandbox.query().filter(status="active").all()`.
2. **Eligibility Verification**: `RolePolicyEngine.is_sandbox_accessible(sandbox, identity)` checks tenant boundaries, role permissions, and resource limit parameters.
3. **Execution Dispatch**: Authorized executions run within isolated sandbox resource bounds (`memory_mb`, `cpu_cores`, `timeout_sec`, `network_enabled`).

### Example Tool Orchestration Request
```bash
curl -X POST http://127.0.0.1:8000/v1/orchestrate \
  -H "Content-Type: application/json" \
  -H "X-Username: jane_auditor" \
  -H "X-User-Role: AUDITOR" \
  -d '{
    "type": "tool_use",
    "id": "toolu_12345",
    "name": "run_code",
    "input": {
      "code": "print(\"Executing in authorized sandbox context\")",
      "language": "python"
    }
  }'
```
