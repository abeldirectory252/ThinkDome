"""Workflow Execution Engine.

Traverses a directed node-graph, evaluating conditions, dispatching actions,
pausing on human approval gates, and collecting step results.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from thinkdome.apps.workflows.models import Workflow, WorkflowExecution
from thinkdome.core.events.events import emit
from thinkdome.core.hooks.hooks import manager as hook_manager

logger = logging.getLogger(__name__)

# Action handlers registered by name
_action_handlers: Dict[str, Callable] = {}


def register_action(name: str) -> Callable:
    """Decorator to register a workflow action handler by name."""
    def decorator(func: Callable) -> Callable:
        _action_handlers[name] = func
        return func
    return decorator


# ── Built-in Actions ──────────────────────────────────────────────────────────

@register_action("log")
async def action_log(payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Log a message during workflow execution."""
    msg = payload.get("message", "")
    logger.info(f"[Workflow] {msg}")
    return {"logged": msg}


@register_action("create_sandbox")
async def action_create_sandbox(payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Create a sandbox as a workflow step."""
    from thinkdome.apps.sandbox.models import Sandbox
    from thinkdome.apps.sandbox.controller import create_sandbox

    sandbox = Sandbox(
        name=payload.get("name", "workflow-sandbox"),
        runtime=payload.get("runtime", "docker"),
        image=payload.get("image", "python:3.12-slim"),
        owner=context.get("started_by", "system"),
    )
    sandbox_id = await create_sandbox(sandbox)
    return {"sandbox_id": sandbox_id}


@register_action("run_agent")
async def action_run_agent(payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute an agent as a workflow step."""
    from thinkdome.apps.agents.models import Agent
    from thinkdome.apps.agents.controller import initialize_agent, execute_agent

    agent = Agent(
        name=payload.get("name", "workflow-agent"),
        model=payload.get("model", "gpt-4o"),
        owner=context.get("started_by", "system"),
        sandbox_id=context.get("sandbox_id", ""),
    )
    agent.save()
    await initialize_agent(agent)
    result = await execute_agent(agent, payload.get("task", ""))
    return result


@register_action("destroy_sandbox")
async def action_destroy_sandbox(payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Destroy a sandbox after workflow completes."""
    from thinkdome.apps.sandbox.models import Sandbox
    from thinkdome.apps.sandbox.controller import destroy_sandbox

    sandbox_id = payload.get("sandbox_id") or context.get("sandbox_id")
    if sandbox_id:
        sandbox = Sandbox.get(sandbox_id)
        if sandbox:
            await destroy_sandbox(sandbox)
    return {"destroyed": sandbox_id}


# ── Engine ────────────────────────────────────────────────────────────────────

async def start_workflow(workflow: Workflow, trigger_data: Dict[str, Any] = None) -> WorkflowExecution:
    """Begin a new execution of a workflow definition."""
    execution = WorkflowExecution(
        workflow_id=workflow.id,
        trigger_data=json.dumps(trigger_data or {}),
        status="Running",
        started_by=trigger_data.get("started_by", "system") if trigger_data else "system",
    )
    execution.save()

    await emit("workflow.started", {"workflow_id": workflow.id, "execution_id": execution.id})
    logger.info(f"Starting workflow '{workflow.name}' (execution={execution.id})")

    nodes = json.loads(workflow.nodes)
    edges = json.loads(workflow.edges)
    context: Dict[str, Any] = {"started_by": execution.started_by}
    if trigger_data:
        context.update(trigger_data)

    try:
        await _traverse_nodes(execution, nodes, edges, context)
    except Exception as e:
        execution.status = "Failed"
        execution.error_message = str(e)
        execution.save()
        await emit("workflow.failed", {"execution_id": execution.id, "error": str(e)})
        logger.error(f"Workflow execution {execution.id} failed: {e}")

    return execution


async def _traverse_nodes(
    execution: WorkflowExecution,
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    context: Dict[str, Any],
    start_nodes: Optional[List[str]] = None,
) -> None:
    """Walk through nodes following edges, evaluating conditions and dispatching actions."""
    step_results = []

    # Build adjacency list
    adjacency: Dict[str, List[Dict[str, Any]]] = {}
    for edge in edges:
        adjacency.setdefault(edge["from"], []).append(edge)

    if start_nodes is not None:
        queue = list(start_nodes)
    else:
        # Find entry node (first node or one with no incoming edges)
        incoming = {e["to"] for e in edges}
        entry_nodes = [n for n in nodes if n["id"] not in incoming]
        if not entry_nodes:
            entry_nodes = nodes[:1]
        queue = [entry_nodes[0]["id"]] if entry_nodes else []
    visited = set()

    while queue:
        node_id = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)

        node = next((n for n in nodes if n["id"] == node_id), None)
        if not node:
            continue

        execution.current_node = node_id
        execution.save()

        node_type = node.get("type", "action")

        # ── Approval Gate ──
        if node_type == "approval":
            execution.status = "WaitingApproval"
            execution.save()
            await emit("workflow.approval_required", {
                "execution_id": execution.id,
                "node_id": node_id,
                "message": node.get("message", "Approval required"),
            })
            logger.info(f"Workflow paused at approval gate: {node_id}")
            return  # Suspend until approval callback

        # ── Condition Branch ──
        if node_type == "condition":
            field = node.get("field", "")
            operator = node.get("operator", "==")
            value = node.get("value", "")
            actual = context.get(field, "")

            condition_met = False
            if operator == "==" and str(actual) == str(value):
                condition_met = True
            elif operator == "!=" and str(actual) != str(value):
                condition_met = True
            elif operator == ">" and float(actual) > float(value):
                condition_met = True

            # Follow matching edge
            for edge in adjacency.get(node_id, []):
                edge_cond = edge.get("condition", "true")
                if (condition_met and edge_cond == "true") or (not condition_met and edge_cond == "false"):
                    queue.append(edge["to"])
            step_results.append({"node": node_id, "type": "condition", "result": condition_met})
            continue

        # ── Action Node ──
        action_name = node.get("action", "log")
        payload = node.get("payload", {})

        handler = _action_handlers.get(action_name)
        if handler:
            result = await handler(payload, context)
            # Merge results into context for downstream nodes
            if isinstance(result, dict):
                context.update(result)
            step_results.append({"node": node_id, "action": action_name, "result": result})
        else:
            logger.warning(f"No handler for workflow action '{action_name}'")
            step_results.append({"node": node_id, "action": action_name, "error": "handler not found"})

        # Follow outgoing edges
        for edge in adjacency.get(node_id, []):
            queue.append(edge["to"])

    # All nodes traversed
    execution.step_results = json.dumps(step_results)
    execution.status = "Completed"
    execution.save()
    await emit("workflow.completed", {"execution_id": execution.id, "results": step_results})
    logger.info(f"Workflow execution {execution.id} completed successfully.")


async def approve_execution(execution_id: str) -> None:
    """Resume a workflow paused at an approval gate."""
    execution = WorkflowExecution.get(execution_id)
    if not execution or execution.status != "WaitingApproval":
        raise ValueError(f"Execution {execution_id} is not awaiting approval")

    workflow = Workflow.get(execution.workflow_id)
    if not workflow:
        raise ValueError(f"Workflow {execution.workflow_id} not found")

    execution.status = "Running"
    execution.save()

    nodes = json.loads(workflow.nodes)
    edges = json.loads(workflow.edges)
    context = json.loads(execution.trigger_data)

    # Resume from the approval node's successors
    adjacency: Dict[str, List[Dict[str, Any]]] = {}
    for edge in edges:
        adjacency.setdefault(edge["from"], []).append(edge)

    next_nodes = [e["to"] for e in adjacency.get(execution.current_node, [])]
    # Re-traverse from next nodes
    await _traverse_nodes(execution, nodes, edges, context, start_nodes=next_nodes)
