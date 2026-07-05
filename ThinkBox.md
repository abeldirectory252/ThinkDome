# ThinkDome Sandbox Platform — System Specification Prompt

> Use this document as a complete product and engineering specification prompt
> for building or extending the ThinkDome multi-sandbox execution platform.


.\venv\Scripts\python -m thinkdome.cli serve --host 127.0.0.1 --port 8000
---

## 1. System Overview

Build a **multi-tenant sandbox execution platform** where authenticated users can:

- Spin up **multiple isolated Docker containers** as personal sandbox environments
- Optionally provision a **VirtualBox VM** for full OS-level isolation
- Interact with their sandboxes via **six distinct token types**, each scoped to a specific surface
- Execute Python code, manage files, and operate a full Linux terminal — all through a clean web UI and open API

Each user owns their own sandboxes. Each sandbox is isolated: separate filesystem, separate network policy, separate resource limits. No sandbox can access another user's data or another sandbox's filesystem.

---

## 2. Authentication & Session Model

### 2.1 Web Login Token (Session Token)

- Issued at login via `POST /v1/auth/login`
- Short-lived JWT (default: 8 hours), refresh via silent re-auth
- Scopes: full dashboard access, sandbox management, file workspace, log viewer
- Stored in `localStorage` on the client (`thinkdome_token`)
- Used in `Authorization: Bearer <token>` header on all dashboard API calls
- Auto-logout on 401 response anywhere in the app

### 2.2 Sandbox Tokens (Six Types)

Each token type is issued per-sandbox and scoped to exactly what that surface needs.
All sandbox tokens are prefixed to identify their type: `td_llm_`, `td_web_`, `td_sdk_`, `td_curl_`, `td_orch_`, `td_ide_`.

| Token Type | Prefix | Allowed Operations | Typical Consumer |
|---|---|---|---|
| **LLM Token** | `td_llm_` | `run_code` only | Claude / GPT tool calls |
| **Website User Token** | `td_web_` | `run_code`, `read_file`, `write_file`, `list_dir` | Web UI file workspace |
| **Python SDK Token** | `td_sdk_` | All file + code tools, structured JSON responses | `thinkdome` Python package |
| **cURL Token** | `td_curl_` | All file + code tools, raw HTTP | Shell scripts, CI pipelines |
| **Full Orchestrator Token** | `td_orch_` | All tools, sandbox admin, log access | Backend services, power users |
| **IDE Token** | `td_ide_` | All tools + **Linux terminal (PTY)**, package install, process management | Web IDE, VS Code extension |

---

## 3. Sandbox Types

### 3.1 Docker Sandbox (Default)

**Technology:** Docker Engine, one container per sandbox instance.

**Isolation model:**
- Each sandbox = one named Docker container
- Separate overlayfs filesystem per container (no shared volumes between users)
- User workspace mounted at `/workspace` inside the container
- Container runs as non-root user (`sandboxuser`, UID 1000)

**Resource limits (configurable at creation):**

```
memory_mb:        128 | 256 | 512 | 1024 | 2048   (default: 256)
cpu_cores:        0.5 | 1.0 | 2.0 | 4.0           (default: 1.0)
timeout_sec:      30 – 3600                        (default: 300)
network_enabled:  true | false                     (default: false)
```

**Security flags applied to every container:**
```
--security-opt no-new-privileges
--cap-drop ALL
--cap-add NET_BIND_SERVICE   (only if network_enabled)
--read-only /                (except /workspace and /tmp)
--tmpfs /tmp:size=64m
--pids-limit 128
--ulimit nofile=1024:1024
```

**Base images available:**
```
python:3.12-slim    (default)
python:3.11-slim
ubuntu:22.04
node:20-slim
golang:1.22-alpine
```

**Warm pool:** maintain a pool of 3 pre-warmed containers per active user to reduce cold-start latency. Containers are recycled after each execution (filesystem reset) unless the session is stateful (IDE mode).

**Lifecycle states:**
```
creating → active → stopped → terminated
```

---

### 3.2 VirtualBox Sandbox (Optional Add-on)

**Technology:** VirtualBox 7.x with headless VM provisioning via `VBoxManage`.

**When to use:** kernel-level isolation requirements, running non-Python runtimes, OS-level testing, full root access inside the sandbox, or when Docker container escape risk is a concern.

**Provisioning flow:**
1. User requests a VirtualBox sandbox from the dashboard
2. Backend clones a base `.ova` snapshot (Ubuntu 22.04 minimal, pre-baked)
3. VM is registered and started headless: `VBoxManage startvm <name> --type headless`
4. SSH keypair generated per-VM; backend holds private key, exposes shell via WebSocket PTY
5. User workspace synced via SFTP into `/home/sandboxuser/workspace`

