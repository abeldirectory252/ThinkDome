# ThinkDome — Architecture Specification
> Multi-Tenant Sandbox Execution Platform · Designed for Claude Opus 4.6

---

## 0. North Star

ThinkDome is a **multi-tenant, token-scoped sandbox platform** where every user gets isolated Docker containers (and optionally VirtualBox VMs) to run code, manage files, and operate a full Linux terminal — reachable from a web UI, a Python SDK, raw cURL, an SSH client, or an LLM tool-call, each via a purpose-scoped credential.

---

## 1. High-Level System Map

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT SURFACES                          │
│                                                                 │
│  Browser (Web UI)   SSH Client   Python SDK   cURL / CI   LLM  │
└────────┬──────────────────┬────────────┬──────────┬────────┬───┘
         │                  │            │          │        │
         │ HTTPS / WSS      │ TCP:22     │ HTTPS    │ HTTPS  │ HTTPS
         ▼                  ▼            ▼          ▼        ▼
┌─────────────────────────────────────────────────────────────────┐
│                        EDGE / GATEWAY                           │
│   TLS termination · Rate limiting · Token type routing          │
│   Web Session JWT ──► Dashboard API                             │
│   Sandbox tokens  ──► Orchestrator API                          │
│   IDE token (SSH) ──► SSH Gateway (sshd proxy)                  │
└─────────────────────────────────────────────────────────────────┘
         │                  │            │
         ▼                  ▼            ▼
