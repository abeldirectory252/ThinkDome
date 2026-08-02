"""Master registration for all ERPNext Audit tools.

Exposes every professional audit capability to the ThinkDome tool registry.
"""

from __future__ import annotations

from typing import Any, Dict

from thinkdome.orchestration.tools import registry
from thinkdome.apps.erp.audit.types import *
from thinkdome.apps.erp.audit import company
from thinkdome.apps.erp.audit import financial
from thinkdome.apps.erp.audit import ledger
from thinkdome.apps.erp.audit import journal
from thinkdome.apps.erp.audit import sales
from thinkdome.apps.erp.audit import purchase
from thinkdome.apps.erp.audit import inventory
from thinkdome.apps.erp.audit import banking
from thinkdome.apps.erp.audit import assets
from thinkdome.apps.erp.audit import users
from thinkdome.apps.erp.audit import permissions
from thinkdome.apps.erp.audit import workflow
from thinkdome.apps.erp.audit import audittrail
from thinkdome.apps.erp.audit import fraud
from thinkdome.apps.erp.audit import controls
from thinkdome.apps.erp.audit import sampling
from thinkdome.apps.erp.audit import investigation
from thinkdome.apps.erp.audit import evidence
from thinkdome.apps.erp.audit import reporting

# Define the mapping of tools and their specifications
AUDIT_TOOLS_SPEC = [
    # ── Company Information ──
    {
        "name": "audit.get_company",
        "description": "Fetch company information, fiscal year settings, and basic configuration.",
        "func": company.get_company,
        "input_schema": CompanyInput,
    },
    {
        "name": "audit.get_chart_of_accounts",
        "description": "Fetch the full Chart of Accounts hierarchy with account types and classifications.",
        "func": company.get_chart_of_accounts,
        "input_schema": CompanyInput,
    },
    {
        "name": "audit.get_accounting_periods",
        "description": "Fetch fiscal years and accounting period closing status.",
        "func": company.get_accounting_periods,
        "input_schema": CompanyInput,
    },
    # ── Financial Statements ──
    {
        "name": "audit.get_trial_balance",
        "description": "Fetch trial balance for the specified period with balance verification.",
        "func": financial.get_trial_balance,
        "input_schema": DateRangeInput,
    },
    {
        "name": "audit.get_balance_sheet",
        "description": "Fetch balance sheet as of a specific date.",
        "func": financial.get_balance_sheet,
        "input_schema": DateRangeInput,
    },
    {
        "name": "audit.get_profit_loss",
        "description": "Fetch profit and loss statement for a period.",
        "func": financial.get_profit_loss,
        "input_schema": DateRangeInput,
    },
    {
        "name": "audit.get_cash_flow",
        "description": "Fetch cash flow statement for a period.",
        "func": financial.get_cash_flow,
        "input_schema": DateRangeInput,
    },
    {
        "name": "audit.compare_financial_periods",
        "description": "Compare two financial periods and flag material variances.",
        "func": financial.compare_financial_periods,
        "input_schema": PeriodCompareInput,
    },
    # ── General Ledger ──
    {
        "name": "audit.search_general_ledger",
        "description": "Search the general ledger with flexible filters.",
        "func": ledger.search_general_ledger,
        "input_schema": LedgerSearchInput,
    },
    {
        "name": "audit.find_large_transactions",
        "description": "Find transactions exceeding the materiality threshold.",
        "func": ledger.find_large_transactions,
        "input_schema": ThresholdInput,
    },
    {
        "name": "audit.find_manual_journals",
        "description": "Find manually created journal entries.",
        "func": ledger.find_manual_journals,
        "input_schema": DocumentListInput,
    },
    {
        "name": "audit.find_backdated_entries",
        "description": "Find entries where posting_date is significantly before creation date.",
        "func": ledger.find_backdated_entries,
        "input_schema": DocumentListInput,
    },
    {
        "name": "audit.find_year_end_entries",
        "description": "Find entries posted in the last N days of a fiscal year.",
        "func": ledger.find_year_end_entries,
        "input_schema": DocumentListInput,
    },
    {
        "name": "audit.find_round_number_entries",
        "description": "Find entries with suspiciously round amounts.",
        "func": ledger.find_round_number_entries,
        "input_schema": ThresholdInput,
    },
    {
        "name": "audit.find_weekend_postings",
        "description": "Find entries posted on weekends or outside business hours.",
        "func": ledger.find_weekend_postings,
        "input_schema": DocumentListInput,
    },
    # ── Journal Entry ──
    {
        "name": "audit.get_journal_entry",
        "description": "Fetch full journal entry with lines, attachments, and linked documents.",
        "func": journal.get_journal_entry,
        "input_schema": DocumentInput,
    },
    {
        "name": "audit.get_journal_history",
        "description": "Fetch version history and all modifications for a journal entry.",
        "func": journal.get_journal_history,
        "input_schema": DocumentInput,
    },
    {
        "name": "audit.get_journal_creator",
        "description": "Identify who created a journal entry, when, and with what role.",
        "func": journal.get_journal_creator,
        "input_schema": DocumentInput,
    },
    {
        "name": "audit.get_journal_approvals",
        "description": "Fetch the approval workflow trail for a journal entry.",
        "func": journal.get_journal_approvals,
        "input_schema": DocumentInput,
    },
    {
        "name": "audit.get_related_documents",
        "description": "Find all documents linked to a journal entry.",
        "func": journal.get_related_documents,
        "input_schema": DocumentInput,
    },
    # ── Revenue Audit ──
    {
        "name": "audit.get_sales_cycle",
        "description": "Trace the full sales cycle: SO -> DN -> SI -> Payment.",
        "func": sales.get_sales_cycle,
        "input_schema": SalesDocInput,
    },
    {
        "name": "audit.find_invoice_without_delivery",
        "description": "Find sales invoices with no linked delivery note.",
        "func": sales.find_invoice_without_delivery,
        "input_schema": DocumentListInput,
    },
    {
        "name": "audit.find_delivery_without_invoice",
        "description": "Find delivery notes with no matching sales invoice.",
        "func": sales.find_delivery_without_invoice,
        "input_schema": DocumentListInput,
    },
    {
        "name": "audit.find_revenue_cutoff_errors",
        "description": "Find invoices where posting date is inconsistent with delivery date.",
        "func": sales.find_revenue_cutoff_errors,
        "input_schema": DocumentListInput,
    },
    {
        "name": "audit.find_unusual_sales",
        "description": "Find statistically unusual sales transactions (outliers).",
        "func": sales.find_unusual_sales,
        "input_schema": DocumentListInput,
    },
    # ── Purchase Audit ──
    {
        "name": "audit.get_purchase_cycle",
        "description": "Trace the full purchase cycle: PO -> PR -> PI -> Payment.",
        "func": purchase.get_purchase_cycle,
        "input_schema": PurchaseDocInput,
    },
    {
        "name": "audit.test_three_way_matching",
        "description": "Verify PO vs PR vs PI quantity and rate matching.",
        "func": purchase.test_three_way_matching,
        "input_schema": ThreeWayMatchInput,
    },
    {
        "name": "audit.find_duplicate_supplier_invoice",
        "description": "Detect potential duplicate supplier invoices.",
        "func": purchase.find_duplicate_supplier_invoice,
        "input_schema": ThreeWayMatchInput,
    },
    {
        "name": "audit.find_payment_without_invoice",
        "description": "Find payments to suppliers with no linked purchase invoice.",
        "func": purchase.find_payment_without_invoice,
        "input_schema": ThreeWayMatchInput,
    },
    {
        "name": "audit.find_invoice_without_po",
        "description": "Find purchase invoices that bypass the PO process.",
        "func": purchase.find_invoice_without_po,
        "input_schema": ThreeWayMatchInput,
    },
    # ── Inventory Audit ──
    {
        "name": "audit.get_stock_ledger",
        "description": "Fetch stock ledger entries with filters.",
        "func": inventory.get_stock_ledger,
        "input_schema": StockLedgerInput,
    },
    {
        "name": "audit.find_negative_inventory",
        "description": "Find items/warehouses with negative stock balances.",
        "func": inventory.find_negative_inventory,
        "input_schema": StockLedgerInput,
    },
    {
        "name": "audit.find_large_stock_adjustments",
        "description": "Find stock reconciliation entries or stock entries exceeding thresholds.",
        "func": inventory.find_large_stock_adjustments,
        "input_schema": StockLedgerInput,
    },
    {
        "name": "audit.inventory_valuation",
        "description": "Compare inventory valuation settings against General Ledger values.",
        "func": inventory.inventory_valuation,
        "input_schema": StockLedgerInput,
    },
    {
        "name": "audit.find_inventory_anomalies",
        "description": "Detect anomalies like backdated stock movements or zero-value receipts.",
        "func": inventory.find_inventory_anomalies,
        "input_schema": StockLedgerInput,
    },
    # ── Banking Audit ──
    {
        "name": "audit.get_bank_reconciliation",
        "description": "Fetch details of bank reconciliation state and cleared transactions.",
        "func": banking.get_bank_reconciliation,
        "input_schema": BankReconciliationInput,
    },
    {
        "name": "audit.find_unreconciled_transactions",
        "description": "Find stale unreconciled bank transactions.",
        "func": banking.find_unreconciled_transactions,
        "input_schema": BankReconciliationInput,
    },
    {
        "name": "audit.find_cash_transactions",
        "description": "Identify entries posted directly against cash/petty cash accounts.",
        "func": banking.find_cash_transactions,
        "input_schema": BankReconciliationInput,
    },
    {
        "name": "audit.find_duplicate_payments",
        "description": "Identify duplicate payment entries.",
        "func": banking.find_duplicate_payments,
        "input_schema": BankReconciliationInput,
    },
    # ── Fixed Assets ──
    {
        "name": "audit.get_asset_register",
        "description": "Fetch the asset register with acquisition and depreciation details.",
        "func": assets.get_asset_register,
        "input_schema": AssetInput,
    },
    {
        "name": "audit.test_asset_existence",
        "description": "Cross-reference asset register entries against purchase invoices.",
        "func": assets.test_asset_existence,
        "input_schema": AssetInput,
    },
    {
        "name": "audit.check_depreciation",
        "description": "Verify depreciation postings and schedules for assets.",
        "func": assets.check_depreciation,
        "input_schema": AssetInput,
    },
    {
        "name": "audit.find_asset_disposals",
        "description": "Identify and review asset disposals, sales, and scrap entries.",
        "func": assets.find_asset_disposals,
        "input_schema": AssetInput,
    },
    # ── User Access Audit ──
    {
        "name": "audit.get_users",
        "description": "Fetch active users, emails, status, and last login dates.",
        "func": users.get_users,
        "input_schema": UserListInput,
    },
    {
        "name": "audit.get_roles",
        "description": "Fetch all active security roles.",
        "func": users.get_roles,
        "input_schema": EmptyInput,
    },
    {
        "name": "audit.get_permissions",
        "description": "Fetch permission rules mapping roles to doctype access.",
        "func": users.get_permissions,
        "input_schema": EmptyInput,
    },
    {
        "name": "audit.get_system_managers",
        "description": "Identify users with superuser / System Manager privileges.",
        "func": users.get_system_managers,
        "input_schema": EmptyInput,
    },
    {
        "name": "audit.permission_changes",
        "description": "Audit version logs of modifications to user permissions/roles.",
        "func": users.permission_changes,
        "input_schema": UserInput,
    },
    {
        "name": "audit.login_history",
        "description": "Fetch user login/logout history logs.",
        "func": users.login_history,
        "input_schema": UserInput,
    },
    {
        "name": "audit.failed_login_attempts",
        "description": "Find failed login attempts.",
        "func": users.failed_login_attempts,
        "input_schema": UserInput,
    },
    # ── Segregation of Duties ──
    {
        "name": "audit.check_sod_conflicts",
        "description": "Analyze active users against the Segregation of Duties conflict matrix.",
        "func": permissions.check_sod_conflicts,
        "input_schema": SoDInput,
    },
    # ── Workflow Audit ──
    {
        "name": "audit.get_workflows",
        "description": "Fetch all workflow configurations and transition rules.",
        "func": workflow.get_workflows,
        "input_schema": WorkflowInput,
    },
    {
        "name": "audit.workflow_history",
        "description": "Fetch workflow log/transition history for a specific document.",
        "func": workflow.workflow_history,
        "input_schema": WorkflowInput,
    },
    {
        "name": "audit.find_skipped_approvals",
        "description": "Find documents that bypassed defined workflow transitions.",
        "func": workflow.find_skipped_approvals,
        "input_schema": WorkflowInput,
    },
    {
        "name": "audit.find_approval_bypass",
        "description": "Find documents finalized by users other than the designated workflow steps.",
        "func": workflow.find_approval_bypass,
        "input_schema": WorkflowInput,
    },
    # ── Audit Trail ──
    {
        "name": "audit.get_document_history",
        "description": "Fetch complete document version history including edits and creators.",
        "func": audittrail.get_document_history,
        "input_schema": DocumentInput,
    },
    {
        "name": "audit.get_version_changes",
        "description": "Fetch detailed field-level version differences for a document.",
        "func": audittrail.get_version_changes,
        "input_schema": DocumentInput,
    },
    {
        "name": "audit.get_activity_log",
        "description": "Fetch activity logs filtering by user, action, or date.",
        "func": audittrail.get_activity_log,
        "input_schema": ActivityLogInput,
    },
    {
        "name": "audit.get_cancelled_documents",
        "description": "Identify cancelled documents (docstatus = 2) for fraud risk.",
        "func": audittrail.get_cancelled_documents,
        "input_schema": DocumentListInput,
    },
    {
        "name": "audit.find_modified_after_approval",
        "description": "Find documents modified after approval/submission.",
        "func": audittrail.find_modified_after_approval,
        "input_schema": DocumentListInput,
    },
    # ── Fraud Analytics ──
    {
        "name": "audit.detect_duplicate_transactions",
        "description": "Identify duplicate transaction entries across any DocType.",
        "func": fraud.detect_duplicate_transactions,
        "input_schema": FraudDetectionInput,
    },
    {
        "name": "audit.detect_duplicate_suppliers",
        "description": "Fuzzy match supplier names to detect potential duplicates.",
        "func": fraud.detect_duplicate_suppliers,
        "input_schema": FraudDetectionInput,
    },
    {
        "name": "audit.detect_duplicate_payments",
        "description": "Find potential duplicate payment entries.",
        "func": fraud.detect_duplicate_payments,
        "input_schema": FraudDetectionInput,
    },
    {
        "name": "audit.benford_analysis",
        "description": "Perform Benford's Law first-digit distribution check on transaction amounts.",
        "func": fraud.benford_analysis,
        "input_schema": BenfordInput,
    },
    {
        "name": "audit.detect_round_amounts",
        "description": "Find entries with suspiciously round amounts.",
        "func": fraud.detect_round_amounts,
        "input_schema": FraudDetectionInput,
    },
    {
        "name": "audit.detect_unusual_users",
        "description": "Analyze activity levels per user to find outliers or compromised profiles.",
        "func": fraud.detect_unusual_users,
        "input_schema": FraudDetectionInput,
    },
    {
        "name": "audit.detect_after_hours_activity",
        "description": "Find entries created outside standard business hours or on weekends.",
        "func": fraud.detect_after_hours_activity,
        "input_schema": FraudDetectionInput,
    },
    {
        "name": "audit.detect_management_override",
        "description": "Identify direct administrator database postings, overrides, or bypasses.",
        "func": fraud.detect_management_override,
        "input_schema": FraudDetectionInput,
    },
    # ── Audit Sampling ──
    {
        "name": "audit.random_sample",
        "description": "Select a simple random sample from a DocType population.",
        "func": sampling.random_sample,
        "input_schema": SampleInput,
    },
    {
        "name": "audit.high_value_sample",
        "description": "Select the highest-value items from the population.",
        "func": sampling.high_value_sample,
        "input_schema": SampleInput,
    },
    {
        "name": "audit.risk_based_sample",
        "description": "Select a risk-weighted sample based on suspicious properties.",
        "func": sampling.risk_based_sample,
        "input_schema": SampleInput,
    },
    {
        "name": "audit.monetary_unit_sample",
        "description": "Select items using Monetary Unit Sampling (MUS) probability proportional to size.",
        "func": sampling.monetary_unit_sample,
        "input_schema": SampleInput,
    },
    # ── Investigation Engine ──
    {
        "name": "audit.investigate_transaction",
        "description": "Deep-dive investigation of a transaction to check validity and fraud risk.",
        "func": investigation.investigate_transaction,
        "input_schema": InvestigateInput,
    },
    # ── Evidence Management ──
    {
        "name": "audit.collect_evidence",
        "description": "Gather complete evidence package for a specific transaction.",
        "func": evidence.collect_evidence,
        "input_schema": EvidenceInput,
    },
    {
        "name": "audit.create_workpaper",
        "description": "Create a structured audit workpaper summarizing testing procedures and results.",
        "func": evidence.create_workpaper,
        "input_schema": WorkpaperInput,
    },
    # ── Reporting ──
    {
        "name": "audit.create_finding",
        "description": "Create a formal audit finding with risk ratings, assertions, and recommendations.",
        "func": reporting.create_finding,
        "input_schema": FindingInput,
    },
    {
        "name": "audit.generate_audit_report",
        "description": "Produce the final comprehensive audit report.",
        "func": reporting.generate_audit_report,
        "input_schema": ReportInput,
    },
    {
        "name": "audit.generate_management_letter",
        "description": "Produce the management letter with control recommendations.",
        "func": reporting.generate_management_letter,
        "input_schema": ReportInput,
    },
]

# Dynamically register all tools in the registry
for spec in AUDIT_TOOLS_SPEC:
    registry.register(
        name=spec["name"],
        description=spec["description"],
        required_scope="audit:read",
        input_schema=spec["input_schema"],
    )(spec["func"])