**Resource limits (configurable):**
```
memory_mb:        512 | 1024 | 2048 | 4096   (default: 1024)
cpu_cores:        1 | 2 | 4                  (default: 1)
disk_gb:          10 | 20 | 40               (default: 10)
network_enabled:  true | false               (default: false)
```

**Exposed API surface:** identical to Docker sandbox — same `run_code`, `read_file`, `write_file`, `list_dir` tools. Execution is routed over SSH instead of `docker exec`. From the client's perspective, the token and API calls are the same.

**Cost:** displayed to user as `$X.XXX/hr` on the sandbox card. VirtualBox sandboxes cost ~3–5× more than equivalent Docker sandboxes due to full OS overhead.

**Lifecycle states:**
```
provisioning → running → paused → stopped → terminated
```

---

## 4. Token Management

### 4.1 Issuing Tokens

**Endpoint:** `POST /v1/admin/sandboxes/{sandbox_id}/tokens`

**Request body:**
```json
{
  "token_type": "llm | web | sdk | curl | orchestrator | ide",
  "display_name": "My LLM Key",
  "expires_at": "2025-12-31T00:00:00Z"   // null = never
}
```

**Response:** token is returned **once only** at creation. It is not stored in plaintext — only the masked version (`td_llm_••••••••Xk9z`) is kept.

### 4.2 Token Scope Enforcement

All tokens pass through a **scope middleware** at the `/v1/orchestrate` endpoint before reaching the sandbox.

```
Incoming request
    │
    ├─ Decode token → extract { user_id, sandbox_id, token_type, scopes[] }
    │
    ├─ Check sandbox ownership: token.user_id == sandbox.owner_id
    │
    ├─ Check tool permission:
    │     LLM token      → allow: run_code
    │     Web token      → allow: run_code, read_file, write_file, list_dir
    │     SDK token      → allow: run_code, read_file, write_file, list_dir, web_search
    │     cURL token     → allow: run_code, read_file, write_file, list_dir, web_search
    │     Orch token     → allow: ALL tools + sandbox admin endpoints
    │     IDE token      → allow: ALL tools + pty_open, pty_input, pty_resize, pty_close
    │
    └─ Route to correct sandbox backend (Docker or VirtualBox)
```

### 4.3 Token Revocation

**Endpoint:** `POST /v1/admin/tokens/{token_id}/revoke`

Immediate effect — revoked tokens return `401 Unauthorized` on next request. No grace period.

---

## 5. Core Tool API

All tools are invoked via a unified `POST /v1/orchestrate` with a ToolUse payload:

```json
{
  "type": "tool_use",
  "id": "toolu_unique_id",
  "name": "<tool_name>",
  "input": { }
}
```

### 5.1 Tool Reference

#### `run_code`
Execute Python (or other supported language) inside the sandbox.
```json
{
  "name": "run_code",
  "input": {
    "language": "python",
    "code": "print('Hello ThinkDome')",
    "timeout_sec": 30
  }
}
```
Response: `{ "stdout": "...", "stderr": "...", "exit_code": 0, "duration_ms": 142 }`

#### `read_file`
Read a file from the user's workspace.
```json
{ "name": "read_file", "input": { "path": "analysis.py" } }
```

#### `write_file`
Create or overwrite a file in the workspace.
```json
{ "name": "write_file", "input": { "path": "output.csv", "content": "col1,col2\n1,2" } }
```

#### `list_dir`
List files and directories at a given path.
```json
{ "name": "list_dir", "input": { "path": "." } }
```
Response: array of `{ name, path, type, size_bytes }`

#### `web_search` *(SDK / cURL / Orchestrator / IDE tokens only)*
```json
{ "name": "web_search", "input": { "query": "...", "max_results": 5 } }
```

#### `install_package` *(IDE / Orchestrator tokens only)*
Install a pip or apt package into the sandbox.
```json
{ "name": "install_package", "input": { "manager": "pip", "package": "pandas==2.2.0" } }
```

---

## 6. IDE Token — Terminal & Web IDE

The IDE token enables a full **Linux PTY session** inside the sandbox. This is the token that powers the web IDE surface.

### 6.1 PTY WebSocket Protocol

Connect: `WS /v1/pty?token=td_ide_<token>&sandbox_id=<id>`

**Client → Server messages:**
```json
{ "type": "input",  "data": "ls -la\n" }
{ "type": "resize", "cols": 220, "rows": 50 }
{ "type": "ping" }
```

**Server → Client messages:**
```json
{ "type": "output", "data": "\u001b[32mroot@sandbox\u001b[0m:~$ " }
{ "type": "exit",   "code": 0 }
{ "type": "pong" }
```

### 6.2 Web IDE Features (IDE Token Surface)

The web IDE is a browser-based environment exposed at `/ide` (or as an embeddable panel). It must include:

