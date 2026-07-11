"""Agent app hooks."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def on_agent_ready(agent) -> None:
    logger.info(f"[Hook] Agent ready: {agent.name} (model={agent.model})")


def on_agent_error(agent, error=None, **kwargs) -> None:
    logger.error(f"[Hook] Agent error: {agent.name} — {error}")


hooks = {
    "agent.before_execute": [],
    "agent.after_execute": [],
    "agent.on_tool_call": [],
    "agent.on_error": [on_agent_error],
}
