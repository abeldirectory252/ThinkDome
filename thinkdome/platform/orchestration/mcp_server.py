"""ThinkDome Model Context Protocol (MCP) Stdio Server.

Exposes active tools dynamically through standard input/output transport,
executing them safely inside the sandbox context.
"""

from __future__ import annotations

import sys
import time
import uuid
import anyio
import logging
from typing import Optional, List, Dict, Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from thinkdome.core.config import get_settings
from thinkdome.core.kernel.kernel import Kernel
from thinkdome.platform.database.service import DatabaseService
from thinkdome.sandbox.core.service import ExecutionService
from thinkdome.platform.orchestration.search.service import SearchService
from thinkdome.platform.orchestration.orchestrator_service import OrchestratorService
from thinkdome.platform.orchestration.tools import registry
from thinkdome.security.identity.core import ROLE_ADMIN, UserIdentity
from thinkdome.apps.sandbox.models import Sandbox

# Route all logs to standard error to keep stdout free of JSON-RPC protocol noise
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("thinkdome_mcp")


def get_mcp_server(
    site_name: str,
    db_service: DatabaseService,
    orchestrator: OrchestratorService,
    client_ip: str = "127.0.0.1",
    caller_role: str = ROLE_ADMIN,
    username: str = "anonymous",
    identity: Optional[UserIdentity] = None,
) -> Server:
    """Create and configure low-level MCP server instance with dynamic RBAC identity and audit logging."""
    if identity is not None:
        username = str(identity.metadata.get("workspace_id") or identity.username)
        if identity.roles:
            caller_role = next(iter(identity.roles))

    server = Server("ThinkDome Sandbox MCP Server")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        logger.info(f"Listing active tools in ThinkDome registry for user '{username}' (role: {caller_role})...")

        try:
            db_service.log_audit(
                actor=username,
                action="mcp_list_tools",
                ip_address=client_ip,
                details={"site_name": site_name, "caller_role": caller_role}
            )
        except Exception as ae:
            logger.error(f"Failed to log list_tools audit: {ae}")

        active_tools = registry.get_active_tools(site_name)
        mcp_tools = []
        for t in active_tools:
            mcp_tools.append(
                types.Tool(
                    name=t.name,
                    description=t.description,
                    inputSchema=t.input_schema,
                )
            )
        return mcp_tools

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        logger.info(f"Invoking tool call '{name}' as user '{username}' ({caller_role}) with arguments: {arguments}")
        start_time = time.time()

        tool_use = {
            "type": "tool_use",
            "id": f"toolu_{uuid.uuid4().hex}",
            "name": name,
            "input": arguments or {},
        }

        # Resolve active sandbox context pythonically using ThinkDome ORM
        active_sandboxes = Sandbox.query().filter(status="active").all()
        if not active_sandboxes:
            active_sandboxes = Sandbox.query().filter(status="Running").all()

        all_active = [sb.to_dict() for sb in active_sandboxes]
        if not all_active and hasattr(db_service, "list_sandboxes"):
            all_active = db_service.list_sandboxes()

        sandbox_id = None
        sandbox_limits = None

        if all_active:
            sb = all_active[0]
            sandbox_id = sb.get("sandbox_id") or sb.get("id")
            sandbox_limits = {
                "memory_mb": sb.get("memory_mb", 256),
                "cpu_cores": sb.get("cpu_cores", 1.0),
                "timeout_sec": sb.get("timeout_sec", 30),
                "network_enabled": sb.get("network_enabled", False),
            }
        else:
            logger.info("No active sandbox found. Pre-seeding a default sandbox context in database...")
            sandbox_id = "default_mcp_sandbox"
            db_service.create_sandbox(
                sandbox_id=sandbox_id,
                name="Default MCP Sandbox",
                owner=username,
                memory_mb=256,
                cpu_cores=1.0,
                timeout_sec=30,
                network_enabled=False,
                cost_per_hour=0.02,
            )
            sandbox_limits = {
                "memory_mb": 256,
                "cpu_cores": 1.0,
                "timeout_sec": 30,
                "network_enabled": False,
            }

        try:
            res = await orchestrator.execute_tool(
                tool_use=tool_use,
                caller_role=caller_role,
                sandbox_limits=sandbox_limits,
                username=username,
                sandbox_id=sandbox_id,
            )
            content = res.get("content", "")
            duration_ms = (time.time() - start_time) * 1000

            try:
                db_service.log_audit(
                    actor=username,
                    action="mcp_call_tool",
                    ip_address=client_ip,
                    details={
                        "tool_name": name,
                        "arguments": arguments,
                        "caller_role": caller_role,
                        "status": "success",
                        "duration_ms": round(duration_ms, 2),
                        "sandbox_id": sandbox_id,
                    }
                )
            except Exception as ae:
                logger.error(f"Failed to log call_tool audit: {ae}")

            return [types.TextContent(type="text", text=str(content))]
        except Exception as e:
            logger.error(f"Error executing tool {name} via orchestrator: {e}")
            duration_ms = (time.time() - start_time) * 1000

            try:
                db_service.log_audit(
                    actor=username,
                    action="mcp_call_tool",
                    ip_address=client_ip,
                    details={
                        "tool_name": name,
                        "arguments": arguments,
                        "caller_role": caller_role,
                        "status": "error",
                        "error": str(e),
                        "duration_ms": round(duration_ms, 2),
                        "sandbox_id": sandbox_id,
                    }
                )
            except Exception as ae:
                logger.error(f"Failed to log call_tool error audit: {ae}")

            return [types.TextContent(type="text", text=f"Error executing tool: {e}")]

    return server


async def async_main(site_name: str) -> None:
    """Async server launcher setting up services, registering tool listeners, and running transport loop."""
    settings = get_settings()

    kernel = Kernel.get_instance(site_name)
    kernel.initialize()

    db_service = DatabaseService(settings)
    await db_service.initialize()

    execution_service = ExecutionService(settings)
    await execution_service.initialize()

    search_service = SearchService(settings)

    orchestrator = OrchestratorService(
        settings=settings,
        execution_service=execution_service,
        search_service=search_service,
    )
    orchestrator.db = db_service

    server = get_mcp_server(site_name, db_service, orchestrator)

    logger.info("Initializing ThinkDome MCP stdio transport loop...")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def run_mcp_server(site_name: str) -> None:
    """Run stdio-based MCP server for specified site context."""
    anyio.run(async_main, site_name)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Start ThinkDome MCP Server")
    import os
    parser.add_argument("--site", default=os.environ.get("THINKDOME_SITE", "think.local"), help="Site config target")
    args = parser.parse_args()

    run_mcp_server(args.site)
