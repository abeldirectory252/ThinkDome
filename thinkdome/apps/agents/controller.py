"""Agent Execution Controller.

Manages agent lifecycle: initialization, step-loop execution,
tool dispatch, result collection, and error handling.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from thinkdome.apps.agents.models import Agent
from thinkdome.core.hooks.hooks import manager as hook_manager
from thinkdome.core.events.events import emit

logger = logging.getLogger(__name__)


async def initialize_agent(agent: Agent) -> None:
    """Prepare an agent for execution by validating its configuration."""
    await hook_manager.run("agent.before_execute", agent)
    agent.status = "Ready"
    agent.save()
    await emit("agent.ready", {"agent_id": agent.id, "model": agent.model})


async def execute_agent(agent: Agent, task: str) -> Dict[str, Any]:
    """Run the agent step-loop, dispatching tool calls until completion or failure.

    Args:
        agent: The Agent model instance to execute.
        task: The user instruction or prompt to process.

    Returns:
        Dict containing result output, step count, and duration.
    """
    agent.status = "Executing"
    agent.save()
    await emit("agent.executing", {"agent_id": agent.id, "task": task})

    start_time = time.time()
    steps_taken = 0
    tools = json.loads(agent.tools) if agent.tools else []
    memory = json.loads(agent.memory) if agent.memory else {}

    try:
        # Simulate step-loop execution
        # In production this would call the LLM API and dispatch tool calls
        for step in range(agent.max_steps):
            steps_taken += 1

            # Fire hook for each tool call opportunity
            await hook_manager.run("agent.on_tool_call", agent, step=step)

            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > agent.timeout_sec:
                raise TimeoutError(f"Agent exceeded {agent.timeout_sec}s timeout")

            # Simulated completion condition
            # Real implementation would check LLM response for stop token
            if step >= 1:
                break

        duration_ms = (time.time() - start_time) * 1000
        result = {
            "output": f"Agent '{agent.name}' completed task: {task}",
            "steps": steps_taken,
            "duration_ms": round(duration_ms, 2),
            "memory": memory,
        }

        agent.status = "Completed"
        agent.result = json.dumps(result)
        agent.save()

        await hook_manager.run("agent.after_execute", agent)
        await emit("agent.completed", {"agent_id": agent.id, "result": result})
        return result

    except Exception as e:
        agent.status = "Failed"
        agent.error_message = str(e)
        agent.save()

        await hook_manager.run("agent.on_error", agent, error=e)
        await emit("agent.failed", {"agent_id": agent.id, "error": str(e)})
        logger.error(f"Agent '{agent.name}' failed: {e}")
        return {"error": str(e), "steps": steps_taken}
