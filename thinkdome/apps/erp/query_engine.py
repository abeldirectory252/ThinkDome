"""ERP Query Engine.

Provides raw query capabilities, Frappe REST API integrations, and local caching
mechanisms to let AI agents inspect and query data tables directly.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from thinkdome.orchestration.tools import get_context
from thinkdome.apps.erp.frappe_client import FrappeClient

logger = logging.getLogger(__name__)


class QueryEngine:
    """Core translation layer running raw SQL locally or delegating schema and requests to Frappe REST API."""

    def __init__(self, frappe_client: Optional[FrappeClient] = None) -> None:
        self.frappe_client = frappe_client or FrappeClient.from_config()

    def execute_local_sql(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Run raw read-only SQL queries directly against ThinkDome's local cache database.

        Limits query scope to read-only queries (SELECT) to maintain security profiles.
        """
        # Security sanitization check: only allow SELECT queries
        sanitized = query.strip().upper()
        if not sanitized.startswith("SELECT") and not sanitized.startswith("WITH"):
            raise PermissionError("Security restriction: Only SELECT or WITH queries are permitted through the local query endpoint.")

        ctx = get_context()
        if not hasattr(ctx, "db") or ctx.db is None:
            raise RuntimeError("Database connection not available in the current ToolContext.")

        # Run query through the site-level database driver wrapper
        try:
            return ctx.db.fetch_all(query, params)
        except Exception as e:
            logger.error(f"SQL Execution error: {e}")
            raise RuntimeError(f"Database query failed: {e}")

    async def execute_frappe_query(
        self,
        doctype: str,
        filters: Optional[Dict[str, Any]] = None,
        fields: Optional[List[str]] = None,
        order_by: str = "modified desc",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Query a remote Frappe DocType table using filters and fields."""
        if not self.frappe_client.is_connected:
            await self.frappe_client.connect()

        if not self.frappe_client.is_configured:
            raise RuntimeError("Frappe server URL not configured. Fill in your erp/config.json settings.")

        try:
            return await self.frappe_client.get_list(
                doctype=doctype,
                filters=filters,
                fields=fields,
                order_by=order_by,
                limit_page_length=limit
            )
        except Exception as e:
            logger.error(f"Frappe Query failed for DocType '{doctype}': {e}")
            raise RuntimeError(f"Frappe connection/query failed: {e}")

    async def get_doctype_schema(self, doctype: str) -> Dict[str, Any]:
        """Describe remote DocType field structure, validations, and links."""
        if not self.frappe_client.is_connected:
            await self.frappe_client.connect()

        if not self.frappe_client.is_configured:
            # Fallback schema list for basic bookkeeping if not connected
            return self._get_local_schema_stub(doctype)

        try:
            meta = await self.frappe_client.get_meta(doctype)
            fields = []
            for f in meta.get("fields", []):
                fields.append({
                    "name": f.get("fieldname"),
                    "type": f.get("fieldtype"),
                    "label": f.get("label"),
                    "required": bool(f.get("reqd")),
                    "options": f.get("options")
                })
            return {
                "name": meta.get("name"),
                "module": meta.get("module"),
                "fields": fields
            }
        except Exception as e:
            logger.error(f"Failed to fetch metadata for DocType '{doctype}': {e}")
            # Fallback local schema stub
            return self._get_local_schema_stub(doctype)

    async def list_doctypes(self) -> List[str]:
        """List all available DocTypes from remote Frappe server or fallback stubs."""
        if not self.frappe_client.is_connected:
            await self.frappe_client.connect()

        if not self.frappe_client.is_configured:
            return [
                "Account", "Journal Entry", "Sales Invoice", "Purchase Invoice",
                "Payment Entry", "Bank Account", "Budget", "Employee", "Item"
            ]

        try:
            # Fetch all doctypes
            res = await self.frappe_client.get_list("DocType", fields=["name"], limit_page_length=500)
            return [d["name"] for d in res]
        except Exception as e:
            logger.error(f"Failed to list doctypes: {e}")
            return [
                "Account", "Journal Entry", "Sales Invoice", "Purchase Invoice",
                "Payment Entry", "Bank Account", "Budget", "Employee", "Item"
            ]

    async def sync_data_to_local(self, doctype: str, filters: Optional[Dict] = None) -> Dict[str, Any]:
        """Sync remote Frappe DocType table entries to the local cache database."""
        if not self.frappe_client.is_connected:
            await self.frappe_client.connect()

        if not self.frappe_client.is_configured:
            return {"status": "error", "message": "Frappe server not configured."}

        try:
            # Map Frappe DocTypes to local ORM Models
            model_class = self._get_model_class_for_doctype(doctype)
            if not model_class:
                return {
                    "status": "error",
                    "message": f"No local ORM model matching Frappe DocType '{doctype}' is available to write into."
                }

            records = await self.frappe_client.get_list_all(doctype, filters=filters)
            count = 0
            for item in records:
                # Map fields to match local columns
                mapped_data = self._map_frappe_to_local(doctype, item)
                # Save locally using ORM save
                local_inst = model_class(**mapped_data)
                local_inst.save()
                count += 1

            return {
                "status": "success",
                "doctype": doctype,
                "records_synced": count
            }
        except Exception as e:
            logger.error(f"Sync failed for '{doctype}': {e}")
            return {"status": "error", "message": str(e)}

    # ── Utility Helpers ───────────────────────────────────────────────────────

    def _get_local_schema_stub(self, doctype: str) -> Dict[str, Any]:
        """Provide mock schema descriptions if offline or remote server cannot be reached."""
        from thinkdome.core.metadata.metadata import get_doctype_model
        model = get_doctype_model(doctype) or self._get_model_class_for_doctype(doctype)
        if not model:
            return {"name": doctype, "fields": [{"name": "name", "type": "String", "label": "Name"}]}

        fields = []
        for name, field in model._fields.items():
            fields.append({
                "name": name,
                "type": field.__class__.__name__.replace("Field", ""),
                "required": field.required,
                "options": getattr(field, "choices", None)
            })
        return {
            "name": model.__name__,
            "fields": fields
        }

    def _get_model_class_for_doctype(self, doctype: str) -> Optional[Any]:
        """Resolve remote DocType string representation to local ORM model class."""
        # Simple name normalization mapping
        norm_map = {
            "Account": "Account",
            "Journal Entry": "JournalEntry",
            "Sales Invoice": "SalesInvoice",
            "Purchase Invoice": "PurchaseInvoice",
            "Payment Entry": "Payment",
            "Bank Account": "BankAccount",
            "Budget": "Budget",
            "Employee": "Employee",
            "Item": "Item"
        }
        local_name = norm_map.get(doctype, doctype.replace(" ", ""))
        from thinkdome.core.metadata.metadata import get_doctype_model
        return get_doctype_model(local_name)

    def _map_frappe_to_local(self, doctype: str, frappe_item: Dict[str, Any]) -> Dict[str, Any]:
        """Convert key naming styles from Frappe JSON payload to local ORM columns."""
        # Custom maps
        mapped = {}
        for k, v in frappe_item.items():
            if k == "name":
                mapped["id"] = v
            else:
                mapped[k] = v
        return mapped
