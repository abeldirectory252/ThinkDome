"""ORM Models for Accounting.

Declares all tables and entities required for a complete double-entry
financial bookkeeping and budgeting system in ThinkDome.
"""

from __future__ import annotations

from thinkdome.core.orm.orm import (
    Model,
    StringField,
    IntegerField,
    FloatField,
    BooleanField,
    SelectField,
    UUIDField,
)


class Account(Model):
    """Chart of Accounts node."""

    name = StringField(required=True)
    account_type = SelectField(
        choices=[
            "Asset", "Liability", "Equity", "Revenue", "Expense",
            "Bank", "Cash", "Receivable", "Payable", "Cost of Goods Sold",
            "Tax", "Depreciation", "Income"
        ],
        required=True
    )
    parent_account = StringField()  # Parent Account ID (for hierarchical tree)
    root_type = SelectField(choices=["Asset", "Liability", "Equity", "Revenue", "Expense"], required=True)
    balance = FloatField(default=0.0)
    currency = StringField(default="USD")
    is_group = BooleanField(default=False)  # True if it's a folder containing other accounts


class JournalEntry(Model):
    """Double-entry general ledger posting header."""

    posting_date = StringField(required=True)  # ISO date string YYYY-MM-DD
    entry_type = SelectField(
        choices=["Journal Entry", "Payment", "Receipt", "Contra", "Opening", "Depreciation"],
        default="Journal Entry"
    )
    total_debit = FloatField(default=0.0)
    total_credit = FloatField(default=0.0)
    status = SelectField(choices=["Draft", "Submitted", "Cancelled"], default="Draft")
    narration = StringField(default="")
    reference_type = StringField()  # e.g., SalesInvoice, PurchaseInvoice
    reference_id = StringField()


class JournalEntryLine(Model):
    """Individual debit/credit entries linked to a JournalEntry."""

    journal_entry_id = StringField(required=True)  # FK to JournalEntry
    account = StringField(required=True)  # Account ID
    debit = FloatField(default=0.0)
    credit = FloatField(default=0.0)
    party_type = SelectField(choices=["Customer", "Supplier", "Employee", "Shareholder"])
    party = StringField()  # Party ID (e.g. customer ID, supplier ID)
    cost_center = StringField()  # Cost Center ID


class FiscalYear(Model):
    """Accounting period definitions."""

    year_name = StringField(required=True)  # e.g., "2026"
    start_date = StringField(required=True)  # ISO Date
    end_date = StringField(required=True)  # ISO Date
    is_closed = BooleanField(default=False)


class CostCenter(Model):
    """Cost/profit tracker for divisional breakdown."""

    name = StringField(required=True)
    parent_cost_center = StringField()
    department = StringField()


class SalesInvoice(Model):
    """Sales invoice representing client sales billing."""

    customer = StringField(required=True)  # Customer name/ID
    posting_date = StringField(required=True)
    items_json = StringField(default="[]")  # JSON encoded list of items
    net_total = FloatField(default=0.0)
    tax_total = FloatField(default=0.0)
    grand_total = FloatField(default=0.0)
    outstanding = FloatField(default=0.0)
    status = SelectField(choices=["Draft", "Submitted", "Paid", "Partly Paid", "Unpaid", "Cancelled"], default="Draft")
    payment_terms = StringField()  # Link to PaymentTerm
    cost_center = StringField()


class PurchaseInvoice(Model):
    """Purchase invoice representing supplier procurement billing."""

    supplier = StringField(required=True)  # Supplier name/ID
    posting_date = StringField(required=True)
    items_json = StringField(default="[]")  # JSON encoded list of items
    net_total = FloatField(default=0.0)
    tax_total = FloatField(default=0.0)
    grand_total = FloatField(default=0.0)
    outstanding = FloatField(default=0.0)
    status = SelectField(choices=["Draft", "Submitted", "Paid", "Partly Paid", "Unpaid", "Cancelled"], default="Draft")
    cost_center = StringField()


