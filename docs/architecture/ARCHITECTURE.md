# ThinkDome — Architecture Overview

> Technical architecture documentation for the ThinkDome secure AI agent sandbox & orchestration platform.

---

## System Architecture Diagram

```mermaid
graph TB
    subgraph Client["🌐 Client Layer"]
        Browser["Web Dashboard<br/>(HTML/CSS/JS)"]
        SDK["Python SDK<br/>(thinkdome.Sandbox)"]
        CLI["CLI<br/>(think / thinkdome)"]
    end

    subgraph API["⚡ API Gateway"]
        FastAPI["FastAPI Server<br/>uvicorn + WebSocket"]
        AuthMW["Auth Middleware<br/>JWT + Session"]
        RBAC["RBAC Engine<br/>Role-Based Access"]
    end

    subgraph Core["🧠 Core Services"]
        Handler["RPC Handler<br/>(whitelist dispatch)"]
        ORM["Custom ORM<br/>(SQLAlchemy + SQLite)"]
        EventBus["Event Bus<br/>(async pub/sub)"]
        Scheduler["Task Scheduler"]
        UIService["Dynamic UI Registry<br/>(page builder)"]
    end

    subgraph Sandbox["🐳 Sandbox Engine"]
        Provisioner["Provisioner<br/>(backend selection)"]
        Docker["Docker Executor<br/>(seccomp + cgroups)"]
        Subprocess["Subprocess Executor<br/>(dev mode)"]
        MicroVM["MicroVM Executor<br/>(Firecracker)"]
        Pool["Container Pool<br/>(warm start)"]
        Lifecycle["Lease Lifecycle<br/>(TTL, cleanup)"]
    end

    subgraph Storage["💾 Storage Layer"]
        FileBox["FileBox Service<br/>(per-user virtual FS)"]
        SiteDB["Site Database<br/>(SQLite per tenant)"]
        Redis["Redis Cache<br/>(sessions, checkpoints)"]
    end

    subgraph Security["🛡️ Security Boundary"]
        Seccomp["seccomp-bpf profiles"]
        NetworkPolicy["Network Egress Policy<br/>(default-deny)"]
        Scanner["Code Scanner<br/>(static analysis)"]
    end

    subgraph Integrations["🔗 Integrations"]
        LangGraph["LangGraph<br/>(agentic workflows)"]
        MCP["MCP Tools<br/>(Model Context Protocol)"]
        Telegram["Telegram MCP"]
    end

    Browser --> FastAPI
    SDK --> FastAPI
    CLI --> FastAPI

    FastAPI --> AuthMW --> RBAC
    RBAC --> Handler
    Handler --> ORM
    Handler --> EventBus
    Handler --> UIService
    Handler --> Scheduler

    Handler --> Provisioner
    Provisioner --> Docker
    Provisioner --> Subprocess
    Provisioner --> MicroVM
    Docker --> Pool
    Docker --> Lifecycle
    Docker --> Seccomp
    Docker --> NetworkPolicy

    Handler --> FileBox
    ORM --> SiteDB
    ORM --> Redis

    Handler --> LangGraph
    Handler --> MCP
    MCP --> Telegram
    LangGraph --> Docker

    Scanner --> Docker

    style Client fill:#1e293b,stroke:#38bdf8,color:#f8fafc
    style API fill:#1e293b,stroke:#a855f7,color:#f8fafc
    style Core fill:#1e293b,stroke:#10b981,color:#f8fafc
    style Sandbox fill:#1e293b,stroke:#f97316,color:#f8fafc
    style Storage fill:#1e293b,stroke:#06b6d4,color:#f8fafc
    style Security fill:#1e293b,stroke:#ef4444,color:#f8fafc
    style Integrations fill:#1e293b,stroke:#eab308,color:#f8fafc
```

---

## Request Flow — Code Execution