┌────────────────┐  ┌───────────────┐  ┌──────────────────────────┐
│  Dashboard API │  │  SSH Gateway  │  │     Orchestrator API      │
│  /v1/auth/*    │  │  port 22 →    │  │  POST /v1/orchestrate     │
│  /v1/admin/*   │  │  PTY bridge   │  │  Scope middleware          │
│  (JWT auth)    │  │  (IDE token)  │  │  Tool router              │
└────────┬───────┘  └──────┬────────┘  └────────────┬─────────────┘
         │                  │                        │
         └──────────────────┴────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SANDBOX BACKENDS                           │
│                                                                 │
│   ┌──────────────────────────┐   ┌───────────────────────────┐  │
│   │    Docker Engine         │   │    VirtualBox Host        │  │
│   │  Container per sandbox   │   │  Headless VM per sandbox  │  │
│   │  /workspace overlay FS   │   │  SSH → /home/sandboxuser  │  │
│   │  Warm pool (3/user)      │   │  SFTP workspace sync      │  │
│   └──────────────────────────┘   └───────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                     PERSISTENCE LAYER                           │
│  PostgreSQL (users, sandboxes, tokens, audit)                   │
│  Redis (session cache, warm-pool state, rate-limit counters)    │
│  Object store / local FS (workspace file blobs, VM snapshots)   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Authentication & Session Model

### 2.1 Web Login (Session Token)

| Property | Value |
|---|---|
| Endpoint | `POST /v1/auth/login` |
| Token format | RS256-signed JWT |
| TTL | 8 hours (silent refresh) |
| Storage | `localStorage` → `thinkdome_token` |
| Header | `Authorization: Bearer <jwt>` |
| Auto-logout trigger | Any `401` response |

The web session token gates **only** the Dashboard API (`/v1/admin/*`) — it cannot call the Orchestrator directly.

### 2.2 The Six Sandbox Token Types

All sandbox tokens are **opaque random strings**, SHA-256-hashed before storage. Plaintext is returned exactly once at creation.

```
td_llm_   LLM Token            ─── run_code only
td_web_   Website User Token   ─── run_code + file CRUD
td_sdk_   Python SDK Token     ─── file CRUD + web_search
td_curl_  cURL Token           ─── file CRUD + web_search (raw HTTP)
td_orch_  Orchestrator Token   ─── ALL tools + sandbox admin
td_ide_   IDE Token            ─── ALL tools + PTY (terminal)
```

Scope matrix:

| Tool | LLM | Web | SDK | cURL | Orch | IDE |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `run_code` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `read_file` | | ✓ | ✓ | ✓ | ✓ | ✓ |
| `write_file` | | ✓ | ✓ | ✓ | ✓ | ✓ |
| `list_dir` | | ✓ | ✓ | ✓ | ✓ | ✓ |
| `web_search` | | | ✓ | ✓ | ✓ | ✓ |
| `install_package` | | | | | ✓ | ✓ |
| `delete_file` / `rename_file` | | | | | ✓ | ✓ |
| PTY (`pty_open/input/resize/close`) | | | | | | ✓ |
| Sandbox admin endpoints | | | | | ✓ | |

---

## 3. Sandbox Types

### 3.1 Docker Sandbox (Default)

**One container = one sandbox.** No shared volumes between users or sandboxes.

```
Base images:
  python:3.12-slim  (default)
  python:3.11-slim
  ubuntu:22.04
  node:20-slim
  golang:1.22-alpine

User inside container: sandboxuser (UID 1000) — never root

Security flags applied to every container:
  --security-opt no-new-privileges
  --cap-drop ALL
  --cap-add NET_BIND_SERVICE    (if network_enabled)
  --read-only /                 (except /workspace and /tmp)
  --tmpfs /tmp:size=64m
  --pids-limit 128
  --ulimit nofile=1024:1024

Resource limits (selectable at creation):
  memory_mb:       128 | 256 | 512 | 1024 | 2048   (default 256)
  cpu_cores:       0.5 | 1.0 | 2.0 | 4.0           (default 1.0)
  timeout_sec:     30 – 3600                        (default 300)
  network_enabled: true | false                     (default false)
```

**Warm pool:** 3 pre-warmed containers per active user. On each non-IDE execution the filesystem is reset (overlayfs rollback) before returning the container to the pool.

**Lifecycle:**
```
creating ──► active ──► stopped ──► terminated
```

### 3.2 VirtualBox Sandbox (Optional Add-on)

Full OS-level isolation. Identical API surface as Docker — execution routes over SSH instead of `docker exec`.

```
Provisioning flow:
  1. Clone base .ova snapshot (Ubuntu 22.04 minimal)
  2. VBoxManage startvm <name> --type headless
  3. Generate per-VM SSH keypair (backend holds private key)
  4. Expose shell via WebSocket PTY or direct SSH
  5. Sync workspace via SFTP → /home/sandboxuser/workspace

Resource limits:
  memory_mb:       512 | 1024 | 2048 | 4096   (default 1024)
  cpu_cores:       1 | 2 | 4                  (default 1)
  disk_gb:         10 | 20 | 40               (default 10)
  network_enabled: true | false               (default false)

Provision time: 45–90 seconds
Cost:           ~3–5× equivalent Docker sandbox

Lifecycle: provisioning ──► running ──► paused ──► stopped ──► terminated
```

### 3.3 Cost Formula

```
Docker:
  (memory_mb / 128) × $0.010
  + cpu_cores × $0.020
  + (network_enabled ? $0.005 : 0)

VirtualBox:
  (memory_mb / 512) × $0.040
  + cpu_cores × $0.035
  + (disk_gb / 10) × $0.008
  + (network_enabled ? $0.010 : 0)
```

---

## 4. Request Lifecycle — Orchestrator

Every tool call from any token type follows this single path:

```
Client request
    │
    ├─ 1. TLS termination at edge
    │
    ├─ 2. Rate limit check (Redis counter)
    │       LLM token  → 60 req/min
    │       Orch/IDE   → 300 req/min
    │
    ├─ 3. Token decode
    │       extract { user_id, sandbox_id, token_type, scopes[] }
    │
    ├─ 4. Ownership check
    │       token.user_id == sandbox.owner_id  (else 403)
    │
    ├─ 5. Scope check
    │       requested tool ∈ token.scopes[]    (else 403)
    │
    ├─ 6. Sandbox backend routing
    │       Docker  → docker exec --user sandboxuser
    │       VirtualBox → SSH exec via stored keypair
    │
    ├─ 7. Path traversal validation on all file paths
    │
    ├─ 8. Execution with timeout enforcement (SIGKILL at timeout_sec)
    │
    └─ 9. Append-only audit log entry written
```

**Unified tool payload (all token types):**
```json
POST /v1/orchestrate
Authorization: Bearer td_<type>_<token>

{
  "type":  "tool_use",
  "id":    "toolu_unique_id",
  "name":  "run_code",
  "input": { "language": "python", "code": "print(42)", "timeout_sec": 30 }
}
```

---

## 5. Tool Reference

### `run_code`
Execute code inside the sandbox.
```json
{ "language": "python", "code": "...", "timeout_sec": 30 }
→ { "stdout": "...", "stderr": "...", "exit_code": 0, "duration_ms": 142 }
```

### `read_file`
```json
{ "path": "analysis.py" }
→ { "content": "..." }
```

### `write_file`
```json
{ "path": "output.csv", "content": "col1,col2\n1,2" }
```

### `list_dir`
```json
{ "path": "." }
→ [{ "name": "...", "path": "...", "type": "file|dir", "size_bytes": 1024 }]
```

### `web_search` *(SDK / cURL / Orch / IDE)*
```json
{ "query": "pandas groupby docs", "max_results": 5 }
```

### `install_package` *(IDE / Orch only)*
```json
{ "manager": "pip", "package": "pandas==2.2.0" }
```

### PTY tools *(IDE token only, via WebSocket)*
```
WS /v1/pty?token=td_ide_<token>&sandbox_id=<id>

Client → Server:
  { "type": "input",  "data": "ls -la\n" }
  { "type": "resize", "cols": 220, "rows": 50 }

Server → Client:
  { "type": "output", "data": "\u001b[32msandboxuser@td\u001b[0m:~$ " }
  { "type": "exit",   "code": 0 }
```

---

## 6. Terminal Access Paths

Users reach their sandbox terminal through two independent paths — both isolated, both authenticated.

### Path A — Browser Console / IDE (td_ide_ token)

```
Browser
  │
  │  WSS /v1/pty?token=td_ide_<token>&sandbox_id=<id>
  ▼
WebSocket PTY Server
  │
  │  docker exec -it --user sandboxuser <container> /bin/bash
  │     OR
  │  ssh sandboxuser@<vm-ip> (VirtualBox)
  ▼
xterm.js terminal panel in web IDE
```

The IDE surface exposes:
- **File tree** (left) — `list_dir` recursive, right-click context menu, drag-drop, upload
- **Monaco editor** (center) — syntax highlighting, auto-save (1.5 s debounce via `write_file`), multi-tab, diff view
- **Terminal panel** (bottom) — full xterm.js PTY, ANSI colors, Ctrl+C/D, multiple tabs, resizable
- **Run panel** (right) — one-click Python run, stdout/stderr inline, run history
- **Package manager** — PyPI search, `install_package` tool, installed versions list

### Path B — SSH Direct Access (td_ide_ token as SSH credential)

```
User's local terminal
  │
  │  ssh -p 22 thinkdome.io -i <key_or_token_auth>
  ▼
SSH Gateway (sshd proxy layer)
  │  validates td_ide_ token from SSH auth
  │  maps to correct sandbox_id
  ▼
docker exec / VirtualBox SSH
  → sandboxuser shell inside isolated sandbox
```

Both paths land in the **same isolated sandbox filesystem** (`/workspace`). Files written in the browser IDE are visible over SSH immediately, and vice versa — they are the same container/VM.

---

## 7. File Workspace

Each sandbox owns `/workspace` — isolated overlayfs (Docker) or disk partition (VirtualBox).

| Operation | Tool | Min Token |
|---|---|---|
| List | `list_dir` | Web |
| Read | `read_file` | Web |
| Write / Create | `write_file` | Web |
| Delete | `delete_file` | Orch / IDE |
| Rename | `rename_file` | Orch / IDE |
| Upload (multipart) | `POST /v1/workspace/upload` | Web / Orch / IDE |
| Download | `GET /v1/workspace/download?path=` | Web / Orch / IDE |

**Storage quotas:** 1 GB per Docker sandbox (configurable). VirtualBox: up to `disk_gb` set at creation.

**Hidden from UI by default:** `.git`, `venv`, `__pycache__`, `.env`, `*.pyc`, `node_modules`

---

## 8. SDK & Integration Examples

### Python SDK (td_sdk_ token)
```python
from thinkdome import Sandbox

sb = Sandbox(token="td_sdk_xxxxxxxxxxxx")
result = sb.run("print('Hello ThinkDome')")
print(result.stdout)

sb.write_file("hello.py", "print('saved!')")
content = sb.read_file("hello.py")
files   = sb.list_dir(".")

# Context manager — auto cleanup
with Sandbox(token="td_sdk_xxxxxxxxxxxx") as sb:
    sb.run("import pandas as pd; print(pd.__version__)")
```

### cURL (td_curl_ token)
```bash
curl -X POST https://thinkdome.io/v1/orchestrate \
  -H "Authorization: Bearer td_curl_xxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "tool_use",
    "id":   "curl_001",
    "name": "run_code",
    "input": { "language": "python", "code": "print(2**32)" }
  }'
```

### LLM Integration / Claude Tool Use (td_llm_ token)
```python
import anthropic

client = anthropic.Anthropic()

tools = [{
    "name": "run_code",
    "description": "Execute Python code in a secure ThinkDome sandbox",
    "input_schema": {
        "type": "object",
        "properties": {
            "language": { "type": "string", "enum": ["python"] },
            "code":     { "type": "string" }
        },
        "required": ["language", "code"]
    }
}]

# Claude emits a tool_use block → your backend forwards to ThinkDome
# td_llm_ token: only run_code permitted — no filesystem access for the LLM
```

---

## 9. API Endpoints Reference

### Auth
```
POST  /v1/auth/login        → { access_token, username }
POST  /v1/auth/register     → { message }
POST  /v1/auth/logout       → { message }
```

### Sandboxes
```
GET    /v1/admin/sandboxes              → list all user sandboxes
POST   /v1/admin/sandboxes             → create (Docker or VirtualBox)
POST   /v1/admin/sandboxes/{id}/toggle → start / stop
DELETE /v1/admin/sandboxes/{id}        → terminate permanently
```

### Sandbox Tokens
```
GET   /v1/admin/sandboxes/{id}/tokens    → list tokens for sandbox
POST  /v1/admin/sandboxes/{id}/tokens    → issue new token (returned once)
POST  /v1/admin/tokens/{token_id}/revoke → immediate revocation
```

### Orchestrator
```
POST  /v1/orchestrate        → execute tool (all sandbox token types)
```

### IDE / Terminal
```
WS    /v1/pty                → PTY WebSocket (IDE token only)
```

### File Workspace
```
POST  /v1/workspace/upload   → multipart file upload
GET   /v1/workspace/download → download by ?path=
```

### Logs & Audit
```
GET   /v1/admin/logs         → request/execution logs
POST  /v1/admin/logs/clear   → clear logs
GET   /v1/admin/audits       → security audit trail (append-only)
```

### Billing
```
GET   /v1/admin/billing?cycle=<key>         → cost usage report
POST  /v1/admin/billing/invoice?cycle=<key> → compile invoice PDF
```

### Schema
```
GET   /orchestrator_schema.json → ToolUse JSON schema
```

---

## 10. Dashboard UI — Key Screens

### Sandbox Card
Each sandbox renders as a card:
- Name + type badge (`DOCKER` / `VIRTUALBOX`)
- Status badge (`ACTIVE` / `STOPPED` / `CREATING` / `TERMINATED`)
- Resource summary: RAM · vCPU · timeout · network
- Cost/hr display
- Sandbox ID (monospaced, one-click copy)
- Actions: **Open Console** · **Open IDE** · **Start/Stop** · **Terminate**

### Create Sandbox Modal
Docker fields: name, runtime image, RAM, CPU, timeout slider, network toggle → live cost estimate.
VirtualBox fields: name, base OS, RAM, CPU, disk size, network toggle → live cost + provisioning time warning (45–90 s).

### Token Management (per sandbox)
Table columns: Display Name · Type badge · Masked preview (`td_llm_••••Xk9z`) · Created · Expires · Status · Revoke button.

Create token form: display name → token type radio cards (icon + description) → optional expiry → **Generate**. Token shown once in reveal banner with copy button and "Store securely" warning.

---

## 11. Security Constraints

| Control | Detail |
|---|---|
| Token storage | SHA-256 hash only — plaintext never persisted |
| Session JWTs | RS256 signed |
| Transport | HTTPS everywhere — HTTP rejected at edge |
| Rate limiting | 60 req/min (LLM) / 300 req/min (Orch, IDE) |
| Container isolation | No shared Docker network namespaces between sandboxes |
| Execution user | Always `sandboxuser` (UID 1000) — never root inside container |
| VirtualBox networking | Host-only or NAT only — never bridged to internal network |
| Path traversal | All file paths validated server-side (`../../` rejected) |
| Execution timeout | Enforced at container level — SIGKILL at `timeout_sec` |
| Audit log | Append-only — no delete endpoint |
| Token revocation | Immediate — revoked tokens return `401` on next request |

---

## 12. Persistence Layer

| Store | Holds |
|---|---|
| **PostgreSQL** | Users, sandboxes, token metadata (hashed), audit events, billing records |
| **Redis** | Session cache, warm-pool state, rate-limit counters, PTY session registry |
| **Object store / local FS** | Workspace file blobs (large files), VM `.ova` snapshots, invoice PDFs |

---

## 13. Glossary

| Term | Meaning |
|---|---|
| Sandbox | An isolated execution environment (Docker container or VirtualBox VM) owned by one user |
| Token | A scoped, opaque credential tied to one sandbox and one surface |
| Workspace | The persistent `/workspace` directory inside a sandbox |
| PTY | Pseudo-terminal — the real shell session used by IDE tokens |
| Orchestrator | The API layer that routes ToolUse payloads to the correct sandbox backend |
| Warm pool | Pre-started containers held ready to cut cold-start latency |
| Scope | The set of tools a token is permitted to invoke |
| Overlayfs | The copy-on-write filesystem layer Docker uses per container |