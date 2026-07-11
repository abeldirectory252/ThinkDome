"""ThinkDome Background Task Queue.

Implements job scheduling, serialization, worker loops, and dead-letter failure handling
backed by the database to ensure zero-dependency portability.
"""

from __future__ import annotations

import json
import time
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Global registry matching task names to execution handlers
_task_registry: Dict[str, Callable[[Dict[str, Any]], None]] = {}


def register_task(task_name: str) -> Callable:
    """Decorator to register a function as a background task handler."""
    def decorator(func: Callable) -> Callable:
        _task_registry[task_name] = func
        return func
    return decorator


def enqueue(task_name: str, payload: Dict[str, Any], priority: int = 100) -> None:
    """Queue a task for execution by inserting it into the database queue table."""
    from thinkdome.core.kernel.kernel import Kernel
    kernel = Kernel.current()

    payload_json = json.dumps(payload)
    now_str = datetime.now(timezone.utc).isoformat()

    # Use raw query adapter to avoid ORM circular import issues
    query = (
        "INSERT INTO queue_jobs (task_name, payload, status, priority, retry_count, max_retries, created_at, run_at) "
        "VALUES (:task_name, :payload, 'queued', :priority, 0, 3, :created_at, :run_at)"
    )
    params = {
        "task_name": task_name,
        "payload": payload_json,
        "priority": priority,
        "created_at": now_str,
        "run_at": now_str,
    }

    # Ensure table exists before enqueue
    kernel.db.execute(text(
        "CREATE TABLE IF NOT EXISTS queue_jobs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "task_name TEXT NOT NULL,"
        "payload TEXT NOT NULL,"
        "status TEXT DEFAULT 'queued',"
        "priority INTEGER DEFAULT 100,"
        "retry_count INTEGER DEFAULT 0,"
        "max_retries INTEGER DEFAULT 3,"
        "error_message TEXT,"
        "created_at TEXT,"
        "run_at TEXT"
        ")"
    ))
    kernel.db.execute(text(query), params)
    kernel.db.commit()
    logger.info(f"✓ Enqueued background task: {task_name}")


class QueueWorker:
    """Background processor looping through pending DB jobs and running handlers."""

    def __init__(self, site_name: str) -> None:
        self.site_name = site_name
        self.running = False

    def start(self) -> None:
        """Run worker process loop, checking database for new queued tasks."""
        self.running = True
        from thinkdome.core.kernel.kernel import Kernel
        kernel = Kernel.get_instance(self.site_name)
        kernel.initialize()

        logger.info(f"Worker booted. Listening for background jobs on site '{self.site_name}'...")

        while self.running:
            try:
                job = self._fetch_next_job(kernel)
                if job:
                    self._process_job(kernel, job)
                else:
                    time.sleep(2.0)  # Polling interval
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                time.sleep(5.0)

    def _fetch_next_job(self, kernel: Kernel) -> Optional[Dict[str, Any]]:
        """Atomically lock and fetch the next queued job."""
        # Find next job
        select_query = (
            "SELECT * FROM queue_jobs WHERE status = 'queued' "
            "ORDER BY priority ASC, id ASC LIMIT 1"
        )
        row = kernel.db.execute(text(select_query)).first()
        if not row:
            return None

        # Cast Row to dictionary to mutate
        job = dict(row._mapping)
        
        # Mark as processing
        update_query = "UPDATE queue_jobs SET status = 'processing' WHERE id = :id"
        kernel.db.execute(text(update_query), {"id": job["id"]})
        kernel.db.commit()
        return job

    def _process_job(self, kernel: Kernel, job: Dict[str, Any]) -> None:
        """Invoke mapped task handler, capturing exceptions for retry logic."""
        task_name = job["task_name"]
        payload = json.loads(job["payload"])
        logger.info(f"[{job['id']}] Running task '{task_name}'...")

        handler = _task_registry.get(task_name)
        if not handler:
            err_msg = f"No handler registered for task '{task_name}'"
            logger.error(err_msg)
            self._mark_failed(kernel, job, err_msg)
            return

        try:
            handler(payload)
            # Mark completed
            kernel.db.execute(
                text("UPDATE queue_jobs SET status = 'completed' WHERE id = :id"),
                {"id": job["id"]},
            )
            kernel.db.commit()
            logger.info(f"[{job['id']}] Task '{task_name}' successfully completed.")
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"[{job['id']}] Task failed with exception: {e}")
            self._handle_failure(kernel, job, tb)

    def _handle_failure(self, kernel: Kernel, job: Dict[str, Any], error_msg: str) -> None:
        """Retry the task if retry count limit has not been reached, else mark failed."""
        retries = job["retry_count"] + 1
        if retries <= job["max_retries"]:
            logger.info(f"[{job['id']}] Retrying job (attempt {retries}/{job['max_retries']})")
            kernel.db.execute(
                text("UPDATE queue_jobs SET status = 'queued', retry_count = :retries, error_message = :err WHERE id = :id"),
                {"retries": retries, "err": error_msg, "id": job["id"]},
            )
        else:
            self._mark_failed(kernel, job, error_msg)
        kernel.db.commit()

    def _mark_failed(self, kernel: Kernel, job: Dict[str, Any], error_msg: str) -> None:
        """Move job to dead-letter state."""
        logger.warning(f"[{job['id']}] Job exceeded retry limit. Marked as failed.")
        kernel.db.execute(
            text("UPDATE queue_jobs SET status = 'failed', error_message = :err WHERE id = :id"),
            {"err": error_msg, "id": job["id"]},
        )
