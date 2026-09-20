# ThinkDome — Architecture Overview

> Technical architecture documentation for the ThinkDome secure AI agent sandbox & orchestration platform.

---

## 1. System Architecture & Modular Dispatch Flow

ThinkDome is built as a modular micro-kernel architecture where all subsystem interactions occur through strict RPC dispatching, permission boundaries, and lifecycle management.

```mermaid
sequenceDiagram
    autonumber
    actor Client as 🌐 Client / SDK / CLI / Web UI
    participant Gateway as ⚡ FastAPI Gateway
    participant Auth as 🛡️ Auth & RBAC Engine
    participant Handler as 🧠 Core RPC Dispatcher
    participant Orchestrator as ⚙️ Sandbox Provisioner
    participant Runtime as 🐳 Execution Backend (Docker/MicroVM)
    participant FileBox as 📂 FileBox Virtual Drive
    participant SiteDB as 💾 Site Database & Redis

    Note over Client,Gateway: 1. Request Entry & Protocol Ingress
    Client->>Gateway: HTTP / WebSocket / Tool Request
    Gateway->>Auth: Validate JWT / Session & User Roles
    Auth-->>Gateway: Access Permitted (SuperAdmin / Admin / Agent)

    Note over Gateway,Handler: 2. Core RPC Dispatching
    Gateway->>Handler: Dispatch Verified Operation
    Handler->>SiteDB: Load Tenant Workspace & Quota Policies
    SiteDB-->>Handler: Quota: Max RAM, Lease Duration, Active Nodes

    Note over Handler,Orchestrator: 3. Execution Provisioning
    Handler->>Orchestrator: Request Isolated Execution Environment
    Orchestrator->>FileBox: Mount Scoped Agent Workdir (/workspace)
    FileBox-->>Orchestrator: Virtual Directory Ready
    Orchestrator->>Runtime: Spawn Container / MicroVM with Seccomp & Limits
    Runtime-->>Orchestrator: Execution Stream & Return Code

    Note over Handler,SiteDB: 4. Storage Sync & Audit Logging
    Orchestrator->>FileBox: Sync Output Artifacts
    Handler->>SiteDB: Record Audit Trail (Execution Duration, Memory Peak)
    Handler-->>Gateway: Build RPC Response
    Gateway-->>Client: Return JSON Result / Stream Output
```

---

## 2. End-to-End Sandbox Code Execution Lifecycle

This sequence diagram details the full execution path when an autonomous AI agent or user runs code inside an ephemeral sandbox.

```mermaid
sequenceDiagram
    autonumber
    actor Agent as 🤖 AI Agent / User
    participant API as ⚡ FastAPI Server
    participant Auth as 🛡️ Auth Middleware
    participant Quota as 📊 Admission & Quota Check
    participant Pool as 🔄 Container Pool Manager
    participant Executor as 🐳 Docker / MicroVM Executor
    participant Egress as 🌐 Network Egress Gate
    participant FS as 📂 FileBox Storage
    participant DB as 💾 Site Database

    Agent->>API: POST /api/sandbox/run (code, backend, limits, egress_policy)
    API->>Auth: Validate Token & Workspace Desk Scope
    Auth-->>API: ✓ Authorized

    API->>Quota: Validate Host Available RAM & Active Leases
    Quota-->>API: ✓ Admission Approved

    API->>Pool: Request Warm / Fresh Container
    Pool->>Executor: Initialize Ephemeral Sandbox Instance
    Executor->>FS: Mount Isolated Virtual Directory
    FS-->>Executor: Workdir Mounted

    Executor->>Executor: Apply seccomp-bpf Syscall Filter
    Executor->>Executor: Apply cgroups Resource Limits (RAM, CPU)

    Executor->>Executor: Execute Code in Isolated Environment

    opt Outbound Network Access Attempted
        Executor->>Egress: Outbound HTTP / Socket Connection
        alt Destination in Domain Allowlist
            Egress-->>Executor: Forward Packet
        else Not in Allowlist (Default-Deny)
            Egress-->>Executor: Drop Connection & Log Violation
        end
    end

    Executor-->>Pool: Return stdout, stderr, exit_code & peak_memory_mb
    Pool->>FS: Persist Generated Output Files
    Pool->>Executor: Teardown & Recycle Ephemeral Container
    Pool->>DB: Log Audit Event (duration, memory, exit_code)
    Pool-->>API: Format Execution Result
    API-->>Agent: JSON Response (exit_code: 0, stdout: "...")
```

---

## 3. FileBox Virtual Filesystem Lifecycle

FileBox provides isolated, semantic workspace storage for autonomous agents, preventing path traversal while maintaining per-tenant isolation.

```mermaid
sequenceDiagram
    autonumber
    actor Agent as 🤖 Agent / User
    participant API as ⚡ FileBox REST API
    participant Perm as 🛡️ Permission Checker
    participant Core as 📂 FileBox Core Service
    participant Storage as 💾 Host Virtual Storage
    participant Audit as 📊 FileBox Audit Logger

    Agent->>API: POST /api/filebox/write (path, content)
    API->>Perm: Check Access Control (actor, permissions.yaml)
    
    alt Unauthorized or Path Traversal (e.g. ../../)
        Perm-->>API: 403 Forbidden (Path Traversal Detected)
        API-->>Agent: Error: Permission Denied
    else Permission Valid
        Perm-->>API: Access Granted
        API->>Core: Write Content to Target File
        Core->>Storage: Persist to /sites/{tenant}/filebox/{actor}/{path}
        Core->>Audit: Log Audit Entry (action="write", path, actor)
        Audit-->>Core: Logged
        Core-->>API: Write Succeeded
        API-->>Agent: 201 Created (path, size_bytes, updated_at)
    end
```