**File tree panel (left sidebar):**
- Recursive directory listing via `list_dir`
- Click to open files in editor
- Right-click context menu: rename, delete, new file, new folder
- Drag-and-drop reorder
- File upload from local machine

**Code editor (center panel):**
- Monaco Editor (same engine as VS Code)
- Syntax highlighting for Python, JS, Bash, JSON, YAML, Markdown
- Auto-save on change (debounced 1.5s) via `write_file`
- Multi-tab support (one tab per open file)
- Diff view for comparing file versions

**Terminal panel (bottom panel):**
- Full xterm.js PTY connected via WebSocket using IDE token
- Supports ANSI colors, cursor movement, Ctrl+C, Ctrl+D
- Resizable height via drag handle
- Multiple terminal tabs
- `python`, `pip`, `bash`, `git`, `curl`, `vim`, `nano` all available

**Run panel (right sidebar or overlay):**
- One-click run of currently open Python file
- Output displayed inline (stdout / stderr colored)
- Run history with timestamps

**Package manager panel:**
- Search PyPI, install via `install_package` tool
- Installed packages list with version badges

---

## 7. File Workspace

Each sandbox has an isolated `/workspace` directory. This is the user's persistent storage within that sandbox.

**File operations exposed:**

| Operation | Tool | Token Required |
|---|---|---|
| List files | `list_dir` | Web, SDK, cURL, Orch, IDE |
| Read file | `read_file` | Web, SDK, cURL, Orch, IDE |
| Write/create file | `write_file` | Web, SDK, cURL, Orch, IDE |
| Delete file | `delete_file` | Orch, IDE |
| Rename file | `rename_file` | Orch, IDE |
| Upload file | multipart `POST /v1/workspace/upload` | Web, Orch, IDE |
| Download file | `GET /v1/workspace/download?path=<path>` | Web, Orch, IDE |

**Storage quotas:**
- Docker sandbox: 1 GB per sandbox (configurable)
- VirtualBox sandbox: up to disk_gb configured at creation

**File filtering (clean workspace view):**
System files hidden from the UI by default: `.git`, `venv`, `__pycache__`, `.env`, `*.pyc`, `node_modules`.

---

## 8. Sandbox Management Dashboard

### 8.1 Sandbox Card (UI)

Each sandbox displays as a card showing:
- Name and type badge (`DOCKER` or `VIRTUALBOX`)
- Status badge: `ACTIVE` / `STOPPED` / `CREATING` / `TERMINATED`
- Resource summary: RAM, vCPU, timeout, network status
- Cost per hour
- Sandbox ID (monospaced, copyable)

**Card actions:**
- **Open in Console** → switches to console tab with this sandbox selected
- **Open IDE** → opens IDE panel (IDE token auto-issued if none exists)
- **Stop / Start** toggle
- **Terminate** (destructive, requires confirmation)

### 8.2 Create Sandbox Modal

**Docker sandbox form fields:**
```
Name:             [text input]
Runtime image:    [dropdown: python:3.12-slim | ubuntu:22.04 | node:20-slim | ...]
RAM:              [dropdown: 128MB | 256MB | 512MB | 1GB | 2GB]
CPU cores:        [dropdown: 0.5 | 1.0 | 2.0 | 4.0]
Timeout:          [slider: 30s – 3600s]
Network enabled:  [toggle]
──────────────────────────────
Estimated cost:   $0.032/hr   ← live calculation
```

**VirtualBox sandbox form fields:**
```
Name:             [text input]
Base OS:          [dropdown: Ubuntu 22.04 | Ubuntu 20.04]
RAM:              [dropdown: 512MB | 1GB | 2GB | 4GB]
CPU cores:        [dropdown: 1 | 2 | 4]
Disk size:        [dropdown: 10GB | 20GB | 40GB]
Network enabled:  [toggle]
──────────────────────────────
Estimated cost:   $0.115/hr   ← live calculation
[⚠ VirtualBox sandboxes take 45–90s to provision]
```

**Cost formula:**
```
Docker:     (memory_mb / 128) × $0.010 + cpu_cores × $0.020 + (network ? $0.005 : 0)
VirtualBox: (memory_mb / 512) × $0.040 + cpu_cores × $0.035 + (disk_gb / 10) × $0.008 + (network ? $0.010 : 0)
```

---

## 9. Token Management Dashboard

### 9.1 Token Table (per sandbox)

Each sandbox has its own token management section showing:

| Column | Content |
|---|---|
| Display Name | User-defined label |
| Type | Badge: `LLM` / `WEB` / `SDK` / `CURL` / `ORCH` / `IDE` |
| Token Preview | `td_llm_••••••••Xk9z` |
| Created | Relative timestamp |
| Expires | Date or `Never` |
| Status | `ACTIVE` / `REVOKED` |
| Actions | **Revoke** button (active tokens only) |

### 9.2 Create Token Form

