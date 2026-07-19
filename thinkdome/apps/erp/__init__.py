"""ThinkDome ERP Module — Enterprise Resource Planning via MCP.

Full Frappe/ERPNext bridge with deep accounting expertise,
data explainability, query engine, and privilege-controlled CRUD.
All capabilities exposed as MCP-callable tools for AI-driven decision support.
"""

from __future__ import annotations

# Import models to trigger ORM metaclass table registration
import thinkdome.apps.erp.models  # noqa: F401