---

## 4. Defense-in-Depth Security Enforcement Pipeline

Every request is evaluated through 7 discrete defensive layers before and during execution:

```mermaid
sequenceDiagram
    autonumber
    actor Request as 🌐 Incoming Execution Request
    participant L1 as 1️⃣ Token Auth (JWT / Cookie)
    participant L2 as 2️⃣ RBAC Authorization
    participant L3 as 3️⃣ Code Static Scanner
    participant L4 as 4️⃣ Host Admission & RAM Check
    participant L5 as 5️⃣ Seccomp & Cap Drop
    participant L6 as 6️⃣ Default-Deny Egress Gate
    participant L7 as 7️⃣ Lease TTL Reaper

    Request->>L1: Validate Session / Token Signature
    L1-->>Request: Signature Valid
    Request->>L2: Match Role Permissions (Execute Sandbox)
    L2-->>Request: Role Authorized
    Request->>L3: Scan Code for Fork Bombs / Dangerous Calls
    L3-->>Request: Code Passed Static Check
    Request->>L4: Verify Host Memory Budget & Lease Limits
    L4-->>Request: Admission Granted
    Request->>L5: Apply seccomp-bpf & drop Linux capabilities
    L5-->>Request: Isolation Boundary Active
    Request->>L6: Filter Outbound Egress (Allowlist Only)
    L6-->>Request: Network Traffic Restricted
    Request->>L7: Monitor Lease Duration & Auto-Terminate on Expiry
    L7-->>Request: Sandbox Cleanly Destroyed
```

---

## 5. Module Directory Map

```
thinkdome/
├── __init__.py          # Public API: Sandbox, whitelist, call
├── cli.py               # CLI entry point (thinkdome & think commands)
├── api/                 # FastAPI server, routes, middleware
│   ├── server.py        # Application factory & route registration
│   └── routes/          # REST endpoint modules
├── core/                # Framework internals
│   ├── config.py        # Settings & environment resolution
│   ├── handler.py       # RPC whitelist dispatch engine
│   ├── orm/             # Custom ORM (SQLAlchemy models)
│   ├── kernel/          # Startup, migrations, lifecycle
│   ├── events/          # Async event bus
│   ├── ui/              # Dynamic page registry & builder
│   └── middleware/      # CORS, auth, error handling
├── sandbox/             # Sandbox execution engine
│   ├── core/            # Sandbox primitives
│   ├── executors/       # Docker, subprocess, MicroVM backends
│   ├── pool/            # Warm container pool manager
│   ├── security/        # seccomp profiles, network policies
│   ├── sessions/        # Session state management
│   ├── snapshots/       # Checkpoint/restore support
│   └── tools/           # MCP tool bindings
├── security/            # Authentication & authorization
│   ├── auth/            # JWT, session, password hashing
│   ├── identity/        # User identity resolution
│   ├── rbac/            # Role-based access control
│   └── scanner/         # Static code analysis
├── filebox/             # Virtual filesystem service
│   ├── api.py           # Browse REST endpoints
│   ├── core.py          # Read/write/move/delete operations
│   ├── search.py        # Full-text file search
│   └── permissions.py   # Per-file access control
├── control_plane/       # Distributed node management
│   ├── orchestrator.py  # Multi-node orchestration
│   ├── node_agent.py    # Per-node sandbox agent
│   ├── placement.py     # Scheduling & placement
│   └── registry.py      # Node registry
├── integrations/        # External framework connectors
│   └── langgraph.py     # LangGraph agentic workflow integration
├── platform/            # Infrastructure services
│   ├── database/        # Connection pools & migrations
│   ├── storage/         # FileBox storage backend
│   ├── orchestration/   # Container orchestration
│   └── observability/   # Logging & metrics
└── static/              # Frontend assets
    └── assets/
        ├── css/styles.css
        └── js/
            ├── app.js           # SPA router & navigation
            ├── api.js           # REST API client
            ├── filemanager.js   # FileBox workstation UI
            └── ui_builder.js    # Dynamic page renderer
```

---

## 6. Technology Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.9+ |
| **Web Framework** | FastAPI + Uvicorn |
| **ORM** | SQLAlchemy 2.0 |
| **Database** | SQLite (per-site tenant DB), Redis |
| **Container Runtime** | Docker Engine + cgroups v2 |
| **MicroVM** | Firecracker / Cloud Hypervisor |
| **User-Space Kernel** | gVisor (`runsc`) |
| **Auth** | JWT + bcrypt + Session Cookies |
| **Frontend** | Vanilla HTML5 / Modern CSS / ES Modules (SPA) |
| **Real-time** | WebSocket (native bidirectional PTY) |
| **AI Frameworks** | LangGraph, Model Context Protocol (MCP) |
| **Build & Packaging** | Hatchling (`pyproject.toml`) |
