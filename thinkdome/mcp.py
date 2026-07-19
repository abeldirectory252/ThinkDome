"""ThinkDome Model Context Protocol (MCP) Stdio Server.

Exposes active tools dynamically through standard input/output transport,
executing them safely inside the sandbox context.
"""

from __future__ import annotations

import sys
import uuid
import anyio
import logging
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from thinkdome.core.config import get_settings
from thinkdome.core.kernel.kernel import Kernel
from thinkdome.modules.database.db_service import DatabaseService
from thinkdome.modules.execution.execution_service import ExecutionService
from thinkdome.modules.search.search_service import SearchService
from thinkdome.modules.orchestrator.orchestrator_service import OrchestratorService
from thinkdome.core.tools import registry

# Route all logs to standard error to keep stdout free of JSON-RPC protocol noise
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("thinkdome_mcp")


async def async_main(site_name: str) -> None:
    """Async server launcher setting up services, registering tool listeners, and running transport loop."""
    settings = get_settings()

    # 1. Initialize framework Kernel context
    kernel = Kernel.get_instance(site_name)
    kernel.initialize()

    # 2. Instantiate orchestrator database and backend services
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
    # Inject db_service for sandbox verification checks
    orchestrator.db = db_service

    # 3. Create low-level MCP server instance
    server = Server("ThinkDome Sandbox MCP Server")

    # 4. Handle List Tools
    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        logger.info("Listing active tools in ThinkDome registry...")
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

    # 5. Handle Call Tool
    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        logger.info(f"Invoking tool call: {name} (arguments: {arguments})")

        # Format request as an Orchestrator tool use request block
        tool_use = {
            "type": "tool_use",
            "id": f"toolu_{uuid.uuid4().hex}",
            "name": name,
            "input": arguments or {},
        }

        # Resolve or pre-seed sandbox context for execution check
        all_active = db_service.fetch_all("SELECT * FROM sandboxes WHERE status = 'active'")
        sandbox_id = None
        sandbox_limits = None

        if all_active:
            sb = all_active[0]
            sandbox_id = sb.get("sandbox_id")
            sandbox_limits = {
                "memory_mb": sb.get("memory_mb"),
                "cpu_cores": sb.get("cpu_cores"),
                "timeout_sec": sb.get("timeout_sec"),
                "network_enabled": sb.get("network_enabled"),
            }
        else:
            logger.info("No active sandbox found. Pre-seeding a default sandbox context in database...")
            sandbox_id = "default_mcp_sandbox"
            db_service.create_sandbox(
                sandbox_id=sandbox_id,
                name="Default MCP Sandbox",
                owner="anonymous",
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
            # Delegate tool execution to OrchestratorService
            res = await orchestrator.execute_tool(
                tool_use=tool_use,
                caller_role="ADMIN",  # Execute with ADMIN role privileges for MCP integrations
                sandbox_limits=sandbox_limits,
                username="anonymous",
                sandbox_id=sandbox_id,
            )
            content = res.get("content", "")
            return [types.TextContent(type="text", text=str(content))]
        except Exception as e:
            logger.error(f"Error executing tool {name} via orchestrator: {e}")
            return [types.TextContent(type="text", text=f"Error executing tool: {e}")]

    # 6. Run Stdio Server Transport loop
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
    parser.add_argument("--site", default="personal", help="Site config target")
    args = parser.parse_args()

    run_mcp_server(args.site)
