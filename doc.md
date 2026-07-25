# ThinkDome — Scalable Modular Architecture & MCP Tool Pipeline

## Overview

ThinkDome exposes a dynamic, registry-driven tool structure that powers both the REST Orchestrator API and a production-grade **Model Context Protocol (MCP)** stdio server. All 24 built-in tools are implemented as distinct object-oriented classes inheriting from a common `BaseTool` interface, organized into self-contained domain-driven packages.

---

## Architectural Layout

```
thinkdome/
├── modules/               (Domain Modules)
│   ├── auth/              (AuthService, CredentialVault)
│   ├── billing/           (BillingService)
│   ├── database/          (DatabaseService)
│   ├── execution/         (ExecutionService, PoolManager, EgressProxy, run/shell tools)
│   ├── storage/           (FileService, WorkspaceService, file/dir tools)
│   ├── orchestrator/      (OrchestratorService, RequestLogService)
│   ├── search/            (SearchService, web_search, grep, find_files tools)
│   ├── memory/            (MemoryStoreTool, MemoryRetrieveTool, etc.)
│   ├── comms/             (SendEmailTool, SendTelegramTool)
│   └── ...
├── core/
│   └── tools.py           (BaseTool, register_tool, and ToolRegistry core engine)
└── mcp.py                 (Production MCP stdio transport server)
```

---

## Tool Class Inheritance Hierarchy

All tools inherit from the abstract `BaseTool` class in [thinkdome/core/tools.py](file:///home/sandbox/ThinkDome/thinkdome/core/tools.py):

```python
from abc import ABC, abstractmethod
from typing import Any, Optional, Type
from pydantic import BaseModel

class BaseTool(ABC):
    """Abstract base class representing a framework tool."""
    name: str
    description: str
    required_scope: str
    input_schema: Optional[Type[BaseModel]] = None

    @abstractmethod
    async def execute(self, tool_input: dict[str, Any]) -> str:
        """Execution logic for the tool."""
        pass
```

Classes are decorated with `@register_tool` to automatically instantiate and register themselves in the global registry at module import time.

### Example Tool Implementation

```python
from thinkdome.core.tools import BaseTool, register_tool, get_context
from thinkdome.models.orchestrator import ReadFileInput

@register_tool
class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a file's content from the workspace"
    required_scope = "file:read"
    input_schema = ReadFileInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        path = tool_input.get("path")
        ctx = get_context()
        # Execution logic goes here...
```

---

## Core Components

### 1. `ToolRegistry`
Coordinates all registered tools. Handles discovery, metadata translation (for MCP schemas), and site-specific activation checks.

### 2. `ToolContext`
Carries user details, workspace boundaries, active database instances, and sandbox resource limits. Exposes `execute_code()` to allow tools to run code inside containerized sandbox environments.

### 3. `OrchestratorService`
Acts as a lightweight orchestrator:
1. Validates requests.
2. Checks RBAC privileges against the role's scopes.
3. Retrieves the requested tool from the registry.
4. Prepares the execution context and dispatches control to the tool class.

---

## Registered Tools (24 Core)

| Tool Name          | Domain Module | Required Scope     | Description                                      |
|-------------------|---------------|--------------------|-------------------------------------------------|
| `read_file`       | `storage`     | `file:read`        | Read a file from the workspace                   |
| `write_file`      | `storage`     | `file:write`       | Write content to a file                          |
| `list_dir`        | `storage`     | `file:read`        | List directory contents                          |
| `file_exists`     | `storage`     | `file:read`        | Check if a file or directory exists              |
| `make_dir`        | `storage`     | `file:write`       | Create a directory                               |
| `remove_file`     | `storage`     | `file:destructive` | Delete a file                                    |
| `remove_dir`      | `storage`     | `file:destructive` | Delete a directory recursively                   |
| `move_file`       | `storage`     | `file:destructive` | Move/rename a file or directory                  |
| `copy_file`       | `storage`     | `file:write`       | Copy a file                                      |
| `run_code`        | `execution`   | `code:run`         | Execute code in sandbox (Python, JS, etc.)       |
| `shell_exec`      | `execution`   | `shell:run`        | Execute shell command in sandbox                 |
| `web_search`      | `search`      | `web:search`       | Search the web via configured provider           |
| `grep_search`     | `search`      | `file:read`        | Search file contents with regex/pattern          |
| `find_files`      | `search`      | `file:read`        | Find files by name pattern                       |
| `get_file_info`   | `search`      | `file:read`        | Get file metadata (size, modified, etc.)         |
| `hash_file`       | `search`      | `file:read`        | Compute hash of a file                           |
| `memory_store`    | `memory`      | `memory:write`     | Store key-value entry in persistent memory       |
| `memory_retrieve` | `memory`      | `memory:read`      | Retrieve memory entry by key                     |
| `memory_search`   | `memory:read` | `memory:read`      | Search memory entries                            |
| `memory_delete`   | `memory`      | `memory:delete`    | Delete a memory entry                            |
| `memory_list`     | `memory`      | `memory:read`      | List memory keys                                 |
| `http_request`    | `network`     | `network:all`      | Make HTTP requests                               |
| `send_email`      | `comms`       | `comms:send`       | Send email via SMTP                              |
| `send_telegram`   | `comms`       | `comms:send`       | Send Telegram message via Bot API                |

---

## MCP Server Integration

### Local Claude Desktop Config (Stdio)

Start the stdio-based MCP server using the CLI:

```bash
python think mcp --site personal
```

Configure local Claude Desktop (in `claude_desktop_config.json`):

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

---

### Remote Claude Desktop Config (Access from another machine)

To connect from another Claude machine to this host (`192.168.150.91`), you can use one of the two options below:

#### Option A: SSH Tunneling (Secure & Stdio)

Run standard stdio protocol over a secure SSH connection. Ensure the remote machine has passwordless SSH login configured to your machine (using `ssh-copy-id` or adding public keys to `~/.ssh/authorized_keys`).

Configure Claude Desktop on the remote machine:

```json
{
  "mcpServers": {
    "thinkdome-remote-ssh": {
      "command": "ssh",
      "args": [
        "sandbox@192.168.150.91",
        "/home/sandbox/ThinkDome/venv/bin/python /home/sandbox/ThinkDome/think mcp --site personal"
      ]
    }
  }
}
```

#### Option B: Server-Sent Events (HTTP / SSE)

Expose the MCP server via HTTP/SSE. 

1. Start the ThinkDome server on your host (`192.168.150.91`) binding to all network interfaces:
   ```bash
   python think serve --host 0.0.0.0 --port 8000
   ```

2. Configure Claude Desktop on the remote machine to connect to the SSE endpoint:
   ```json
   {
     "mcpServers": {
       "thinkdome-remote-sse": {
         "url": "http://192.168.150.91:8000/mcp/sse"
       }
     }
   }
   ```

