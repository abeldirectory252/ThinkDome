# ThinkDome — REST API & Python SDK Reference

> Comprehensive API documentation for ThinkDome's HTTP/WebSocket endpoints and Python SDK.

---

## 1. Authentication & Headers

ThinkDome supports dual authentication methods depending on whether you are integrating an autonomous agent via an API Key or accessing via a browser session:

### 1.1 Bearer Token / API Key
Pass the API token in the `Authorization` header:
```http
Authorization: Bearer <your_api_token_or_jwt>
```
Or pass the custom header:
```http
X-API-Key: <your_api_key>
```

### 1.2 Session Cookie
When using the Web Dashboard, requests automatically use the `session_id` cookie validated against the Redis/SQLite session cache.

---

## 2. API Endpoints

### 2.1 Authentication (`/api/auth`)

#### `POST /api/auth/login`
Authenticate a user and obtain a session/JWT token.
- **Request Body**:
  ```json
  {
    "username": "admin",
    "password": "your_secure_password"
  }
  ```
- **Response `200 OK`**:
  ```json
  {
    "status": "success",
    "token": "eyJhbGciOiJIUzI1NiIsIn...",
    "user": {
      "id": "usr_01",
      "username": "admin",
      "role": "Administrator"
    }
  }
  ```

#### `GET /api/auth/me`
Retrieve profile, permissions, and active quota for current session.
- **Response `200 OK`**:
  ```json
  {
    "user_id": "usr_01",
    "username": "admin",
    "role": "Administrator",
    "quotas": {
      "max_sandboxes": 10,
      "max_memory_mb": 4096,
      "storage_quota_mb": 1024
    }
  }
  ```

---

### 2.2 Sandbox Execution & Lifecycle (`/api/sandbox`)

#### `POST /api/sandbox/run`
Execute code synchronously or stream output.
- **Request Body**:
  ```json
  {
    "code": "print('Hello from ThinkDome')",
    "language": "python",
    "backend": "docker",
    "timeout": 30,
    "memory_mb": 512,
    "network_egress": "deny",
    "dependencies": ["requests", "numpy"]
  }
  ```
- **Response `200 OK`**:
  ```json
  {
    "execution_id": "exec_9a8b7c",
    "exit_code": 0,
    "stdout": "Hello from ThinkDome\n",
    "stderr": "",
    "duration_ms": 342,
    "status": "completed",
    "resource_usage": {
      "memory_peak_mb": 42.1,
      "cpu_time_ms": 118
    }
  }
  ```

#### `POST /api/sandbox/create`
Create a stateful or warm ephemeral sandbox instance with lease TTL.
- **Request Body**:
  ```json
  {
    "name": "agent-worker-1",
    "backend": "docker",
    "memory_mb": 512,
    "lease_ttl_minutes": 60,
    "dependencies": ["pandas"]
  }
  ```
- **Response `201 Created`**:
  ```json
  {
    "sandbox_id": "sbx_f4e3d2",
    "name": "agent-worker-1",
    "backend": "docker",
    "status": "running",
    "created_at": "2026-09-20T12:00:00Z",
    "expires_at": "2026-09-20T13:00:00Z"
  }
  ```

#### `GET /api/sandbox/list`
List all sandboxes for the authenticated owner (or all for Administrator).
- **Response `200 OK`**:
  ```json
  [
    {
      "sandbox_id": "sbx_f4e3d2",
      "name": "agent-worker-1",
      "backend": "docker",
      "status": "running",
      "memory_mb": 512,
      "expires_at": "2026-09-20T13:00:00Z"
    }
  ]
  ```

#### `DELETE /api/sandbox/{sandbox_id}`
Terminate and clean up sandbox resources.
- **Response `200 OK`**:
  ```json
  {
    "status": "destroyed",
    "sandbox_id": "sbx_f4e3d2"
  }
  ```

---

### 2.3 FileBox Virtual Filesystem (`/api/filebox`)

#### `GET /api/filebox/list`
List virtual files stored in the user or sandbox isolated workspace.
- **Query Parameters**:
  - `path`: Virtual directory path (default: `/`)
- **Response `200 OK`**:
  ```json
  {
    "path": "/",
    "files": [
      {
        "name": "dataset.csv",
        "size_bytes": 1048576,
        "updated_at": "2026-09-20T11:45:00Z",
        "type": "file"
      }
    ]
  }
  ```

#### `POST /api/filebox/upload`
Upload a file to the FileBox virtual drive (`multipart/form-data`).
- **Form Data**:
  - `file`: binary payload
  - `destination`: `/uploads/dataset.csv`
- **Response `201 Created`**:
  ```json
  {
    "status": "uploaded",
    "path": "/uploads/dataset.csv",
    "size_bytes": 1048576
  }
  ```

---

### 2.4 Model Context Protocol (MCP) (`/api/mcp`)

#### `GET /api/mcp/tools`
Retrieve list of registered agent tools conforming to the MCP specification.
- **Response `200 OK`**:
  ```json
  {
    "tools": [
      {
        "name": "thinkdome_execute",
        "description": "Execute Python code in isolated sandbox",
        "inputSchema": {
          "type": "object",
          "properties": {
            "code": {"type": "string"}
          },
          "required": ["code"]
        }
      },
      {
        "name": "telegram_notify",
        "description": "Send alert message via Telegram bot MCP",
        "inputSchema": {
          "type": "object",
          "properties": {
            "chat_id": {"type": "string"},
            "message": {"type": "string"}
          },
          "required": ["chat_id", "message"]
        }
      }
    ]
  }
  ```

#### `POST /api/mcp/execute`
Invoke an MCP tool with audit recording.
- **Request Body**:
  ```json
  {
    "tool": "thinkdome_execute",
    "arguments": {
      "code": "print(sum(range(100)))"
    }
  }
  ```
- **Response `200 OK`**:
  ```json
  {
    "status": "success",
    "result": "4950\n"
  }
  ```

---

## 3. WebSocket Terminal (`/ws/sandbox/{id}/terminal`)

Stream interactive bidirectional terminal sessions (PTY) inside a running sandbox.

- **Protocol**: WebSocket (binary or JSON message frames)
- **Message Types**:
  - `{"type": "stdin", "data": "ls -la\n"}`
  - `{"type": "resize", "cols": 120, "rows": 40}`
- **Server Response**:
  - `{"type": "stdout", "data": "total 12\ndrwxr-xr-x ..."}`

---

## 4. Python SDK Quick Reference

### 4.1 Running Code

```python
from thinkdome import Sandbox

# Initialize sandbox with Docker backend and resource restrictions
sandbox = Sandbox(
    backend="docker",
    memory_limit="512M",
    cpu_limit="1.0",
    timeout=30,
    network_egress=False
)

result = sandbox.run("""
import math
print("Pi =", math.pi)
""")

print("Exit code:", result.exit_code)
print("Output:", result.stdout)
sandbox.close()
```

### 4.2 Context Manager

```python
with Sandbox(backend="subprocess", timeout=10) as sb:
    res = sb.run("print('Ephemeral execution done!')")
    print(res.stdout)
```

### 4.3 Virtual File Operations

```python
with Sandbox(backend="docker") as sb:
    sb.files.write("input.txt", "Data to process")
    sb.run("with open('input.txt') as f: print(f.read())")
    output = sb.files.read("input.txt")
```
