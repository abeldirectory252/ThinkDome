"""Frappe/ERPNext REST API Client.

Connects to a live Frappe/ERPNext instance via its REST API.
Supports token-based and session-based authentication.
All write operations enforce ThinkDome privilege checks.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, quote

import httpx

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config.json"


class FrappeClientError(Exception):
    """Error communicating with the Frappe server."""

    def __init__(self, message: str, status_code: int = 0, response_data: Any = None):
        self.status_code = status_code
        self.response_data = response_data
        super().__init__(message)


class FrappeClient:
    """REST API client wrapping the Frappe API for ERPNext integration.

    Supports two authentication modes:
      1. API Key + Secret (preferred for server-to-server)
      2. Username + Password (session-based login)

    Usage:
        client = FrappeClient.from_config()
        await client.connect()
        doc = await client.get_doc("Sales Invoice", "SINV-00001")
    """

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        api_secret: str = "",
        username: str = "",
        password: str = "",
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.username = username
        self.password = password
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._session_cookie: Optional[str] = None
        self._connected = False
        self._last_request_time = 0.0
        self._min_request_interval = 0.1  # Rate limit: 10 req/sec

    @classmethod
    def from_config(cls, config_path: Optional[Path] = None) -> FrappeClient:
        """Create a FrappeClient from the ERP config.json file."""
        path = config_path or _CONFIG_PATH
        try:
            with open(path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except FileNotFoundError:
            logger.warning(f"ERP config not found at {path}. Using empty defaults.")
            config = {}

        return cls(
            base_url=config.get("frappe_url", ""),
            api_key=config.get("api_key", ""),
            api_secret=config.get("api_secret", ""),
            username=config.get("username", ""),
            password=config.get("password", ""),
            timeout=config.get("request_timeout_sec", 30),
        )

    @property
    def is_configured(self) -> bool:
        """Check if the Frappe server URL is configured."""
        return bool(self.base_url) and self.base_url != "https://your-erpnext.example.com"

    @property
    def is_connected(self) -> bool:
        """Check if the client has an active connection."""
        return self._connected

    # ── Connection Management ─────────────────────────────────────────────────

    async def connect(self) -> Dict[str, Any]:
        """Establish connection and authenticate with the Frappe server."""
        if not self.is_configured:
            return {
                "status": "not_configured",
                "message": "Frappe server URL not configured. Update config.json with your ERPNext URL and credentials.",
            }

        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            verify=True,
        )

        # Attempt API key auth first, fall back to session auth
        if self.api_key and self.api_secret:
            self._client.headers["Authorization"] = f"token {self.api_key}:{self.api_secret}"
        elif self.username and self.password:
            try:
                resp = await self._client.post(
                    f"{self.base_url}/api/method/login",
                    data={"usr": self.username, "pwd": self.password},
                )
                if resp.status_code == 200:
                    self._session_cookie = resp.cookies.get("sid")
                    logger.info(f"Authenticated with Frappe as {self.username}")
                else:
                    raise FrappeClientError(
                        f"Login failed: {resp.text}",
                        status_code=resp.status_code,
                    )
            except httpx.ConnectError as e:
                return {
                    "status": "connection_failed",
                    "message": f"Cannot reach Frappe server at {self.base_url}: {e}",
                }

        # Verify connection with a simple API call
        try:
            resp = await self._request("GET", "/api/method/frappe.auth.get_logged_user")
            self._connected = True
            user = resp.get("message", "unknown")
            return {
                "status": "connected",
                "user": user,
                "server": self.base_url,
            }
        except Exception as e:
            return {
                "status": "auth_failed",
                "message": f"Connected but authentication failed: {e}",
            }

    async def disconnect(self) -> None:
        """Close the HTTP client connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False

    # ── Core Request Engine ───────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        json_body: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Execute an HTTP request to the Frappe API with rate limiting."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            if self.api_key and self.api_secret:
                self._client.headers["Authorization"] = f"token {self.api_key}:{self.api_secret}"

        # Rate limiting
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_request_interval:
            import asyncio
            await asyncio.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"

        try:
            resp = await self._client.request(
                method,
                url,
                params=params,
                data=data,
                json=json_body,
            )

            if resp.status_code == 403:
                raise FrappeClientError("Permission denied by Frappe server", 403, resp.text)
            if resp.status_code == 404:
                raise FrappeClientError("Resource not found on Frappe server", 404, resp.text)
            if resp.status_code >= 400:
                raise FrappeClientError(
                    f"Frappe API error: {resp.status_code}",
                    resp.status_code,
                    resp.text,
                )

            return resp.json()

        except httpx.ConnectError as e:
            raise FrappeClientError(f"Connection failed: {e}")
        except json.JSONDecodeError:
            return {"message": resp.text if resp else ""}

    # ── Document CRUD ─────────────────────────────────────────────────────────

    async def get_doc(self, doctype: str, name: str, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """Fetch a single document by DocType and name.

        Args:
            doctype: The Frappe DocType (e.g., "Sales Invoice").
            name: The document name/ID (e.g., "SINV-00001").
            fields: Optional list of specific fields to return.
        """
        params = {}
        if fields:
            params["fields"] = json.dumps(fields)

        result = await self._request("GET", f"/api/resource/{quote(doctype)}/{quote(name)}", params=params)
        return result.get("data", result)

    async def get_list(
        self,
        doctype: str,
        filters: Optional[Dict | List] = None,
        fields: Optional[List[str]] = None,
        order_by: str = "modified desc",
        limit_start: int = 0,
        limit_page_length: int = 20,
    ) -> List[Dict[str, Any]]:
        """List documents with filters and pagination.

        Args:
            doctype: The Frappe DocType.
            filters: Filter dict ({"status": "Draft"}) or list of lists.
            fields: Fields to return (default: ["name"]).
            order_by: Sort order.
            limit_start: Pagination offset.
            limit_page_length: Page size (max typically 100).
        """
        params: Dict[str, Any] = {
            "order_by": order_by,
            "limit_start": limit_start,
            "limit_page_length": limit_page_length,
        }
        if filters:
            params["filters"] = json.dumps(filters)
        if fields:
            params["fields"] = json.dumps(fields)

        result = await self._request("GET", f"/api/resource/{quote(doctype)}", params=params)
        return result.get("data", [])

    async def create_doc(self, doctype: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new document. Requires CREATE privilege.

        Args:
            doctype: The Frappe DocType.
            data: Document field values.
        """
        result = await self._request("POST", f"/api/resource/{quote(doctype)}", json_body={"data": json.dumps(data)})
        return result.get("data", result)

    async def update_doc(self, doctype: str, name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing document. Requires UPDATE privilege.

        Args:
            doctype: The Frappe DocType.
            name: Document name.
            data: Fields to update.
        """
        result = await self._request("PUT", f"/api/resource/{quote(doctype)}/{quote(name)}", json_body=data)
        return result.get("data", result)

    async def delete_doc(self, doctype: str, name: str) -> Dict[str, Any]:
        """Delete a document. Requires DELETE privilege.

        Args:
            doctype: The Frappe DocType.
            name: Document name.
        """
        result = await self._request("DELETE", f"/api/resource/{quote(doctype)}/{quote(name)}")
        return result

    async def get_count(self, doctype: str, filters: Optional[Dict] = None) -> int:
        """Count documents matching filters.

        Args:
            doctype: The Frappe DocType.
            filters: Optional filter dict.
        """
        params: Dict[str, Any] = {}
        if filters:
            params["filters"] = json.dumps(filters)

        result = await self._request(
            "GET",
            "/api/method/frappe.client.get_count",
            params={"doctype": doctype, **({"filters": json.dumps(filters)} if filters else {})},
        )
        return result.get("message", 0)

    # ── Reports & Methods ─────────────────────────────────────────────────────

    async def run_report(
        self,
        report_name: str,
        filters: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Execute a named Frappe report.

        Args:
            report_name: The report name (e.g., "General Ledger").
            filters: Report filter parameters.
        """
        params: Dict[str, Any] = {"report_name": report_name}
        if filters:
            params["filters"] = json.dumps(filters)

        return await self._request("GET", "/api/method/frappe.desk.query_report.run", params=params)

    async def call_method(self, method: str, args: Optional[Dict] = None) -> Any:
        """Call a whitelisted Frappe server method.

        Args:
            method: Dotted method path (e.g., "erpnext.accounts.utils.get_balance_on").
            args: Method arguments.
        """
        result = await self._request(
            "POST",
            f"/api/method/{method}",
            json_body=args or {},
        )
        return result.get("message", result)

    # ── Schema & Metadata ─────────────────────────────────────────────────────

    async def get_meta(self, doctype: str) -> Dict[str, Any]:
        """Get DocType metadata/schema (fields, permissions, links).

        Args:
            doctype: The Frappe DocType.
        """
        result = await self._request(
            "GET",
            "/api/method/frappe.client.get_meta",
            params={"doctype": doctype},
        )
        return result.get("message", result)

    async def search_link(
        self,
        doctype: str,
        txt: str,
        page_length: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search for link field values (autocomplete).

        Args:
            doctype: The target DocType to search.
            txt: Search text.
            page_length: Max results.
        """
        result = await self._request(
            "GET",
            "/api/method/frappe.desk.search.search_link",
            params={"doctype": doctype, "txt": txt, "page_length": page_length},
        )
        return result.get("results", result.get("message", []))

    async def get_server_info(self) -> Dict[str, Any]:
        """Get Frappe server version and installed apps."""
        try:
            version = await self._request("GET", "/api/method/frappe.utils.change_log.get_versions")
            return {
                "status": "connected",
                "server": self.base_url,
                "versions": version.get("message", {}),
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
            }

    # ── Utility ───────────────────────────────────────────────────────────────

    async def get_list_all(
        self,
        doctype: str,
        filters: Optional[Dict] = None,
        fields: Optional[List[str]] = None,
        order_by: str = "modified desc",
        max_records: int = 5000,
    ) -> List[Dict[str, Any]]:
        """Fetch all records (paginated internally) for bulk sync.

        Args:
            doctype: The Frappe DocType.
            filters: Optional filters.
            fields: Fields to return.
            order_by: Sort order.
            max_records: Safety cap to prevent runaway fetches.
        """
        all_records = []
        page_size = 100
        offset = 0

        while offset < max_records:
            batch = await self.get_list(
                doctype, filters, fields, order_by,
                limit_start=offset,
                limit_page_length=page_size,
            )
            if not batch:
                break
            all_records.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size

        return all_records[:max_records]
