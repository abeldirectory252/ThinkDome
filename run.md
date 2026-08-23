# ThinkDome — Application Execution & Testing Guide

This guide provides step-by-step instructions to run the ThinkDome server, execute tests, and perform administrative operations (User Creation, Role Assignment, User Deletion, MCP & Sandbox tool execution) using `curl` and Python ORM.

---

## 1. How to Start ThinkDome

### A. Start the Web & REST API Server
Run the FastAPI production server on port 8000:
```bash
./venv/bin/python think serve --port 8000
```
- **Web UI Interface**: `http://127.0.0.1:8000/login.html` (or `http://127.0.0.1:8000/`)
- **Interactive Swagger OpenAPI Docs**: `http://127.0.0.1:8000/docs`

### B. Start Model Context Protocol (MCP) Stdio Server
Launch the stdio transport server for local AI assistants (e.g. Claude Desktop):
```bash
./venv/bin/python think mcp --site think.local
```

### C. Run Full Pytest Test Suite
Execute all 103 automated tests verifying RBAC, Sandboxes, ORM, and MCP:
```bash
./venv/bin/pytest
```

---

## 2. Dynamic User & Role Management (cURL Examples)

### Step 1: User Login (Obtain Session Bearer Token)
```bash
curl -X POST http://127.0.0.1:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "password"
  }'
```
*Response:*
```json
{
  "access_token": "td_sess_9a8b7c6d5e...",
  "token_type": "bearer",
  "username": "admin"
}
```
Save your token: `TOKEN="td_sess_9a8b7c6d5e..."`

---

### Step 2: Create a New User Account
Create a new user with an initial institutional role (e.g. `FINANCE_MANAGER`, `AUDITOR`, `AGENT_STANDARD`):
```bash
curl -X POST http://127.0.0.1:8000/v1/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "username": "jane_auditor",
    "email": "jane.auditor@enterprise.com",
    "password": "SecurePassword123!",
    "first_name": "Jane",
    "last_name": "Auditor"
  }'
```
*Response:*
```json
{
  "status": "success",
  "user": {
    "id": "usr_a1b2c3d4e5",
    "username": "jane_auditor",
    "email": "jane.auditor@enterprise.com",
    "status": "ACTIVE"
  }
}
```
Save user ID: `USER_ID="usr_a1b2c3d4e5"`

---

### Step 3: Create a Dynamic Enterprise Role
Create a custom role with specific permission scopes:
```bash
curl -X POST http://127.0.0.1:8000/v1/roles \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "LeadAuditor",
    "description": "Lead auditor with read-only inspection access across ERP and Sandboxes",
    "is_system": false
  }'
```
*Response:*
```json
{
  "status": "success",
  "role": {
    "id": "role_f9e8d7c6",
    "name": "LeadAuditor",
    "description": "Lead auditor with read-only inspection access across ERP and Sandboxes"
  }
}
```
Save role ID: `ROLE_ID="role_f9e8d7c6"`

---

### Step 4: Assign Role to User
Bind the created role to the user account:
```bash
curl -X POST http://127.0.0.1:8000/v1/users/$USER_ID/roles \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "role_id": "role_f9e8d7c6"
  }'
```
*Response:*
```json
{
  "status": "success",
  "message": "Role assigned to user successfully"
}
```

---

### Step 5: List All Users & Check Assigned Roles
```bash
curl -X GET http://127.0.0.1:8000/v1/users \
  -H "Authorization: Bearer $TOKEN"
```

---

### Step 6: Disable / Enable User Account
Temporarily suspend user access without deleting data:
```bash
curl -X PUT http://127.0.0.1:8000/v1/users/$USER_ID/status \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "status": "DISABLED"
  }'
```

---

### Step 7: Delete User Account
Soft-delete a user account pythonically:
```bash
curl -X DELETE http://127.0.0.1:8000/v1/users/$USER_ID \
  -H "Authorization: Bearer $TOKEN"
```
*Response:*
```json
{
  "status": "success",
  "message": "User usr_a1b2c3d4e5 deleted successfully"
}
```

---

## 3. Pythonic Programmatic Examples (`UserService` & ORM)

You can also run administrative operations directly in Python scripts:

```python
from thinkdome.services.rbac_services import UserService, RoleService

user_svc = UserService()
role_svc = RoleService()

# 1. Create user pythonically
user = user_svc.create_user(
    username="john_developer",
    email="john@enterprise.com",
    password="DevPassword123!",
    actor="admin"
)
print(f"Created User: {user.username} (ID: {user.id})")

# 2. Get role
dev_role = role_svc.get_role_by_name("AGENT_STANDARD")

# 3. Assign role to user
user_svc.assign_role_to_user(
    user_id=user.id,
    role_id=dev_role.id,
    actor="admin"
)

# 4. Disable user account
user_svc.update_user_status(
    user_id=user.id,
    status="DISABLED",
    actor="admin"
)

# 5. Delete user account
user_svc.delete_user(
    user_id=user.id,
    actor="admin"
)
print(f"Deleted User: {user.username}")
```

---

## 4. Inspect Audit Trail Logs

All user creation, role modification, login attempts, and user deletions are automatically recorded in the audit log:

```bash
curl -X GET "http://127.0.0.1:8000/v1/audit/logs?limit=10" \
  -H "Authorization: Bearer $TOKEN"
```