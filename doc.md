# ThinkDome Framework — Developer Documentation

> A metadata-driven application operating system for building AI platforms, developer sandboxes, cloud automation, and internal tools.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Creating Applications](#creating-applications)
- [ORM & Models](#orm--models)
- [Hooks & Events](#hooks--events)
- [Workflow Engine](#workflow-engine)
- [API Server](#api-server)
- [Database Migrations](#database-migrations)
- [Package Manager](#package-manager)
- [Frontend Plugins](#frontend-plugins)
- [Testing](#testing)
- [Docker Deployment](#docker-deployment)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    think CLI                             │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │  Kernel   │  │   ORM    │  │  Events  │  │ Queue  │ │
│  │  Plugin   │  │  Models  │  │  Hooks   │  │ Worker │ │
│  │  Loader   │  │  Fields  │  │  Bus     │  │ Sched  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬───┘ │
│       │              │              │              │     │
│  ┌────┴──────────────┴──────────────┴──────────────┴───┐│
│  │              FastAPI Gateway + WebSockets            ││
│  │          (Auto-generated CRUD from models)           ││
│  └─────────────────────────────────────────────────────┘│
│                                                         │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌─────────┐│
│  │  sandbox  │ │  agents   │ │ workflows │ │  your   ││
│  │    app    │ │    app    │ │    app    │ │   app   ││
│  └───────────┘ └───────────┘ └───────────┘ └─────────┘│
│                   Pluggable Apps                        │
└─────────────────────────────────────────────────────────┘
```

**Key concepts:**

| Concept       | Analogy            | Description                                              |
|---------------|--------------------|----------------------------------------------------------|
| **Kernel**    | OS Kernel          | Boots sites, loads apps, manages DB connections           |
| **Apps**      | Installed programs | Pluggable modules with models, controllers, hooks         |
| **ORM**       | Django ORM         | Pythonic field descriptors → auto SQLAlchemy tables       |
| **Hooks**     | WordPress hooks    | Priority-based callbacks on lifecycle events              |
| **Events**    | Pub/Sub bus        | Async event dispatch with WebSocket relay                 |
| **Queue**     | Celery (lite)      | DB-backed background job runner, zero dependencies        |
| **Metadata**  | DocTypes           | JSON manifests defining resources and schemas             |

---

## Quick Start

### 1. Create a site (multi-tenant workspace)

```bash
think create-site mysite
```

This creates `sites/mysite/` with a SQLite database and configuration file.

### 2. Create a new app

```bash
think new-app crm
```

This scaffolds:

```
thinkdome/apps/crm/
├── app.json          # App metadata manifest
├── hooks.py          # Hook registrations
├── backend/          # Server-side code
├── frontend/         # Client-side code
└── migrations/       # Database migration scripts
```

### 3. Start the server

```bash
think serve --host 0.0.0.0 --port 8000
```

### 4. Run background workers

```bash
think worker      # Process queued jobs
think scheduler   # Run cron tasks
```

---

## CLI Reference

### Site Management

```bash
think create-site <name> [--db-url postgres://...]
```

### Application Lifecycle

```bash
think new-app <name>                         # Scaffold new app
think install-app <source>                   # Install from Git/local
think install-app https://github.com/org/app --branch develop
think install-app ./my-local-app             # Install from local path
think uninstall-app <name>                   # Remove app completely
think link-app ../my-app                     # Symlink for dev mode
think list-apps                              # Show installed apps
think app-info <name>                        # Show app manifest
think enable-app <name>                      # Activate on site
think disable-app <name>                     # Deactivate on site
think update-app <name>                      # Pull latest version
think search-app <query>                     # Search marketplace
```

### Database Migrations

```bash
think migrate                                # Run all pending migrations
think migrate crm                            # Migrate specific app
think migrate --rollback                     # Undo last migration
think migrate crm --rollback                 # Rollback specific app
think migration-status                       # Show migration status
```

### Process Management

```bash
think serve [--host HOST] [--port PORT] [--reload]
think worker                                 # Background job processor
think scheduler                              # Cron job runner
think shell                                  # Interactive Python REPL
think test                                   # Run test suite
```

---

## Creating Applications

### App Manifest (`app.json`)

Every app requires a manifest:

```json
{
    "name": "crm",
    "version": "1.0.0",
    "description": "Customer relationship management",
    "dependencies": ["core", "notifications"],
    "author": "Your Company",
    "license": "MIT"
}
```

### Defining Models (`models.py`)

Use the ThinkDome ORM to define resources:

```python
from thinkdome.core.orm.orm import (
    Model, StringField, IntegerField, BooleanField, FloatField, SelectField
)

class Customer(Model):
    name = StringField(required=True)
    email = StringField(required=True)
    phone = StringField(default="")
    status = SelectField(
        choices=["Active", "Inactive", "Lead"],
        default="Lead"
    )
    revenue = FloatField(default=0.0)
    is_vip = BooleanField(default=False)
```

This automatically:
- Creates a `customers` table in the database
- Registers `Customer` in the API router → `GET/POST/PUT/DELETE /api/customer`
- Enables query filtering, soft deletion, and validation

### Writing Controllers (`controller.py`)

```python
from thinkdome.apps.crm.models import Customer
from thinkdome.core.events.events import emit

async def onboard_customer(data: dict) -> Customer:
    customer = Customer(
        name=data["name"],
        email=data["email"],
        status="Active",
    )
    customer.save()
    await emit("customer.created", {"id": customer.id, "name": customer.name})
    return customer
```

---

## ORM & Models

### Available Field Types

| Field           | Python Type | SQL Type    | Example                                    |
|-----------------|-------------|-------------|---------------------------------------------|
| `StringField`   | `str`       | `VARCHAR`   | `name = StringField(required=True)`         |
| `IntegerField`  | `int`       | `INTEGER`   | `age = IntegerField(default=0)`             |
| `FloatField`    | `float`     | `FLOAT`     | `price = FloatField(default=0.0)`           |
| `BooleanField`  | `bool`      | `BOOLEAN`   | `active = BooleanField(default=True)`       |
| `SelectField`   | `str`       | `VARCHAR`   | `status = SelectField(choices=[...])`       |

### CRUD Operations

```python
# Create
customer = Customer(name="Acme Corp", email="acme@example.com")
customer.save()

# Read
found = Customer.get(customer.id)

# Query with filters
active = Customer.query().filter(status="Active").limit(50).all()
first = Customer.query().filter(is_vip=True).first()

# Update
customer.status = "Active"
customer.save()

# Soft delete (sets is_deleted=True, excluded from queries)
customer.delete(soft=True)
```

---

## Hooks & Events

### Registering Hooks (`hooks.py`)

```python
import logging
logger = logging.getLogger(__name__)

def on_customer_created(customer):
    logger.info(f"New customer: {customer.name}")

def on_customer_error(customer, error=None, **kwargs):
    logger.error(f"Customer error: {error}")

hooks = {
    "customer.after_create": [on_customer_created],
    "customer.on_error": [on_customer_error],
}
```

### Emitting Events

```python
from thinkdome.core.events.events import emit, bus

# Emit an event (relayed to WebSocket clients automatically)
await emit("order.placed", {"order_id": "123", "total": 99.99})

# Subscribe to events
def handle_order(data):
    print(f"Order received: {data}")

bus.on("order.placed", handle_order)
```

---

## Workflow Engine

Build automation pipelines with node graphs:

```python
import json
from thinkdome.apps.workflows.models import Workflow
from thinkdome.apps.workflows.controller import start_workflow, register_action

# Register custom actions
@register_action("send_email")
async def send_email(payload, context):
    # your email logic here
    return {"sent": True}

# Define a workflow
wf = Workflow(
    name="Onboarding Pipeline",
    owner="admin",
    nodes=json.dumps([
        {"id": "step-1", "type": "action", "action": "log",
         "payload": {"message": "Starting onboarding"}},
        {"id": "step-2", "type": "action", "action": "send_email",
         "payload": {"to": "user@example.com"}},
        {"id": "step-3", "type": "approval",
         "message": "Manager approval required"},
    ]),
    edges=json.dumps([
        {"from": "step-1", "to": "step-2"},
        {"from": "step-2", "to": "step-3"},
    ]),
)
wf.save()

# Execute it
execution = await start_workflow(wf, {"user": "john"})
```

Supported node types:
- **`action`** — Runs a registered action handler
- **`condition`** — Branches based on field comparisons (`==`, `!=`, `>`)
- **`approval`** — Pauses execution until manual approval via `approve_execution()`

---

## API Server

The framework auto-generates REST endpoints for every registered model:

| Method   | Route                    | Description        |
|----------|--------------------------|--------------------|
| `GET`    | `/api/{doctype}`         | List records       |
| `POST`   | `/api/{doctype}`         | Create record      |
| `GET`    | `/api/{doctype}/{id}`    | Get single record  |
| `PUT`    | `/api/{doctype}/{id}`    | Update record      |
| `DELETE` | `/api/{doctype}/{id}`    | Soft-delete record |

WebSocket endpoint for real-time events:

```
ws://localhost:8000/ws/{client_id}
```

All internal `emit()` calls are automatically relayed to connected WebSocket clients.

---

## Database Migrations

### Writing a Migration

Create numbered Python files in `apps/<name>/migrations/`:

```python
# apps/crm/migrations/0001_create_customers.py
from sqlalchemy import text

def up(db):
    db.execute(text("""
        CREATE TABLE customers (
            id VARCHAR(255) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL,
            status VARCHAR(50) DEFAULT 'Lead',
            is_deleted BOOLEAN DEFAULT FALSE
        )
    """))
    db.commit()

def down(db):
    db.execute(text("DROP TABLE IF EXISTS customers"))
    db.commit()
```

### Running Migrations

```bash
think migrate              # Apply all pending migrations
think migrate crm          # Migrate only the CRM app
think migrate --rollback   # Rollback the last applied migration
think migration-status     # View what's applied vs pending
```

---

## Package Manager

### Installing Apps

```bash
# From Git (HTTPS)
think install-app https://github.com/company/crm-app

# From Git (SSH) with specific branch
think install-app git@github.com:company/app.git --branch develop

# From Git with version tag
think install-app https://github.com/org/app --version v2.0.0

# From local directory
think install-app ./my-local-app
```

### Development Mode

```bash
think link-app ../my-app-in-development
```

Creates a symlink so changes in your local directory are instantly reflected.

### App Registry

Installed apps are tracked in `sites/common/apps.json`:

```json
{
    "installed_apps": [
        {
            "name": "crm",
            "version": "1.2.0",
            "source": "github.com/company/crm",
            "enabled": true
        }
    ]
}
```

---

## Frontend Plugins

Apps can extend the dashboard UI dynamically:

```javascript
// Register a new page
ThinkDomePlugin.registerPage("Customers", customerIcon, renderFn);

// Register a dashboard widget
ThinkDomePlugin.registerWidget("Revenue Chart", renderChartFn);

// Register a navigation route
ThinkDomePlugin.registerRoute("/customers", renderCustomerPage);

// Register a menu item
ThinkDomePlugin.registerMenu("CRM", "/customers", crmIcon);
```

---

## Testing

Run the framework test suite:

```bash
think test
# or directly:
./venv/bin/pytest tests/test_framework.py -v
```

The test suite validates:
- ORM CRUD, queries, and soft-deletion
- Event bus subscriptions and hook priority ordering
- Background task queue registration
- Sandbox and Agent lifecycle execution
- Workflow engine traversal, condition branching, and approval gates
- Auto-generated REST API endpoints
- Package manager installation, migrations, and rollbacks

---

## Docker Deployment

```bash
docker-compose up -d
```

Configuration lives in `docker/` and `k8s/` directories. The application server runs via:

```bash
think serve --host 0.0.0.0 --port 8000
```

Environment variables are loaded from `.env`.

---

## Project Structure

```
ThinkDome/
├── think                           # Framework CLI entrypoint
├── pyproject.toml                  # Package configuration
├── sites/                          # Multi-tenant site configs
│   └── personal/
│       ├── site_config.json
│       └── db.sqlite
│
├── thinkdome/
│   ├── core/                       # Framework kernel
│   │   ├── kernel/                 # Site boot, plugin registry
│   │   │   ├── kernel.py
│   │   │   ├── manager.py          # Package manager
│   │   │   └── migrations.py       # Migration engine
│   │   ├── orm/orm.py              # Metadata-driven ORM
│   │   ├── cli/cli.py              # CLI command router
│   │   ├── api/                    # Auto-generated REST + WS
│   │   ├── events/events.py        # Async event bus
│   │   ├── hooks/hooks.py          # Priority hook manager
│   │   ├── queue/queue.py          # Background job queue
│   │   ├── scheduler/scheduler.py  # Cron scheduler
│   │   └── metadata/metadata.py    # JSON DocType parser
│   │
│   ├── apps/                       # Pluggable applications
│   │   ├── sandbox/                # Container orchestration
│   │   ├── agents/                 # AI agent execution
│   │   ├── workflows/              # Automation pipelines
│   │   ├── monitoring/             # Resource metrics
│   │   └── marketplace/            # Extension registry
│   │
│   ├── api/                        # Original REST API routes
│   ├── services/                   # Business logic services
│   ├── models/                     # Database models
│   ├── executors/                  # Sandbox execution backends
│   ├── server.py                   # FastAPI application factory
│   └── static/                     # Frontend dashboard
│
├── tests/                          # Test suites
├── docker/                         # Docker configs
└── k8s/                            # Kubernetes manifests
```
