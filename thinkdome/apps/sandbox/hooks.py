"""Sandbox Lifecycle Hooks."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def on_before_provision(sandbox_model) -> None:
    logger.info(f"[Hook] Preparing provisioning sequence for sandbox: {sandbox_model.name}")


def on_after_start(sandbox_model) -> None:
    logger.info(f"[Hook] Sandbox started successfully: {sandbox_model.id}")


hooks = {
    "sandbox.before_provision": [on_before_provision],
    "sandbox.after_start": [on_after_start],
}