```
Display Name:  [text input]  e.g. "My Claude Integration"
Token Type:    [radio cards with icon + description for each type]
Expires At:    [date picker, optional]
──────────────
[Generate Token]
```

After generation:
- Token displayed **once** in a reveal banner with copy button
- Banner auto-dismisses or user manually closes it
- Warning: "Store this token securely. It will not be shown again."

---

## 10. SDK Usage Examples

### Python SDK (`td_sdk_` token)

```python
from thinkdome import Sandbox

sb = Sandbox(token="td_sdk_xxxxxxxxxxxx")

# Execute code
result = sb.run("print('Hello from SDK')")
print(result.stdout)

# File operations
sb.write_file("hello.py", "print('saved!')")
content = sb.read_file("hello.py")
files = sb.list_dir(".")

# Context manager (auto-cleanup)
with Sandbox(token="td_sdk_xxxxxxxxxxxx") as sb:
    sb.run("import pandas as pd; print(pd.__version__)")
```

### cURL (`td_curl_` token)

```bash
# Run Python code
curl -X POST https://thinkdome.io/v1/orchestrate \
  -H "Authorization: Bearer td_curl_xxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "tool_use",
    "id": "curl_001",
    "name": "run_code",
    "input": { "language": "python", "code": "print(2 ** 32)" }
  }'

# Read a file
curl -X POST https://thinkdome.io/v1/orchestrate \
  -H "Authorization: Bearer td_curl_xxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"type":"tool_use","id":"curl_002","name":"read_file","input":{"path":"results.csv"}}'
```

### LLM Integration (Anthropic Claude `td_llm_` token)

```python
import anthropic

client = anthropic.Anthropic()

tools = [{
    "name": "run_code",
    "description": "Execute Python code in a secure sandbox",
    "input_schema": {
        "type": "object",
        "properties": {
            "language": { "type": "string", "enum": ["python"] },
            "code":     { "type": "string" }
        },
        "required": ["language", "code"]
    }
}]

# Claude calls run_code → your backend forwards to ThinkDome with td_llm_ token
# Only run_code is permitted — Claude cannot access the filesystem
```

---

## 11. API Endpoints Reference

### Auth
```
POST   /v1/auth/login              → { access_token, username }
POST   /v1/auth/register           → { message }
POST   /v1/auth/logout             → { message }
```

### Sandboxes
```
GET    /v1/admin/sandboxes              → list all user sandboxes
POST   /v1/admin/sandboxes             → create sandbox (Docker or VirtualBox)
POST   /v1/admin/sandboxes/{id}/toggle → start/stop
DELETE /v1/admin/sandboxes/{id}        → terminate permanently
```

### Sandbox Tokens
```
GET    /v1/admin/sandboxes/{id}/tokens              → list tokens for sandbox
POST   /v1/admin/sandboxes/{id}/tokens              → issue new token
POST   /v1/admin/tokens/{token_id}/revoke           → revoke token
```

### Orchestrator
```
POST   /v1/orchestrate             → execute a tool (all sandbox token types)
```

### IDE / Terminal
```
WS     /v1/pty                     → PTY WebSocket (IDE token only)
```

### File Workspace
```
POST   /v1/workspace/upload        → multipart file upload
GET    /v1/workspace/download      → file download by path
```

### Logs & Audit
```
GET    /v1/admin/logs              → request execution logs
POST   /v1/admin/logs/clear        → clear all logs
GET    /v1/admin/audits            → security audit trail
```

### Schema
```
GET    /orchestrator_schema.json   → JSON schema for ToolUse payloads
```

---

## 12. Security Requirements

- All tokens hashed (SHA-256) before storage — plaintext never persisted
- Web session tokens are JWT signed with RS256; sandbox tokens are opaque random strings
- All API endpoints require HTTPS — HTTP requests rejected at edge
- Rate limiting: 60 req/min per token (LLM), 300 req/min (Orch/IDE)
- Sandbox containers never share a Docker network namespace
- `docker exec` calls use `--user sandboxuser` — never root
- VirtualBox VMs run in host-only or NAT network — not bridged to internal network
- All file paths validated against path traversal (`../../etc/passwd` → rejected)
- Code execution timeout enforced at container level (SIGKILL after timeout_sec)
- Audit log is append-only — no delete endpoint exposed

---

## 13. Glossary

| Term | Meaning |
|---|---|
| Sandbox | An isolated execution environment (Docker container or VirtualBox VM) owned by one user |
| Token | A scoped credential tied to one sandbox and one surface |
| Workspace | The persistent `/workspace` directory inside a sandbox |
| PTY | Real shell | the shell session used by IDE tokens |
| Orchestrator | The API layer that routes ToolUse calls to the correct sandbox backend |
| Warm pool | Pre-started containers held ready to reduce execution latency |
| Scope | The set of tools a token is permitted to invoke |