class Payment(Model):
    """Payment transaction entry linking invoices to bank accounts."""

    party_type = SelectField(choices=["Customer", "Supplier", "Employee"], required=True)
    party = StringField(required=True)
    amount = FloatField(default=0.0)
    payment_type = SelectField(choices=["Receive", "Pay"], required=True)
    mode_of_payment = SelectField(choices=["Bank", "Cash", "Credit Card", "Wire Transfer"], default="Bank")
    bank_account = StringField(required=True)  # BankAccount ID
    reference_type = StringField()  # e.g., SalesInvoice, PurchaseInvoice
    reference_id = StringField()
    posting_date = StringField(required=True)
    narration = StringField(default="")


class BankAccount(Model):
    """Company Bank Accounts."""

    account_name = StringField(required=True)
    bank_name = StringField(required=True)
    account_number = StringField(required=True)
    balance = FloatField(default=0.0)
    currency = StringField(default="USD")
    last_synced = StringField()


class CashFlowEntry(Model):
    """Manual or automated cash flow statement line-items."""

    flow_type = SelectField(choices=["Inflow", "Outflow"], required=True)
    amount = FloatField(default=0.0)
    category = SelectField(choices=["Operating", "Investing", "Financing"], required=True)
    description = StringField(default="")
    bank_account = StringField(required=True)
    posting_date = StringField(required=True)


class BankReconciliation(Model):
    """Bank statement reconciliation records."""

    bank_account = StringField(required=True)
    statement_date = StringField(required=True)
    statement_balance = FloatField(default=0.0)
    system_balance = FloatField(default=0.0)
    status = SelectField(choices=["Draft", "Reconciled"], default="Draft")


class Budget(Model):
    """High-level budgetary ceilings per department and period."""

    fiscal_year = StringField(required=True)  # FiscalYear ID
    department = StringField()
    total_allocated = FloatField(default=0.0)
    total_spent = FloatField(default=0.0)
    status = SelectField(choices=["Active", "Closed"], default="Active")


class BudgetLine(Model):
    """Allocated budget limits per account."""

    budget_id = StringField(required=True)  # Budget ID
    account = StringField(required=True)  # Account ID
    allocated = FloatField(default=0.0)
    actual = FloatField(default=0.0)
    variance = FloatField(default=0.0)


class TaxRate(Model):
    """Tax templates used across invoices."""

    tax_name = StringField(required=True)
    rate_percent = FloatField(default=0.0)
    tax_type = SelectField(choices=["Sales Tax", "VAT", "Withholding Tax"], default="Sales Tax")
    is_default = BooleanField(default=False)


class PaymentTerm(Model):
    """Payment term templates defining outstanding terms."""

    term_name = StringField(required=True)
    days = IntegerField(default=30)
    discount_percent = FloatField(default=0.0)
    description = StringField(default="")


class Asset(Model):
    """Fixed asset tracker."""

    asset_name = StringField(required=True)
    asset_category = StringField(default="Equipment")
    purchase_date = StringField(required=True)
    purchase_value = FloatField(default=0.0)
    current_value = FloatField(default=0.0)
    depreciation_method = SelectField(choices=["Straight Line", "Declining Balance"], default="Straight Line")
    useful_life_years = IntegerField(default=5)
    status = SelectField(choices=["Active", "Retired", "Scrapped"], default="Active")
    cost_center = StringField()
    asset_account = StringField()  # Account ID
    depreciation_account = StringField()  # Account ID


class AssetDepreciation(Model):
    """Depreciation ledger entry."""

    asset_id = StringField(required=True)
    posting_date = StringField(required=True)
    depreciation_amount = FloatField(default=0.0)
    accumulated_depreciation = FloatField(default=0.0)
    remaining_value = FloatField(default=0.0)


class CreditNote(Model):
    """Sales return — reverses a Sales Invoice partially or fully."""

    original_invoice_id = StringField(required=True)
    customer = StringField(required=True)
    posting_date = StringField(required=True)
    items_json = StringField(default="[]")
    net_total = FloatField(default=0.0)
    tax_total = FloatField(default=0.0)
    grand_total = FloatField(default=0.0)
    reason = StringField(default="")
    status = SelectField(choices=["Draft", "Submitted", "Cancelled"], default="Draft")