```mermaid
sequenceDiagram
    participant U as User / Agent
    participant API as FastAPI
    participant Auth as Auth Middleware
    participant RBAC as RBAC Engine
    participant Prov as Provisioner
    participant Pool as Container Pool
    participant Docker as Docker Executor
    participant FS as FileBox
    participant WS as WebSocket

    U->>API: POST /v1/sandbox/execute
    API->>Auth: Validate JWT token
    Auth->>RBAC: Check role permissions
    RBAC-->>API: ✓ Authorized

    API->>Prov: Provision sandbox
    Prov->>Pool: Request warm container
    Pool-->>Prov: Container ID

    Prov->>Docker: Execute code
    Docker->>Docker: Apply seccomp profile
    Docker->>Docker: Set network policy
    Docker->>Docker: Run with cgroup limits

    Docker-->>Prov: SandboxResult (stdout, stderr, exit_code)
    Prov-->>API: Execution result
    API->>FS: Save execution artifacts
    API->>WS: Broadcast event (filebox_changed)
    API-->>U: JSON response
```

---

## FileBox Virtual Filesystem

```mermaid
graph LR
    subgraph Tenant["Multi-Tenant FileBox"]
        User1["User A<br/>/sites/think.local/filebox/user_a/"]
        User2["User B<br/>/sites/think.local/filebox/user_b/"]
        User3["Agent<br/>/sites/think.local/filebox/agent/"]
    end

    subgraph Dirs["Semantic Folder Layout"]
        Models["📁 models/<br/>AI model configs & weights"]
        Designs["📁 designs/<br/>System architecture DAGs"]
        Prompts["📁 prompts/<br/>Persona & instruction templates"]
        Skills["📁 skills/<br/>MCP tools & executable skills"]
        Knowledge["📁 knowledge/<br/>RAG corpora & references"]
        Memory["📁 memory/<br/>Semantic & episodic memory"]
    end

    User1 --> Models
    User1 --> Designs
    User1 --> Prompts
    User1 --> Skills
    User1 --> Knowledge
    User1 --> Memory

    subgraph API["FileBox REST API"]
        List["/v1/filebox/browse/list"]
        Read["/v1/filebox/browse/read"]
        Write["/v1/filebox/browse/write"]
        Delete["/v1/filebox/browse/delete"]
        Move["/v1/filebox/browse/move"]
        Search["/v1/filebox/browse/search"]
    end

    Dirs --> API

    style Tenant fill:#0f172a,stroke:#38bdf8,color:#f8fafc
    style Dirs fill:#0f172a,stroke:#10b981,color:#f8fafc
    style API fill:#0f172a,stroke:#a855f7,color:#f8fafc
```

---

## Security Model

```mermaid
graph TD
    subgraph Layers["Defense-in-Depth"]
        L1["Layer 1: Authentication<br/>JWT + Session Tokens"]
        L2["Layer 2: Authorization<br/>RBAC (SUPER_ADMIN, ADMIN, AGENT)"]
        L3["Layer 3: Code Scanning<br/>Static analysis before execution"]
        L4["Layer 4: Container Isolation<br/>Docker + seccomp-bpf"]
        L5["Layer 5: Network Policy<br/>Default-deny egress firewall"]
        L6["Layer 6: Resource Limits<br/>cgroups (CPU, RAM, disk)"]
        L7["Layer 7: Lease TTL<br/>Auto-terminate expired sandboxes"]
    end

    L1 --> L2 --> L3 --> L4 --> L5 --> L6 --> L7

    style Layers fill:#0f172a,stroke:#ef4444,color:#f8fafc
```

---

## Module Directory Map

```
thinkdome/
├── __init__.py          # Public API: Sandbox, whitelist, call
├── cli.py               # CLI entry point (thinkdome command)
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

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Language** | Python 3.9+ |
| **Web Framework** | FastAPI + Uvicorn |
| **ORM** | SQLAlchemy 2.0 |
| **Database** | SQLite (per-site), Redis |
| **Container Runtime** | Docker Engine |
| **MicroVM** | Firecracker |
| **Auth** | JWT + bcrypt |
| **Frontend** | Vanilla HTML/CSS/JS (SPA) |
| **Real-time** | WebSocket (native) |
| **AI Frameworks** | LangGraph, MCP |
| **Package** | Hatchling (pyproject.toml) |
