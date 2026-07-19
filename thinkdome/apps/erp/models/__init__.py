"""ERP ORM Models — auto-registered via metaclass on import."""

from __future__ import annotations

# Full accounting domain (COMPLETE)
from thinkdome.apps.erp.models.accounting import (
    Account,
    JournalEntry,
    JournalEntryLine,
    FiscalYear,
    CostCenter,
    SalesInvoice,
    PurchaseInvoice,
    Payment,
    BankAccount,
    CashFlowEntry,
    BankReconciliation,
    Budget,
    BudgetLine,
    TaxRate,
    PaymentTerm,
    Asset,
    AssetDepreciation,
    CreditNote,
    DebitNote,
    ExchangeRate,
    ChequeEntry,
    Subscription,
    RecurringEntry,
    CreditLimit,
    DunningNotice,
    PeriodClosing,
    AuditLog,
)

# Stub domains (TODO — future implementation)
from thinkdome.apps.erp.models.stubs import (
    Employee,
    Department,
    Attendance,
    LeaveRequest,
    Payroll,
    Item,
    Warehouse,
    StockEntry,
    Lead,
    Opportunity,
    Project,
    Task,
)

__all__ = [
    # Accounting Core
    "Account", "JournalEntry", "JournalEntryLine", "FiscalYear", "CostCenter",
    "SalesInvoice", "PurchaseInvoice", "Payment",
    "BankAccount", "CashFlowEntry", "BankReconciliation",
    "Budget", "BudgetLine", "TaxRate", "PaymentTerm",
    "Asset", "AssetDepreciation",
    # Financial Extensions
    "CreditNote", "DebitNote", "ExchangeRate", "ChequeEntry",
    "Subscription", "RecurringEntry", "CreditLimit",
    "DunningNotice", "PeriodClosing", "AuditLog",
    # Stubs
    "Employee", "Department", "Attendance", "LeaveRequest", "Payroll",
    "Item", "Warehouse", "StockEntry",
    "Lead", "Opportunity",
    "Project", "Task",
]
