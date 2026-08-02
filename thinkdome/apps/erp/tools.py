"""ERP MCP Tools registration.

Exposes all ERP bridge, query, explainability, accounting, and reporting tools
to AI agents through ThinkDome's tool registry.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from thinkdome.orchestration.tools import BaseTool, register_tool, get_context
from thinkdome.apps.erp.privileges import require_privilege, get_privilege_summary
from thinkdome.apps.erp.frappe_client import FrappeClient
from thinkdome.apps.erp.query_engine import QueryEngine
from thinkdome.apps.erp.explainability import ExplainabilityEngine
from thinkdome.apps.erp.services.accounting_service import AccountingService
from thinkdome.apps.erp.services.report_engine import ReportEngine
from thinkdome.apps.erp.services.todo_services import (
    HRServiceTodo,
    InventoryServiceTodo,
    CRMServiceTodo,
    ProjectServiceTodo,
    AssetServiceTodo,
)

# ── Lazy Service Providers ──────────────────────────────────────────────────

_frappe_client: Optional[FrappeClient] = None
_query_engine: Optional[QueryEngine] = None
_explainability: Optional[ExplainabilityEngine] = None
_accounting: Optional[AccountingService] = None
_reports: Optional[ReportEngine] = None

# TODO stubs
_hr_todo = HRServiceTodo()
_inventory_todo = InventoryServiceTodo()
_crm_todo = CRMServiceTodo()
_project_todo = ProjectServiceTodo()
_asset_todo = AssetServiceTodo()


def get_frappe_client() -> FrappeClient:
    """Retrieve FrappeClient contextually from active tool context or global fallback."""
    from thinkdome.orchestration.tools import current_tool_context
    ctx = current_tool_context.get()
    if ctx and ctx.get_service("frappe_client"):
        return ctx.get_service("frappe_client")

    global _frappe_client
    if not _frappe_client:
        _frappe_client = FrappeClient.from_config()
    return _frappe_client


def get_query_engine() -> QueryEngine:
    """Retrieve QueryEngine contextually from active tool context or global fallback."""
    from thinkdome.orchestration.tools import current_tool_context
    ctx = current_tool_context.get()
    if ctx and ctx.get_service("query_engine"):
        return ctx.get_service("query_engine")

    global _query_engine
    if not _query_engine:
        _query_engine = QueryEngine(get_frappe_client())
    return _query_engine


def get_explainability() -> ExplainabilityEngine:
    """Retrieve ExplainabilityEngine contextually from active tool context or global fallback."""
    from thinkdome.orchestration.tools import current_tool_context
    ctx = current_tool_context.get()
    if ctx and ctx.get_service("explainability"):
        return ctx.get_service("explainability")

    global _explainability
    if not _explainability:
        _explainability = ExplainabilityEngine(get_accounting_service(), get_report_engine())
    return _explainability


def get_accounting_service() -> AccountingService:
    """Retrieve AccountingService contextually from active tool context or global fallback."""
    from thinkdome.orchestration.tools import current_tool_context
    ctx = current_tool_context.get()
    if ctx and ctx.get_service("accounting_service"):
        return ctx.get_service("accounting_service")

    global _accounting
    if not _accounting:
        _accounting = AccountingService()
    return _accounting


def get_report_engine() -> ReportEngine:
    """Retrieve ReportEngine contextually from active tool context or global fallback."""
    from thinkdome.orchestration.tools import current_tool_context
    ctx = current_tool_context.get()
    if ctx and ctx.get_service("report_engine"):
        return ctx.get_service("report_engine")

    global _reports
    if not _reports:
        _reports = ReportEngine(get_accounting_service())
    return _reports


# ── Pydantic Input Schemas ───────────────────────────────────────────────────

class DoctypeNameInput(BaseModel):
    doctype: str = Field(description="The Frappe DocType name (e.g. 'Sales Invoice')")
    name: str = Field(description="The document ID or name (e.g. 'SINV-0001')")


class DoctypeListInput(BaseModel):
    doctype: str = Field(description="The Frappe DocType name")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Optional filters dictionary")
    fields: Optional[List[str]] = Field(default=None, description="Optional specific fields list to retrieve")
    order_by: str = Field(default="modified desc", description="Sort ordering")
    limit: int = Field(default=100, description="Max rows to return")


class CreateDocInput(BaseModel):
    doctype: str = Field(description="The Frappe DocType name")
    data: Dict[str, Any] = Field(description="The dictionary properties/fields of the new document")


class UpdateDocInput(BaseModel):
    doctype: str = Field(description="The Frappe DocType name")
    name: str = Field(description="The document ID or name")
    data: Dict[str, Any] = Field(description="The properties to update")


class ReportInput(BaseModel):
    report_name: str = Field(description="The remote Frappe report name")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Report filter parameters")


class CallMethodInput(BaseModel):
    method: str = Field(description="Dotted path to whitelisted server method")
    args: Optional[Dict[str, Any]] = Field(default=None, description="Method arguments")


class SearchLinkInput(BaseModel):
    doctype: str = Field(description="Target DocType to search link autocomplete values")
    txt: str = Field(description="Query string")


class RawQueryInput(BaseModel):
    query: str = Field(description="SQL query string (read-only, e.g. SELECT)")
    params: Optional[List[Any]] = Field(default=None, description="Optional query parameters list")


class DescribeDoctypeInput(BaseModel):
    doctype: str = Field(description="DocType name to inspect")


class SyncDataInput(BaseModel):
    doctype: str = Field(description="Frappe DocType name to sync")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Optional filter subset for sync")


class TrendExplainInput(BaseModel):
    metric: str = Field(description="Metric to evaluate (e.g., 'revenue', 'cash', 'ar')")
    period: str = Field(default="monthly", description="Analysis interval ('weekly', 'monthly', 'quarterly')")


class ComparePeriodInput(BaseModel):
    metric: str = Field(description="Metric to compare")
    period1_start: str = Field(description="First period start date (YYYY-MM-DD)")
    period1_end: str = Field(description="First period end date (YYYY-MM-DD)")
    period2_start: str = Field(description="Second period start date (YYYY-MM-DD)")
    period2_end: str = Field(description="Second period end date (YYYY-MM-DD)")


class AskQuestionInput(BaseModel):
    question: str = Field(description="Question in natural language about ERP data")


class DateRangeInput(BaseModel):
    from_date: str = Field(description="Start date (YYYY-MM-DD)")
    to_date: str = Field(description="End date (YYYY-MM-DD)")


class AsOfDateInput(BaseModel):
    as_of_date: str = Field(description="Balance date (YYYY-MM-DD)")


class CreateAccountInput(BaseModel):
    name: str = Field(description="Account name")
    account_type: str = Field(description="Classification type (e.g. Asset, Receivable, Expense, Bank)")
    root_type: str = Field(description="Root node category (Asset, Liability, Equity, Revenue, Expense)")
    parent_account: Optional[str] = Field(default=None, description="Parent account ID")
    currency: str = Field(default="USD")
    is_group: bool = Field(default=False)


class GetBalanceInput(BaseModel):
    account_id: str = Field(description="Account ID")
    as_of_date: Optional[str] = Field(default=None, description="Balance point-in-time date")


class PostJournalInput(BaseModel):
    lines: List[Dict[str, Any]] = Field(description="List of debit/credit structures")
    narration: str = Field(default="", description="NAR explanation tag")
    posting_date: Optional[str] = Field(default=None, description="Date tag")
    entry_type: str = Field(default="Journal Entry")
    reference_type: Optional[str] = Field(default=None)
    reference_id: Optional[str] = Field(default=None)


class ReverseEntryInput(BaseModel):
    entry_id: str = Field(description="Journal Entry ID to reverse")
    narration: Optional[str] = Field(default=None, description="Narration explanation")


class GeneralLedgerInput(BaseModel):
    account_id: str = Field(description="Account ID")
    from_date: Optional[str] = Field(default=None)
    to_date: Optional[str] = Field(default=None)


class TrialBalanceInput(BaseModel):
    fiscal_year_id: str = Field(description="FiscalYear record ID")


class SalesInvoiceInput(BaseModel):
    customer: str = Field(description="Customer name/ID")
    items: List[Dict[str, Any]] = Field(description="List of items (qty, rate, description)")
    tax_rate_id: Optional[str] = Field(default=None, description="TaxRate ID")
    payment_terms: Optional[str] = Field(default=None)
    cost_center: Optional[str] = Field(default=None)


class PurchaseInvoiceInput(BaseModel):
    supplier: str = Field(description="Supplier name/ID")
    items: List[Dict[str, Any]] = Field(description="List of items (qty, rate)")
    tax_rate_id: Optional[str] = Field(default=None, description="TaxRate ID")
    cost_center: Optional[str] = Field(default=None)


class RecordPaymentInput(BaseModel):
    party_type: str = Field(description="Party Type (Customer/Supplier)")
    party: str = Field(description="Party name/ID")
    amount: float = Field(description="Transaction payment amount")
    payment_type: str = Field(description="Type: Receive or Pay")
    bank_account_id: str = Field(description="BankAccount ID")
    reference_type: Optional[str] = Field(default=None)
    reference_id: Optional[str] = Field(default=None)
    mode_of_payment: str = Field(default="Bank")


class ReconcileBankInput(BaseModel):
    bank_account_id: str = Field(description="BankAccount ID")
    statement_balance: float = Field(description="Statement final balance")
    statement_date: str = Field(description="Reconciliation date (YYYY-MM-DD)")


class BudgetInput(BaseModel):
    fiscal_year: str = Field(description="FiscalYear ID")
    department: str = Field(description="Department name")
    allocations: Dict[str, float] = Field(description="Mapping of account IDs to budget allocations")


class RegisterAssetInput(BaseModel):
    name: str = Field(description="The name of the asset")
    category: str = Field(default="Equipment", description="The category of the asset (e.g. Equipment, Vehicle, Land)")
    value: float = Field(description="The purchase/starting value of the asset")
    method: str = Field(default="Straight Line", description="The depreciation method (Straight Line or Declining Balance)")
    life_years: int = Field(default=5, description="The useful life in years")
    cost_center: Optional[str] = Field(default=None, description="Optional Cost Center link")
    asset_account_id: Optional[str] = Field(default=None, description="Optional asset general ledger account ID")
    dep_account_id: Optional[str] = Field(default=None, description="Optional depreciation expense general ledger account ID")


class ComputeDepreciationInput(BaseModel):
    asset_id: str = Field(description="The asset ID to compute and post depreciation for")


class AssetIdInput(BaseModel):
    asset_id: str = Field(description="Asset record ID")


class EmptyInput(BaseModel):
    pass


# ── Domain MCP Tool Implementations ─────────────────────────────────────────

# ── 1. Frappe API Bridge Tools ──

@register_tool
class ErpGetDoc(BaseTool):
    name = "erp_get_doc"
    description = "Fetch a single document from Frappe API"
    required_scope = "erp:read"
    input_schema = DoctypeNameInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        client = get_frappe_client()
        res = await client.get_doc(tool_input["doctype"], tool_input["name"])
        return json.dumps(res, indent=2)


@register_tool
class ErpGetList(BaseTool):
    name = "erp_get_list"
    description = "List and filter records of a DocType via Frappe API"
    required_scope = "erp:read"
    input_schema = DoctypeListInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        client = get_frappe_client()
        res = await client.get_list(
            doctype=tool_input["doctype"],
            filters=tool_input.get("filters"),
            fields=tool_input.get("fields"),
            order_by=tool_input.get("order_by", "modified desc"),
            limit_page_length=tool_input.get("limit", 100)
        )
        return json.dumps(res, indent=2)


@register_tool
class ErpCreateDoc(BaseTool):
    name = "erp_create_doc"
    description = "Create a new document on the Frappe server"
    required_scope = "erp:create"
    input_schema = CreateDocInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        client = get_frappe_client()
        res = await client.create_doc(tool_input["doctype"], tool_input["data"])
        return json.dumps(res, indent=2)


@register_tool
class ErpUpdateDoc(BaseTool):
    name = "erp_update_doc"
    description = "Update an existing document on the Frappe server"
    required_scope = "erp:update"
    input_schema = UpdateDocInput

    @require_privilege("update")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        client = get_frappe_client()
        res = await client.update_doc(tool_input["doctype"], tool_input["name"], tool_input["data"])
        return json.dumps(res, indent=2)


@register_tool
class ErpDeleteDoc(BaseTool):
    name = "erp_delete_doc"
    description = "Delete a document on the Frappe server"
    required_scope = "erp:delete"
    input_schema = DoctypeNameInput

    @require_privilege("delete")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        client = get_frappe_client()
        res = await client.delete_doc(tool_input["doctype"], tool_input["name"])
        return json.dumps(res, indent=2)


@register_tool
class ErpGetDoctypeMeta(BaseTool):
    name = "erp_get_doctype_meta"
    description = "Fetch DocType metadata schemas and configurations"
    required_scope = "erp:read"
    input_schema = DescribeDoctypeInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        client = get_frappe_client()
        res = await client.get_meta(tool_input["doctype"])
        return json.dumps(res, indent=2)


@register_tool
class ErpRunReport(BaseTool):
    name = "erp_run_report"
    description = "Run a standard report configured on the remote Frappe instance"
    required_scope = "erp:read"
    input_schema = ReportInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        client = get_frappe_client()
        res = await client.run_report(tool_input["report_name"], tool_input.get("filters"))
        return json.dumps(res, indent=2)


@register_tool
class ErpCallMethod(BaseTool):
    name = "erp_call_method"
    description = "Call a whitelisted Frappe API endpoint method"
    required_scope = "erp:create"
    input_schema = CallMethodInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        client = get_frappe_client()
        res = await client.call_method(tool_input["method"], tool_input.get("args"))
        return json.dumps(res, indent=2)


@register_tool
class ErpSearch(BaseTool):
    name = "erp_search"
    description = "Search linked DocType auto-completions"
    required_scope = "erp:read"
    input_schema = SearchLinkInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        client = get_frappe_client()
        res = await client.search_link(tool_input["doctype"], tool_input["txt"])
        return json.dumps(res, indent=2)


@register_tool
class ErpGetCount(BaseTool):
    name = "erp_get_count"
    description = "Count document listings matches"
    required_scope = "erp:read"
    input_schema = DoctypeListInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        client = get_frappe_client()
        res = await client.get_count(tool_input["doctype"], tool_input.get("filters"))
        return json.dumps({"count": res})


# ── 2. Query & Exploration Tools ──

@register_tool
class ErpQueryLocal(BaseTool):
    name = "erp_query_local"
    description = "Execute raw SELECT SQL query against local cached databases"
    required_scope = "erp:read"
    input_schema = RawQueryInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_query_engine()
        params = tuple(tool_input.get("params") or [])
        res = engine.execute_local_sql(tool_input["query"], params)
        return json.dumps(res, indent=2)


@register_tool
class ErpQueryFrappe(BaseTool):
    name = "erp_query_frappe"
    description = "Run API-level query logic against Frappe doctypes"
    required_scope = "erp:read"
    input_schema = DoctypeListInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_query_engine()
        res = await engine.execute_frappe_query(
            doctype=tool_input["doctype"],
            filters=tool_input.get("filters"),
            fields=tool_input.get("fields"),
            order_by=tool_input.get("order_by", "modified desc"),
            limit=tool_input.get("limit", 100)
        )
        return json.dumps(res, indent=2)


@register_tool
class ErpDescribeDoctype(BaseTool):
    name = "erp_describe_doctype"
    description = "Inspect field layouts and data structures of a DocType"
    required_scope = "erp:read"
    input_schema = DescribeDoctypeInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_query_engine()
        res = await engine.get_doctype_schema(tool_input["doctype"])
        return json.dumps(res, indent=2)


@register_tool
class ErpListDoctypes(BaseTool):
    name = "erp_list_doctypes"
    description = "List all registered tables and doctypes from Frappe"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_query_engine()
        res = await engine.list_doctypes()
        return json.dumps(res, indent=2)


@register_tool
class ErpSyncData(BaseTool):
    name = "erp_sync_data"
    description = "Sync Frappe tables data into local caching ORM"
    required_scope = "erp:create"
    input_schema = SyncDataInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_query_engine()
        res = await engine.sync_data_to_local(tool_input["doctype"], tool_input.get("filters"))
        return json.dumps(res, indent=2)


@register_tool
class ErpGetServerInfo(BaseTool):
    name = "erp_get_server_info"
    description = "Obtain target ERPNext server information and application versions"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        client = get_frappe_client()
        res = await client.get_server_info()
        return json.dumps(res, indent=2)


# ── 3. Data Explainability Tools ──

@register_tool
class ErpExplainForCeo(BaseTool):
    name = "erp_explain_for_ceo"
    description = "Generate the CEO-level real-time executive dashboard narrative briefing"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_explainability()
        return engine.explain_for_ceo()


@register_tool
class ErpExplainFinancialHealth(BaseTool):
    name = "erp_explain_financial_health"
    description = "Explain company health classifications and risk factors in clear language"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_explainability()
        return engine.explain_financial_health()


@register_tool
class ErpExplainTrend(BaseTool):
    name = "erp_explain_trend"
    description = "Explain trajectories and trend vectors of cash, revenues, or accounts"
    required_scope = "erp:read"
    input_schema = TrendExplainInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_explainability()
        return engine.explain_trend(tool_input["metric"], tool_input.get("period", "monthly"))


@register_tool
class ErpExplainAnomalies(BaseTool):
    name = "erp_explain_anomalies"
    description = "Locate and explain budget mismatches or liquidity anomalies"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_explainability()
        return engine.explain_anomalies()


@register_tool
class ErpAnswerQuestion(BaseTool):
    name = "erp_answer_question"
    description = "Heuristically answer natural language questions about corporate financial data"
    required_scope = "erp:read"
    input_schema = AskQuestionInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_explainability()
        return engine.answer_question(tool_input["question"])


@register_tool
class ErpPrivilegeSummary(BaseTool):
    name = "erp_privilege_summary"
    description = "Get summary of permissions required for read/write database actions"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        return json.dumps(get_privilege_summary(), indent=2)


# ── 4. Accounting Tools ──

@register_tool
class ErpChartOfAccounts(BaseTool):
    name = "erp_chart_of_accounts"
    description = "Fetch Chart of Accounts structure hierarchy"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.get_chart_of_accounts()
        return json.dumps(res, indent=2)


@register_tool
class ErpCreateAccount(BaseTool):
    name = "erp_create_account"
    description = "Insert a new account into the Chart of Accounts"
    required_scope = "erp:create"
    input_schema = CreateAccountInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.create_account(
            name=tool_input["name"],
            account_type=tool_input["account_type"],
            root_type=tool_input["root_type"],
            parent_account=tool_input.get("parent_account"),
            currency=tool_input.get("currency", "USD"),
            is_group=tool_input.get("is_group", False)
        )
        return json.dumps(res, indent=2)


@register_tool
class ErpAccountBalance(BaseTool):
    name = "erp_account_balance"
    description = "Fetch account balance point-in-time"
    required_scope = "erp:read"
    input_schema = GetBalanceInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.get_account_balance(tool_input["account_id"], tool_input.get("as_of_date"))
        return json.dumps({"balance": res})


@register_tool
class ErpPostJournalEntry(BaseTool):
    name = "erp_post_journal_entry"
    description = "Post double-entry debit/credit ledger transactions"
    required_scope = "erp:create"
    input_schema = PostJournalInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.post_journal_entry(
            lines=tool_input["lines"],
            narration=tool_input.get("narration", ""),
            posting_date=tool_input.get("posting_date"),
            entry_type=tool_input.get("entry_type", "Journal Entry"),
            reference_type=tool_input.get("reference_type"),
            reference_id=tool_input.get("reference_id")
        )
        return json.dumps(res, indent=2)


@register_tool
class ErpReverseEntry(BaseTool):
    name = "erp_reverse_entry"
    description = "Reverse posted journal transactions"
    required_scope = "erp:create"
    input_schema = ReverseEntryInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.reverse_journal_entry(tool_input["entry_id"], tool_input.get("narration", ""))
        return json.dumps(res, indent=2)


@register_tool
class ErpGeneralLedger(BaseTool):
    name = "erp_general_ledger"
    description = "Retrieve General Ledger running transactions list for an account"
    required_scope = "erp:read"
    input_schema = GeneralLedgerInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.get_general_ledger(
            tool_input["account_id"],
            tool_input.get("from_date"),
            tool_input.get("to_date")
        )
        return json.dumps(res, indent=2)


@register_tool
class ErpTrialBalance(BaseTool):
    name = "erp_trial_balance"
    description = "Fetch debit and credit trial balance calculations"
    required_scope = "erp:read"
    input_schema = TrialBalanceInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.get_trial_balance(tool_input["fiscal_year_id"])
        return json.dumps(res, indent=2)


@register_tool
class ErpCreateSalesInvoice(BaseTool):
    name = "erp_create_sales_invoice"
    description = "Create and post client billing sales invoice"
    required_scope = "erp:create"
    input_schema = SalesInvoiceInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.create_sales_invoice(
            customer=tool_input["customer"],
            items=tool_input["items"],
            tax_rate_id=tool_input.get("tax_rate_id"),
            payment_terms=tool_input.get("payment_terms"),
            cost_center=tool_input.get("cost_center")
        )
        return json.dumps(res, indent=2)


@register_tool
class ErpCreatePurchaseInvoice(BaseTool):
    name = "erp_create_purchase_invoice"
    description = "Create and post supplier purchase procurement invoice"
    required_scope = "erp:create"
    input_schema = PurchaseInvoiceInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.create_purchase_invoice(
            supplier=tool_input["supplier"],
            items=tool_input["items"],
            tax_rate_id=tool_input.get("tax_rate_id"),
            cost_center=tool_input.get("cost_center")
        )
        return json.dumps(res, indent=2)


@register_tool
class ErpRecordPayment(BaseTool):
    name = "erp_record_payment"
    description = "Record customer payment receipts or vendor disbursements"
    required_scope = "erp:create"
    input_schema = RecordPaymentInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.record_payment(
            party_type=tool_input["party_type"],
            party=tool_input["party"],
            amount=tool_input["amount"],
            payment_type=tool_input["payment_type"],
            bank_account_id=tool_input["bank_account_id"],
            reference_type=tool_input.get("reference_type"),
            reference_id=tool_input.get("reference_id"),
            mode_of_payment=tool_input.get("mode_of_payment", "Bank")
        )
        return json.dumps(res, indent=2)


@register_tool
class ErpAccountsReceivable(BaseTool):
    name = "erp_accounts_receivable"
    description = "List all customer accounts outstanding invoicing balances"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.get_accounts_receivable()
        return json.dumps(res, indent=2)


@register_tool
class ErpAccountsPayable(BaseTool):
    name = "erp_accounts_payable"
    description = "List all supplier accounts outstanding obligations"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.get_accounts_payable()
        return json.dumps(res, indent=2)


@register_tool
class ErpReconcileBank(BaseTool):
    name = "erp_reconcile_bank"
    description = "Verify statement balance matching bank ledger"
    required_scope = "erp:create"
    input_schema = ReconcileBankInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.reconcile_bank(
            bank_account_id=tool_input["bank_account_id"],
            statement_balance=tool_input["statement_balance"],
            statement_date=tool_input["statement_date"]
        )
        return json.dumps(res, indent=2)


@register_tool
class ErpCreateBudget(BaseTool):
    name = "erp_create_budget"
    description = "Establish budget limits for fiscal periods"
    required_scope = "erp:create"
    input_schema = BudgetInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.create_budget(
            fiscal_year=tool_input["fiscal_year"],
            department=tool_input["department"],
            allocations=tool_input["allocations"]
        )
        return json.dumps(res, indent=2)


# ── 5. Reports & Decision Support Tools ──

@register_tool
class ErpProfitAndLoss(BaseTool):
    name = "erp_profit_and_loss"
    description = "Generate Income Statement (Profit and Loss report)"
    required_scope = "erp:read"
    input_schema = DateRangeInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_report_engine()
        res = engine.profit_and_loss(tool_input["from_date"], tool_input["to_date"])
        return json.dumps(res, indent=2)


@register_tool
class ErpBalanceSheet(BaseTool):
    name = "erp_balance_sheet"
    description = "Generate Balance Sheet report (Assets vs Liabilities/Equity)"
    required_scope = "erp:read"
    input_schema = AsOfDateInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_report_engine()
        res = engine.balance_sheet(tool_input["as_of_date"])
        return json.dumps(res, indent=2)


@register_tool
class ErpCashFlowStatement(BaseTool):
    name = "erp_cash_flow_statement"
    description = "Generate Cash Flow statement report"
    required_scope = "erp:read"
    input_schema = DateRangeInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_report_engine()
        res = engine.cash_flow_statement(tool_input["from_date"], tool_input["to_date"])
        return json.dumps(res, indent=2)


@register_tool
class ErpFinancialRatios(BaseTool):
    name = "erp_financial_ratios"
    description = "Calculate liquidity and solvency financial ratios"
    required_scope = "erp:read"
    input_schema = AsOfDateInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_report_engine()
        res = engine.get_financial_ratios(tool_input["as_of_date"])
        return json.dumps(res, indent=2)


@register_tool
class ErpExecutiveDashboard(BaseTool):
    name = "erp_executive_dashboard"
    description = "Generate dashboard performance indicators metrics list"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_report_engine()
        res = engine.executive_dashboard()
        return json.dumps(res, indent=2)


@register_tool
class ErpCompanyHealthScore(BaseTool):
    name = "erp_company_health_score"
    description = "Generate dynamic weighted overall health index"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        engine = get_report_engine()
        res = engine.company_health_score()
        return json.dumps(res, indent=2)


# ── 6. Stub/Todo Tools (HR, Inventory, CRM, Projects, Assets) ──

@register_tool
class ErpHrCreateEmployee(BaseTool):
    name = "erp_hr_create_employee"
    description = "Onboard a new employee (HR Stub)"
    required_scope = "erp:create"
    input_schema = CreateDocInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        return json.dumps(_hr_todo.create_employee(tool_input))


@register_tool
class ErpInventoryCreateItem(BaseTool):
    name = "erp_inventory_create_item"
    description = "Register a new inventory item (Inventory Stub)"
    required_scope = "erp:create"
    input_schema = CreateDocInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        return json.dumps(_inventory_todo.create_item(tool_input))


@register_tool
class ErpCrmCreateLead(BaseTool):
    name = "erp_crm_create_lead"
    description = "Capture a new CRM sales lead (CRM Stub)"
    required_scope = "erp:create"
    input_schema = CreateDocInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        return json.dumps(_crm_todo.create_lead(tool_input))


@register_tool
class ErpProjectsCreateProject(BaseTool):
    name = "erp_projects_create_project"
    description = "Create a new project tracking file (Projects Stub)"
    required_scope = "erp:create"
    input_schema = CreateDocInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        return json.dumps(_project_todo.create_project(tool_input))


@register_tool
class ErpAssetsRegisterAsset(BaseTool):
    name = "erp_assets_register_asset"
    description = "Register a capital fixed asset and post its purchase to the general ledger"
    required_scope = "erp:create"
    input_schema = RegisterAssetInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.register_asset(
            name=tool_input["name"],
            category=tool_input.get("category", "Equipment"),
            value=tool_input["value"],
            method=tool_input.get("method", "Straight Line"),
            life_years=tool_input.get("life_years", 5),
            cost_center=tool_input.get("cost_center"),
            asset_account_id=tool_input.get("asset_account_id"),
            dep_account_id=tool_input.get("dep_account_id")
        )
        return json.dumps(res, indent=2)


@register_tool
class ErpAssetsComputeDepreciation(BaseTool):
    name = "erp_assets_compute_depreciation"
    description = "Compute and post depreciation expense for a fixed asset to the general ledger"
    required_scope = "erp:create"
    input_schema = ComputeDepreciationInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.compute_depreciation(tool_input["asset_id"])
        return json.dumps(res, indent=2)


@register_tool
class ErpAssetsGetAssetRegister(BaseTool):
    name = "erp_assets_get_asset_register"
    description = "Retrieve list of all registered fixed capital assets"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.get_asset_register()
        return json.dumps(res, indent=2)


@register_tool
class ErpAssetsGetDepreciationSchedule(BaseTool):
    name = "erp_assets_get_depreciation_schedule"
    description = "Retrieve list of all depreciation entries posted for a fixed asset"
    required_scope = "erp:read"
    input_schema = AssetIdInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.get_depreciation_schedule(tool_input["asset_id"])
        return json.dumps(res, indent=2)


# ── 7. Credit Notes & Debit Notes ──

class CreditNoteInput(BaseModel):
    customer: str = Field(description="Customer name/ID")
    original_invoice_id: str = Field(description="Original Sales Invoice ID being returned against")
    items: List[Dict[str, Any]] = Field(description="List of returned items (qty, rate)")
    reason: str = Field(default="Goods returned", description="Reason for credit note")
    tax_rate_id: Optional[str] = Field(default=None)


class DebitNoteInput(BaseModel):
    supplier: str = Field(description="Supplier name/ID")
    original_invoice_id: str = Field(description="Original Purchase Invoice ID")
    items: List[Dict[str, Any]] = Field(description="List of returned items (qty, rate)")
    reason: str = Field(default="Goods returned to supplier")
    tax_rate_id: Optional[str] = Field(default=None)


@register_tool
class ErpCreateCreditNote(BaseTool):
    name = "erp_create_credit_note"
    description = "Issue a credit note (sales return) reversing a sales invoice with GL postings"
    required_scope = "erp:create"
    input_schema = CreditNoteInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.create_credit_note(
            customer=tool_input["customer"],
            original_invoice_id=tool_input["original_invoice_id"],
            items=tool_input["items"],
            reason=tool_input.get("reason", "Goods returned"),
            tax_rate_id=tool_input.get("tax_rate_id")
        )
        return json.dumps(res, indent=2)


@register_tool
class ErpCreateDebitNote(BaseTool):
    name = "erp_create_debit_note"
    description = "Issue a debit note (purchase return) reversing a purchase invoice with GL postings"
    required_scope = "erp:create"
    input_schema = DebitNoteInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        res = service.create_debit_note(
            supplier=tool_input["supplier"],
            original_invoice_id=tool_input["original_invoice_id"],
            items=tool_input["items"],
            reason=tool_input.get("reason", "Goods returned to supplier"),
            tax_rate_id=tool_input.get("tax_rate_id")
        )
        return json.dumps(res, indent=2)


# ── 8. AR/AP Aging ──

@register_tool
class ErpArAging(BaseTool):
    name = "erp_ar_aging"
    description = "Generate Accounts Receivable aging report in 30/60/90/120+ day buckets"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_ar_aging(), indent=2)


@register_tool
class ErpApAging(BaseTool):
    name = "erp_ap_aging"
    description = "Generate Accounts Payable aging report in 30/60/90/120+ day buckets"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_ap_aging(), indent=2)


# ── 9. Customer & Supplier Ledgers ──

class PartyInput(BaseModel):
    party: str = Field(description="Customer or Supplier name/ID")


@register_tool
class ErpCustomerLedger(BaseTool):
    name = "erp_customer_ledger"
    description = "Full transaction history, invoices, payments, and returns for a customer"
    required_scope = "erp:read"
    input_schema = PartyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_customer_ledger(tool_input["party"]), indent=2)


@register_tool
class ErpSupplierLedger(BaseTool):
    name = "erp_supplier_ledger"
    description = "Full transaction history, invoices, payments, and returns for a supplier"
    required_scope = "erp:read"
    input_schema = PartyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_supplier_ledger(tool_input["party"]), indent=2)


@register_tool
class ErpCustomerBalanceSummary(BaseTool):
    name = "erp_customer_balance_summary"
    description = "Summarized outstanding balance for all customers"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_customer_balance_summary(), indent=2)


@register_tool
class ErpSupplierBalanceSummary(BaseTool):
    name = "erp_supplier_balance_summary"
    description = "Summarized outstanding balance for all suppliers"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_supplier_balance_summary(), indent=2)


# ── 10. Multi-Currency & Exchange Rates ──

class SetExchangeRateInput(BaseModel):
    from_currency: str = Field(description="Source currency code (e.g. USD)")
    to_currency: str = Field(description="Target currency code (e.g. EUR)")
    rate: float = Field(description="Exchange rate (1 unit of source = rate units of target)")
    effective_date: Optional[str] = Field(default=None, description="Date the rate takes effect")


class ConvertCurrencyInput(BaseModel):
    amount: float = Field(description="Amount to convert")
    from_currency: str = Field(description="Source currency code")
    to_currency: str = Field(description="Target currency code")


@register_tool
class ErpSetExchangeRate(BaseTool):
    name = "erp_set_exchange_rate"
    description = "Record a currency exchange rate for multi-currency operations"
    required_scope = "erp:create"
    input_schema = SetExchangeRateInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.set_exchange_rate(
            tool_input["from_currency"], tool_input["to_currency"],
            tool_input["rate"], tool_input.get("effective_date")
        ), indent=2)


@register_tool
class ErpConvertCurrency(BaseTool):
    name = "erp_convert_currency"
    description = "Convert an amount between currencies using stored exchange rates"
    required_scope = "erp:read"
    input_schema = ConvertCurrencyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.convert_currency(
            tool_input["amount"], tool_input["from_currency"], tool_input["to_currency"]
        ), indent=2)


@register_tool
class ErpGetExchangeRates(BaseTool):
    name = "erp_get_exchange_rates"
    description = "List all stored exchange rates"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_exchange_rates(), indent=2)


# ── 11. Cheque Management ──

class IssueChequeInput(BaseModel):
    party_type: str = Field(description="Party type (Customer/Supplier/Employee)")
    party: str = Field(description="Party name")
    amount: float = Field(description="Cheque amount")
    bank_account_id: str = Field(description="BankAccount ID")
    cheque_number: str = Field(description="Cheque number")
    cheque_date: Optional[str] = Field(default=None)
    direction: str = Field(default="Outgoing", description="Outgoing or Incoming")


class ChequeIdInput(BaseModel):
    cheque_id: str = Field(description="ChequeEntry ID")


@register_tool
class ErpIssueCheque(BaseTool):
    name = "erp_issue_cheque"
    description = "Issue a new cheque for payment or receipt"
    required_scope = "erp:create"
    input_schema = IssueChequeInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.issue_cheque(**tool_input), indent=2)


@register_tool
class ErpClearCheque(BaseTool):
    name = "erp_clear_cheque"
    description = "Mark a cheque as cleared and update bank balances"
    required_scope = "erp:create"
    input_schema = ChequeIdInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.clear_cheque(tool_input["cheque_id"]), indent=2)


@register_tool
class ErpBounceCheque(BaseTool):
    name = "erp_bounce_cheque"
    description = "Mark a cheque as bounced and reverse bank impact"
    required_scope = "erp:create"
    input_schema = ChequeIdInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.bounce_cheque(tool_input["cheque_id"]), indent=2)


@register_tool
class ErpChequeRegister(BaseTool):
    name = "erp_cheque_register"
    description = "List all cheques with lifecycle status"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_cheque_register(), indent=2)


@register_tool
class ErpBankClearanceStatus(BaseTool):
    name = "erp_bank_clearance_status"
    description = "List uncleared cheques pending bank clearance"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_bank_clearance_status(), indent=2)


# ── 12. Subscriptions ──

class CreateSubscriptionInput(BaseModel):
    customer: str = Field(description="Customer name/ID")
    plan_name: str = Field(description="Subscription plan name")
    amount: float = Field(description="Billing amount per cycle")
    frequency: str = Field(default="Monthly", description="Monthly/Quarterly/Semi-Annual/Annual")
    start_date: Optional[str] = Field(default=None)


class SubscriptionIdInput(BaseModel):
    subscription_id: str = Field(description="Subscription ID")


@register_tool
class ErpCreateSubscription(BaseTool):
    name = "erp_create_subscription"
    description = "Create a recurring billing subscription for a customer"
    required_scope = "erp:create"
    input_schema = CreateSubscriptionInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.create_subscription(
            customer=tool_input["customer"], plan_name=tool_input["plan_name"],
            amount=tool_input["amount"], frequency=tool_input.get("frequency", "Monthly"),
            start_date=tool_input.get("start_date")
        ), indent=2)


@register_tool
class ErpProcessSubscriptions(BaseTool):
    name = "erp_process_subscriptions"
    description = "Process all due subscriptions and auto-generate invoices"
    required_scope = "erp:create"
    input_schema = EmptyInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.process_subscriptions(), indent=2)


@register_tool
class ErpCancelSubscription(BaseTool):
    name = "erp_cancel_subscription"
    description = "Cancel an active subscription"
    required_scope = "erp:update"
    input_schema = SubscriptionIdInput

    @require_privilege("update")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.cancel_subscription(tool_input["subscription_id"]), indent=2)


# ── 13. Recurring Entries ──

class CreateRecurringEntryInput(BaseModel):
    narration: str = Field(description="Description of the recurring entry")
    lines: List[Dict[str, Any]] = Field(description="Journal entry lines template")
    frequency: str = Field(default="Monthly")
    start_date: Optional[str] = Field(default=None)


@register_tool
class ErpCreateRecurringEntry(BaseTool):
    name = "erp_create_recurring_entry"
    description = "Create auto-repeat journal entry template (rent, salaries, etc.)"
    required_scope = "erp:create"
    input_schema = CreateRecurringEntryInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.create_recurring_entry(
            narration=tool_input["narration"], lines=tool_input["lines"],
            frequency=tool_input.get("frequency", "Monthly"),
            start_date=tool_input.get("start_date")
        ), indent=2)


@register_tool
class ErpProcessRecurringEntries(BaseTool):
    name = "erp_process_recurring_entries"
    description = "Post all pending recurring journal entries that are due"
    required_scope = "erp:create"
    input_schema = EmptyInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.process_recurring_entries(), indent=2)


# ── 14. Credit Limits & Dunning ──

class SetCreditLimitInput(BaseModel):
    customer: str = Field(description="Customer name/ID")
    limit: float = Field(description="Credit ceiling amount")
    bypass: bool = Field(default=False, description="Allow bypass of credit limit")


class CheckCreditLimitInput(BaseModel):
    customer: str = Field(description="Customer name/ID")
    new_amount: float = Field(description="Amount of proposed new transaction")


@register_tool
class ErpSetCreditLimit(BaseTool):
    name = "erp_set_credit_limit"
    description = "Set or update a customer's maximum credit exposure ceiling"
    required_scope = "erp:create"
    input_schema = SetCreditLimitInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.set_credit_limit(
            tool_input["customer"], tool_input["limit"], tool_input.get("bypass", False)
        ), indent=2)


@register_tool
class ErpCheckCreditLimit(BaseTool):
    name = "erp_check_credit_limit"
    description = "Check if a new transaction will exceed a customer's credit limit"
    required_scope = "erp:read"
    input_schema = CheckCreditLimitInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.check_credit_limit(
            tool_input["customer"], tool_input["new_amount"]
        ), indent=2)


@register_tool
class ErpGenerateDunning(BaseTool):
    name = "erp_generate_dunning"
    description = "Generate payment reminder notices for overdue customer invoices"
    required_scope = "erp:create"
    input_schema = EmptyInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.generate_dunning(), indent=2)


# ── 15. Bad Debt Write-Off ──

class WriteOffInput(BaseModel):
    invoice_id: str = Field(description="Sales Invoice ID to write off")
    amount: Optional[float] = Field(default=None, description="Amount to write off (defaults to full outstanding)")


@register_tool
class ErpWriteOffBadDebt(BaseTool):
    name = "erp_write_off_bad_debt"
    description = "Write off uncollectible customer debt with GL postings"
    required_scope = "erp:create"
    input_schema = WriteOffInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.write_off_bad_debt(
            tool_input["invoice_id"], tool_input.get("amount")
        ), indent=2)


# ── 16. Period Closing ──

class ClosePeriodInput(BaseModel):
    fiscal_year_id: str = Field(description="FiscalYear ID to close")


class OpeningBalancesInput(BaseModel):
    entries: List[Dict[str, Any]] = Field(description="List of account/debit/credit opening entries")


@register_tool
class ErpCloseFiscalPeriod(BaseTool):
    name = "erp_close_fiscal_period"
    description = "Close a fiscal year by transferring P&L to Retained Earnings with GL postings"
    required_scope = "erp:create"
    input_schema = ClosePeriodInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.close_fiscal_period(tool_input["fiscal_year_id"]), indent=2)


@register_tool
class ErpSetOpeningBalances(BaseTool):
    name = "erp_set_opening_balances"
    description = "Set opening balances for accounts at the start of a new fiscal period"
    required_scope = "erp:create"
    input_schema = OpeningBalancesInput

    @require_privilege("create")
    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.set_opening_balances(tool_input["entries"]), indent=2)


# ── 17. Tax Summaries ──

@register_tool
class ErpTaxSummary(BaseTool):
    name = "erp_tax_summary"
    description = "Generate tax return summary (output VAT collected vs input VAT paid)"
    required_scope = "erp:read"
    input_schema = DateRangeInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_tax_summary(
            tool_input["from_date"], tool_input["to_date"]
        ), indent=2)


# ── 18. Cost Center Profitability ──

class CostCenterInput(BaseModel):
    cost_center_id: Optional[str] = Field(default=None, description="Cost Center ID (leave blank for all)")


@register_tool
class ErpCostCenterProfitability(BaseTool):
    name = "erp_cost_center_profitability"
    description = "Calculate revenue and expense allocation per cost center"
    required_scope = "erp:read"
    input_schema = CostCenterInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_cost_center_profitability(
            tool_input.get("cost_center_id")
        ), indent=2)


@register_tool
class ErpGrossProfitByCustomer(BaseTool):
    name = "erp_gross_profit_by_customer"
    description = "Calculate gross profit breakdown by customer"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_gross_profit_by_customer(), indent=2)


# ── 19. Cash Flow Forecasting ──

class ForecastInput(BaseModel):
    days_ahead: int = Field(default=90, description="Number of days to forecast ahead")


@register_tool
class ErpForecastCashFlow(BaseTool):
    name = "erp_forecast_cash_flow"
    description = "Project future cash position based on AR, AP, subscriptions, and recurring costs"
    required_scope = "erp:read"
    input_schema = ForecastInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.forecast_cash_flow(
            tool_input.get("days_ahead", 90)
        ), indent=2)


# ── 20. Audit Trail & GL Integrity ──

class AuditTrailInput(BaseModel):
    entity_type: Optional[str] = Field(default=None, description="Entity type filter (e.g. JournalEntry)")
    entity_id: Optional[str] = Field(default=None, description="Specific entity ID")


@register_tool
class ErpAuditTrail(BaseTool):
    name = "erp_audit_trail"
    description = "Retrieve the immutable audit log for financial transactions"
    required_scope = "erp:read"
    input_schema = AuditTrailInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.get_audit_trail(
            tool_input.get("entity_type"), tool_input.get("entity_id")
        ), indent=2)


@register_tool
class ErpVerifyGlIntegrity(BaseTool):
    name = "erp_verify_gl_integrity"
    description = "Verify the general ledger is balanced (total debits == total credits)"
    required_scope = "erp:read"
    input_schema = EmptyInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        service = get_accounting_service()
        return json.dumps(service.verify_gl_integrity(), indent=2)


import thinkdome.apps.erp.audit.tools