class DebitNote(Model):
    """Purchase return — reverses a Purchase Invoice partially or fully."""

    original_invoice_id = StringField(required=True)
    supplier = StringField(required=True)
    posting_date = StringField(required=True)
    items_json = StringField(default="[]")
    net_total = FloatField(default=0.0)
    tax_total = FloatField(default=0.0)
    grand_total = FloatField(default=0.0)
    reason = StringField(default="")
    status = SelectField(choices=["Draft", "Submitted", "Cancelled"], default="Draft")


class ExchangeRate(Model):
    """Currency exchange rate table for multi-currency support."""

    from_currency = StringField(required=True)
    to_currency = StringField(required=True)
    rate = FloatField(required=True)
    effective_date = StringField(required=True)


class ChequeEntry(Model):
    """Cheque lifecycle tracker (issue → clear/bounce)."""

    cheque_number = StringField(required=True)
    party_type = SelectField(choices=["Customer", "Supplier", "Employee"], required=True)
    party = StringField(required=True)
    amount = FloatField(default=0.0)
    bank_account = StringField(required=True)
    cheque_date = StringField(required=True)
    clearance_date = StringField()
    status = SelectField(choices=["Issued", "Cleared", "Bounced", "Cancelled"], default="Issued")
    direction = SelectField(choices=["Outgoing", "Incoming"], required=True)


class Subscription(Model):
    """Recurring billing subscriptions generating periodic invoices."""

    customer = StringField(required=True)
    plan_name = StringField(required=True)
    amount = FloatField(default=0.0)
    frequency = SelectField(choices=["Monthly", "Quarterly", "Semi-Annual", "Annual"], default="Monthly")
    start_date = StringField(required=True)
    next_invoice_date = StringField(required=True)
    status = SelectField(choices=["Active", "Paused", "Cancelled", "Completed"], default="Active")
    invoices_generated = IntegerField(default=0)
    total_billed = FloatField(default=0.0)


class RecurringEntry(Model):
    """Template for auto-repeat journal entries (rent, salaries, etc.)."""

    template_narration = StringField(required=True)
    lines_json = StringField(required=True)  # JSON serialized journal lines
    frequency = SelectField(choices=["Monthly", "Quarterly", "Annual"], default="Monthly")
    next_posting_date = StringField(required=True)
    last_posted_date = StringField()
    is_active = BooleanField(default=True)
    times_posted = IntegerField(default=0)


class CreditLimit(Model):
    """Per-customer credit ceiling enforcement."""

    customer = StringField(required=True)
    credit_limit = FloatField(default=0.0)
    bypass_credit_limit = BooleanField(default=False)


class DunningNotice(Model):
    """Payment reminder / collection notice sent to overdue customers."""

    customer = StringField(required=True)
    invoice_id = StringField(required=True)
    dunning_date = StringField(required=True)
    outstanding_amount = FloatField(default=0.0)
    days_overdue = IntegerField(default=0)
    dunning_level = SelectField(choices=["Reminder", "Warning", "Final Notice", "Legal"], default="Reminder")
    status = SelectField(choices=["Sent", "Acknowledged", "Resolved"], default="Sent")


class PeriodClosing(Model):
    """Fiscal period closing voucher — transfers P&L balances to retained earnings."""

    fiscal_year = StringField(required=True)
    closing_date = StringField(required=True)
    closing_account = StringField(required=True)  # Retained Earnings account ID
    net_pl_amount = FloatField(default=0.0)
    status = SelectField(choices=["Draft", "Submitted"], default="Draft")


class AuditLog(Model):
    """Immutable audit trail for all financial transactions."""

    entity_type = StringField(required=True)  # e.g. JournalEntry, SalesInvoice
    entity_id = StringField(required=True)
    action = SelectField(choices=["Created", "Updated", "Deleted", "Submitted", "Cancelled", "Reversed"], required=True)
    timestamp = StringField(required=True)
    user = StringField(default="system")
    details = StringField(default="")
    previous_state = StringField(default="")  # JSON snapshot

