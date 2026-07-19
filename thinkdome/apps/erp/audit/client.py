"""Read-only audit client wrapping FrappeClient.

AuditClient enforces the fundamental audit principle: auditors observe,
they do NOT modify the system under audit. All write operations are
blocked. Adds caching, trace IDs, and audit-specific convenience methods.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from thinkdome.apps.erp.frappe_client import FrappeClient

logger = logging.getLogger(__name__)


class AuditClientError(Exception):
    """Error raised by the audit client layer."""


class WriteBlockedError(AuditClientError):
    """Raised when a write operation is attempted through the audit client."""

    def __init__(self, operation: str):
        super().__init__(
            f"AUDIT VIOLATION: Write operation '{operation}' is blocked. "
            f"The audit client is read-only. Auditors observe — they do not modify."
        )


class _LRUCache:
    """Simple LRU cache for expensive Frappe API responses."""

    def __init__(self, max_size: int = 256):
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._max_size = max_size
        self.hits = 0
        self.misses = 0

    def _key(self, method: str, args: tuple, kwargs: tuple) -> str:
        raw = f"{method}:{args}:{kwargs}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, method: str, args: tuple, kwargs: tuple) -> Optional[Any]:
        key = self._key(method, args, kwargs)
        if key in self._cache:
            self._cache.move_to_end(key)
            self.hits += 1
            return self._cache[key]
        self.misses += 1
        return None

    def put(self, method: str, args: tuple, kwargs: tuple, value: Any) -> None:
        key = self._key(method, args, kwargs)
        self._cache[key] = value
        self._cache.move_to_end(key)
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()
        self.hits = 0
        self.misses = 0


class AuditClient:
    """Read-only wrapper around FrappeClient for audit operations.

    Blocks all create/update/delete operations.
    Adds response caching and unique trace IDs per request.
    """

    def __init__(self, frappe_client: Optional[FrappeClient] = None, cache_size: int = 256):
        self._client = frappe_client or FrappeClient.from_config()
        self._cache = _LRUCache(max_size=cache_size)
        self._trace_id: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return self._client.is_configured

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    def new_trace(self) -> str:
        """Generate a new audit trace ID for request tracking."""
        self._trace_id = f"AUDIT-{uuid.uuid4().hex[:12].upper()}"
        return self._trace_id

    @property
    def trace_id(self) -> str:
        if not self._trace_id:
            return self.new_trace()
        return self._trace_id

    async def connect(self) -> Dict[str, Any]:
        """Establish connection to ERPNext (delegates to FrappeClient)."""
        return await self._client.connect()

    async def disconnect(self) -> None:
        """Close connection."""
        await self._client.disconnect()

    def clear_cache(self) -> Dict[str, int]:
        """Clear the response cache and return stats."""
        stats = {"hits": self._cache.hits, "misses": self._cache.misses}
        self._cache.clear()
        return stats

    # ── Blocked Write Operations ─────────────────────────────────────────────

    async def create_doc(self, *args: Any, **kwargs: Any) -> None:
        raise WriteBlockedError("create_doc")

    async def update_doc(self, *args: Any, **kwargs: Any) -> None:
        raise WriteBlockedError("update_doc")

    async def delete_doc(self, *args: Any, **kwargs: Any) -> None:
        raise WriteBlockedError("delete_doc")

    # ── Read Operations (with caching) ───────────────────────────────────────

    async def get_doc(
        self, doctype: str, name: str, fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Fetch a single document (cached)."""
        cache_key_args = (doctype, name, tuple(fields or []))
        cached = self._cache.get("get_doc", cache_key_args, ())
        if cached is not None:
            return cached

        if not self._client.is_connected:
            await self._client.connect()

        result = await self._client.get_doc(doctype, name, fields)
        self._cache.put("get_doc", cache_key_args, (), result)
        return result

    async def get_list(
        self,
        doctype: str,
        filters: Optional[Dict | List] = None,
        fields: Optional[List[str]] = None,
        order_by: str = "modified desc",
        limit_start: int = 0,
        limit_page_length: int = 100,
    ) -> List[Dict[str, Any]]:
        """List documents with filters (cached)."""
        cache_args = (
            doctype,
            json.dumps(filters, sort_keys=True) if filters else "",
            tuple(fields or []),
            order_by,
            limit_start,
            limit_page_length,
        )
        cached = self._cache.get("get_list", cache_args, ())
        if cached is not None:
            return cached

        if not self._client.is_connected:
            await self._client.connect()

        result = await self._client.get_list(
            doctype, filters, fields, order_by, limit_start, limit_page_length
        )
        self._cache.put("get_list", cache_args, (), result)
        return result

    async def get_count(
        self, doctype: str, filters: Optional[Dict] = None
    ) -> int:
        """Count documents matching filters."""
        if not self._client.is_connected:
            await self._client.connect()
        return await self._client.get_count(doctype, filters)

    async def run_report(
        self, report_name: str, filters: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Run a Frappe report (cached)."""
        cache_args = (report_name, json.dumps(filters, sort_keys=True) if filters else "")
        cached = self._cache.get("run_report", cache_args, ())
        if cached is not None:
            return cached

        if not self._client.is_connected:
            await self._client.connect()

        result = await self._client.run_report(report_name, filters)
        self._cache.put("run_report", cache_args, (), result)
        return result

    async def call_method(self, method: str, args: Optional[Dict] = None) -> Any:
        """Call a whitelisted read-only Frappe method."""
        if not self._client.is_connected:
            await self._client.connect()
        return await self._client.call_method(method, args)

    async def get_list_all(
        self,
        doctype: str,
        filters: Optional[Dict] = None,
        fields: Optional[List[str]] = None,
        order_by: str = "modified desc",
        max_records: int = 5000,
    ) -> List[Dict[str, Any]]:
        """Fetch all records with internal pagination."""
        if not self._client.is_connected:
            await self._client.connect()
        return await self._client.get_list_all(doctype, filters, fields, order_by, max_records)

    # ── Audit-Specific Convenience Methods ───────────────────────────────────

    async def get_doc_with_history(self, doctype: str, name: str) -> Dict[str, Any]:
        """Fetch a document along with its version history."""
        doc = await self.get_doc(doctype, name)

        # Fetch version log
        versions = await self.get_list(
            "Version",
            filters={"ref_doctype": doctype, "ref_name": name},
            fields=["name", "owner", "creation", "data"],
            order_by="creation asc",
            limit_page_length=100,
        )

        return {
            "document": doc,
            "version_history": versions,
            "version_count": len(versions),
        }

    async def get_doc_timeline(self, doctype: str, name: str) -> Dict[str, Any]:
        """Fetch the complete activity timeline for a document."""
        # Activity log
        activities = await self.get_list(
            "Activity Log",
            filters={"reference_doctype": doctype, "reference_name": name},
            fields=["name", "owner", "creation", "subject", "content", "communication_date"],
            order_by="creation asc",
            limit_page_length=200,
        )

        # Comments
        comments = await self.get_list(
            "Comment",
            filters={"reference_doctype": doctype, "reference_name": name},
            fields=["name", "owner", "creation", "content", "comment_type"],
            order_by="creation asc",
            limit_page_length=200,
        )

        return {
            "doctype": doctype,
            "name": name,
            "activities": activities,
            "comments": comments,
        }

    async def get_version_log(self, doctype: str, name: str) -> List[Dict[str, Any]]:
        """Fetch parsed version change log for a document."""
        versions = await self.get_list(
            "Version",
            filters={"ref_doctype": doctype, "ref_name": name},
            fields=["name", "owner", "creation", "data"],
            order_by="creation asc",
            limit_page_length=100,
        )

        parsed = []
        for v in versions:
            entry = {
                "version": v.get("name"),
                "changed_by": v.get("owner"),
                "changed_at": v.get("creation"),
                "changes": [],
            }
            raw_data = v.get("data", "")
            if raw_data:
                try:
                    data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                    entry["changes"] = data.get("changed", [])
                except (json.JSONDecodeError, AttributeError):
                    entry["changes"] = [{"raw": str(raw_data)[:500]}]
            parsed.append(entry)

        return parsed
