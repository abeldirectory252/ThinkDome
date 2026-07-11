"""ThinkDome Scheduler.

Runs recurring framework actions (cleanup, metrics aggregator, reports)
at set minute, hourly, or daily intervals.
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from typing import Any, Callable, List, Tuple

logger = logging.getLogger(__name__)

# Registry for scheduled actions: (callback, interval_minutes, last_run_timestamp)
_scheduled_tasks: List[Tuple[Callable[[], None], int, float]] = []


def register_scheduled(interval_minutes: int) -> Callable:
    """Decorator to register a recurring task running at set minute intervals."""
    def decorator(func: Callable) -> Callable:
        _scheduled_tasks.append((func, interval_minutes, 0.0))
        return func
    return decorator


class Scheduler:
    """Cron scheduler loop checking and running registered recurring tasks."""

    def __init__(self, site_name: str) -> None:
        self.site_name = site_name
        self.running = False

    def start(self) -> None:
        """Boots site context and runs task evaluations every minute."""
        self.running = True
        from thinkdome.core.kernel.kernel import Kernel
        kernel = Kernel.get_instance(self.site_name)
        kernel.initialize()

        logger.info(f"Scheduler booted. Evaluating tasks for site '{self.site_name}'...")

        while self.running:
            try:
                self._run_due_tasks()
                # Check at 10-second intervals to minimize load but stay responsive
                time.sleep(10.0)
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                time.sleep(10.0)

    def _run_due_tasks(self) -> None:
        """Identify and invoke tasks whose time intervals have elapsed."""
        now = time.time()
        for i, (task_fn, interval, last_run) in enumerate(_scheduled_tasks):
            elapsed_minutes = (now - last_run) / 60.0
            if elapsed_minutes >= interval:
                logger.info(f"Triggering scheduled cron: {task_fn.__name__}")
                try:
                    # Update timestamp before run to prevent re-entrant loops
                    _scheduled_tasks[i] = (task_fn, interval, now)
                    task_fn()
                except Exception as e:
                    logger.error(f"Scheduled task '{task_fn.__name__}' failed: {e}")
