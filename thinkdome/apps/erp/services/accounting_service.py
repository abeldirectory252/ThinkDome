"""Accounting Service.

Implements all core business logic for double-entry bookkeeping, invoicing,
payment posting, bank reconciliation, and budget control.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

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


class AccountingService:
    """Business operations for Chart of Accounts, Journal Entries, Invoices, Payments, and Budgets."""

    # ── Chart of Accounts ─────────────────────────────────────────────────────

    def get_chart_of_accounts(self) -> List[Dict[str, Any]]:
        """Retrieve the entire Chart of Accounts tree structure."""
        accounts = Account.query().all()
        # Sort and structure as a tree
        account_list = [a.to_dict() for a in accounts]
        return account_list

    def create_account(
        self,
        name: str,
        account_type: str,
        root_type: str,
        parent_account: Optional[str] = None,
        currency: str = "USD",
        is_group: bool = False
    ) -> Dict[str, Any]:
        """Create a new account node in the Chart of Accounts."""
        # Ensure parent exists if specified
        if parent_account:
            parent = Account.get(parent_account)
            if not parent:
                raise ValueError(f"Parent account '{parent_account}' not found.")
            if not parent.is_group:
                # Upgrade parent to be a group if it wasn't
                parent._values["is_group"] = True
                parent.save()

        acc = Account(
            name=name,
            account_type=account_type,
            root_type=root_type,
            parent_account=parent_account,
            balance=0.0,
            currency=currency,
            is_group=is_group
        )
        acc.save()
        return acc.to_dict()

    def get_account_balance(self, account_id: str, as_of_date: Optional[str] = None) -> float:
        """Calculate the point-in-time balance for an account."""
        acc = Account.get(account_id)
        if not acc:
            raise ValueError(f"Account '{account_id}' not found.")

        if not as_of_date:
            return acc.balance

        # Compute point-in-time balance from journal entry lines up to date
        lines = JournalEntryLine.query().filter(account=account_id).all()
        balance = 0.0
        for line in lines:
            je = JournalEntry.get(line.journal_entry_id)
            if je and je.status == "Submitted" and je.posting_date <= as_of_date:
                # Add debit/credit based on root type
                if acc.root_type in ["Asset", "Expense"]:
                    balance += (line.debit - line.credit)
                else:
                    balance += (line.credit - line.debit)
        return balance

    # ── Journal Entries & GL Ledger ──────────────────────────────────────────

    def post_journal_entry(
        self,
        lines: List[Dict[str, Any]],
        narration: str = "",
        posting_date: Optional[str] = None,
        entry_type: str = "Journal Entry",
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Post a validated double-entry transaction block.

        Lines schema:
        [
            {"account": "acc_id_1", "debit": 100.0, "credit": 0.0, "party_type": "...", "party": "..."},
            {"account": "acc_id_2", "debit": 0.0, "credit": 100.0, "party_type": "...", "party": "..."}
        ]
        """
        if not posting_date:
            posting_date = datetime.utcnow().strftime("%Y-%m-%d")

        # Validate that debits == credits
        total_debit = sum(float(line.get("debit", 0.0)) for line in lines)
        total_credit = sum(float(line.get("credit", 0.0)) for line in lines)

        if abs(total_debit - total_credit) > 0.001:
            raise ValueError(f"Double-entry validation failed: Total Debits (${total_debit:.2f}) must equal Total Credits (${total_credit:.2f}).")

        # Create Journal Entry Header
        je = JournalEntry(
            posting_date=posting_date,
            entry_type=entry_type,
            total_debit=total_debit,
            total_credit=total_credit,
            status="Submitted",  # Directly submit for instant GL posting in sandbox mode
            narration=narration,
            reference_type=reference_type,
            reference_id=reference_id
        )
        je.save()

        # Create Lines and Update Account Balances
        for line_data in lines:
            acc_id = line_data["account"]
            acc = Account.get(acc_id)
            if not acc:
                raise ValueError(f"Account '{acc_id}' not found.")

            debit = float(line_data.get("debit", 0.0))
            credit = float(line_data.get("credit", 0.0))

            # Validate budget if this is an expense account
            if debit > 0.0 and acc.root_type == "Expense":
                self.check_budget_exceeded(acc_id, debit)

            # Create line record
            line = JournalEntryLine(
                journal_entry_id=je.id,
                account=acc_id,
                debit=debit,
                credit=credit,
                party_type=line_data.get("party_type"),
                party=line_data.get("party"),
                cost_center=line_data.get("cost_center")
            )
            line.save()

            # Update account running balance
            # Assets & Expenses: Balance = Debit - Credit
            # Liabilities, Equity, Revenue: Balance = Credit - Debit
            balance_impact = (debit - credit) if acc.root_type in ["Asset", "Expense"] else (credit - debit)
            acc._values["balance"] += balance_impact
            acc.save()

            # Record budget actual spend if applicable
            if acc.root_type == "Expense":
                self._update_budget_actual(acc_id, debit)

        return je.to_dict()

    def reverse_journal_entry(self, entry_id: str, narration: str = "") -> Dict[str, Any]:
        """Post a reversal for a journal entry (creates matching opposing entry)."""
        je = JournalEntry.get(entry_id)
        if not je:
            raise ValueError(f"Journal Entry '{entry_id}' not found.")
        if je.status != "Submitted":
            raise ValueError(f"Only 'Submitted' journal entries can be reversed.")

        # Find all lines for the entry
        lines = JournalEntryLine.query().filter(journal_entry_id=entry_id).all()
        reversal_lines = []

        for line in lines:
            # Swap debit and credit
            reversal_lines.append({
                "account": line.account,
                "debit": line.credit,
                "credit": line.debit,
                "party_type": line.party_type,
                "party": line.party,
                "cost_center": line.cost_center
            })

        # Cancel the original entry status
        je._values["status"] = "Cancelled"
        je.save()

        # Post the reversal entry
        reversal_narration = narration or f"Reversal of Entry #{entry_id}: {je.narration}"
        return self.post_journal_entry(
            lines=reversal_lines,
            narration=reversal_narration,
            entry_type=je.entry_type,
            reference_type="JournalEntry",
            reference_id=entry_id
        )

    def get_general_ledger(
        self,
        account_id: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve General Ledger records for an account with running balances."""
        acc = Account.get(account_id)
        if not acc:
            raise ValueError(f"Account '{account_id}' not found.")

        lines = JournalEntryLine.query().filter(account=account_id).all()
        ledger_entries = []

        running_balance = 0.0
        # If there's a starting date, we should compute the starting balance up to that date
        if from_date:
            running_balance = self.get_account_balance(account_id, as_of_date=from_date)

        for line in lines:
            je = JournalEntry.get(line.journal_entry_id)
            if not je or je.status != "Submitted":
                continue

            posting_date = je.posting_date
            if from_date and posting_date < from_date:
                continue
            if to_date and posting_date > to_date:
                continue

            debit = line.debit
            credit = line.credit

            balance_impact = (debit - credit) if acc.root_type in ["Asset", "Expense"] else (credit - debit)
            running_balance += balance_impact

            ledger_entries.append({
                "posting_date": posting_date,
                "journal_entry_id": je.id,
                "entry_type": je.entry_type,
                "debit": debit,
                "credit": credit,
                "narration": je.narration,
                "reference_type": je.reference_type,
                "reference_id": je.reference_id,
                "running_balance": running_balance
            })

        # Sort chronologically
        ledger_entries.sort(key=lambda x: x["posting_date"])
        return ledger_entries

    def get_trial_balance(self, fiscal_year_id: str) -> Dict[str, Any]:
        """Generate Trial Balance report listing debit and credit balances for all accounts."""
        fy = FiscalYear.get(fiscal_year_id)
        if not fy:
            raise ValueError(f"Fiscal Year '{fiscal_year_id}' not found.")

        accounts = Account.query().all()
        trial_balance_rows = []
        grand_debit = 0.0
        grand_credit = 0.0

        for acc in accounts:
            if acc.is_group:
                continue

            # Get final balance as of fiscal year end
            balance = self.get_account_balance(acc.id, as_of_date=fy.end_date)

            debit_val = 0.0
            credit_val = 0.0

            if acc.root_type in ["Asset", "Expense"]:
                if balance >= 0:
                    debit_val = balance
                else:
                    credit_val = abs(balance)
            else:
                if balance >= 0:
                    credit_val = balance
                else:
                    debit_val = abs(balance)

            if debit_val > 0.0 or credit_val > 0.0:
                trial_balance_rows.append({
                    "account_id": acc.id,
                    "account_name": acc.name,
                    "account_type": acc.account_type,
                    "debit": debit_val,
                    "credit": credit_val
                })
                grand_debit += debit_val
                grand_credit += credit_val

        return {
            "fiscal_year": fy.year_name,
            "rows": trial_balance_rows,
            "total_debit": grand_debit,
            "total_credit": grand_credit,
            "is_balanced": abs(grand_debit - grand_credit) < 0.001
        }

    # ── Invoicing & Accounts Receivable/Payable ───────────────────────────────

    def create_sales_invoice(
        self,
        customer: str,
        items: List[Dict[str, Any]],
        tax_rate_id: Optional[str] = None,
        payment_terms: Optional[str] = None,
        cost_center: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create and submit a client sales invoice with automatic GL postings.

        GL Postings:
          Debit: Accounts Receivable (Asset)
          Credit: Sales/Revenue (Revenue)
          Credit: Tax Payable (Liability) [if tax applied]
        """
        posting_date = datetime.utcnow().strftime("%Y-%m-%d")

        net_total = sum(float(item.get("qty", 0)) * float(item.get("rate", 0.0)) for item in items)
        tax_amount = 0.0

        if tax_rate_id:
            tax = TaxRate.get(tax_rate_id)
            if tax:
                tax_amount = net_total * (tax.rate_percent / 100.0)

        grand_total = net_total + tax_amount

        invoice = SalesInvoice(
            customer=customer,
            posting_date=posting_date,
            items_json=json.dumps(items),
            net_total=net_total,
            tax_total=tax_amount,
            grand_total=grand_total,
            outstanding=grand_total,
            status="Submitted",  # Instantly submit in sandbox
            payment_terms=payment_terms,
            cost_center=cost_center
        )
        invoice.save()

        # Find standard accounts
        ar_account = self._find_or_create_default_account("Accounts Receivable", "Receivable", "Asset")
        revenue_account = self._find_or_create_default_account("Sales Revenue", "Revenue", "Revenue")

        gl_lines = [
            {"account": ar_account.id, "debit": grand_total, "credit": 0.0, "party_type": "Customer", "party": customer},
            {"account": revenue_account.id, "debit": 0.0, "credit": net_total, "cost_center": cost_center}
        ]

        if tax_amount > 0.0:
            tax_payable_acc = self._find_or_create_default_account("Sales Tax Payable", "Tax", "Liability")
            gl_lines.append({"account": tax_payable_acc.id, "debit": 0.0, "credit": tax_amount})

        # Post to General Ledger
        self.post_journal_entry(
            lines=gl_lines,
            narration=f"Sales Invoice #{invoice.id} to {customer}",
            posting_date=posting_date,
            entry_type="Receipt",
            reference_type="SalesInvoice",
            reference_id=invoice.id
        )

        return invoice.to_dict()

    def create_purchase_invoice(
        self,
        supplier: str,
        items: List[Dict[str, Any]],
        tax_rate_id: Optional[str] = None,
        cost_center: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create and submit a supplier purchase invoice with automatic GL postings.

        GL Postings:
          Debit: Expense/Cost of Goods Sold (Expense)
          Debit: Tax Asset/Receivable (Asset) [if applicable]
          Credit: Accounts Payable (Liability)
        """
        posting_date = datetime.utcnow().strftime("%Y-%m-%d")

        net_total = sum(float(item.get("qty", 0)) * float(item.get("rate", 0.0)) for item in items)
        tax_amount = 0.0

        if tax_rate_id:
            tax = TaxRate.get(tax_rate_id)
            if tax:
                tax_amount = net_total * (tax.rate_percent / 100.0)

        grand_total = net_total + tax_amount

        invoice = PurchaseInvoice(
            supplier=supplier,
            posting_date=posting_date,
            items_json=json.dumps(items),
            net_total=net_total,
            tax_total=tax_amount,
            grand_total=grand_total,
            outstanding=grand_total,
            status="Submitted",
            cost_center=cost_center
        )
        invoice.save()

        # Find standard accounts
        ap_account = self._find_or_create_default_account("Accounts Payable", "Payable", "Liability")
        expense_account = self._find_or_create_default_account("Cost of Goods Sold", "Cost of Goods Sold", "Expense")

        gl_lines = [
            {"account": expense_account.id, "debit": net_total, "credit": 0.0, "cost_center": cost_center},
            {"account": ap_account.id, "debit": 0.0, "credit": grand_total, "party_type": "Supplier", "party": supplier}
        ]

        if tax_amount > 0.0:
            tax_asset_acc = self._find_or_create_default_account("Purchase Tax Receivable", "Tax", "Asset")
            gl_lines.append({"account": tax_asset_acc.id, "debit": tax_amount, "credit": 0.0})

        # Post to General Ledger
        self.post_journal_entry(
            lines=gl_lines,
            narration=f"Purchase Invoice #{invoice.id} from {supplier}",
            posting_date=posting_date,
            entry_type="Payment",
            reference_type="PurchaseInvoice",
            reference_id=invoice.id
        )

        return invoice.to_dict()

    def record_payment(
        self,
        party_type: str,
        party: str,
        amount: float,
        payment_type: str,  # Receive (Customer) or Pay (Supplier)
        bank_account_id: str,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        mode_of_payment: str = "Bank"
    ) -> Dict[str, Any]:
        """Record receipt or payment transactions, reconciles outstanding invoice balances.

        GL Postings:
          If Receive (from Customer):
            Debit: Cash/Bank Account (Asset)
            Credit: Accounts Receivable (Asset)
          If Pay (to Supplier):
            Debit: Accounts Payable (Liability)
            Credit: Cash/Bank Account (Asset)
        """
        posting_date = datetime.utcnow().strftime("%Y-%m-%d")

        bank = BankAccount.get(bank_account_id)
        if not bank:
            raise ValueError(f"Bank Account '{bank_account_id}' not found.")

        # Find matching account mapping for bank ledger posting
        bank_ledger_acc = self._find_or_create_default_account(bank.account_name, "Bank", "Asset")

        payment = Payment(
            party_type=party_type,
            party=party,
            amount=amount,
            payment_type=payment_type,
            mode_of_payment=mode_of_payment,
            bank_account=bank_account_id,
            reference_type=reference_type,
            reference_id=reference_id,
            posting_date=posting_date
        )
        payment.save()

        # Reconcile outstanding invoice values if reference specified
        if reference_type == "SalesInvoice" and reference_id:
            invoice = SalesInvoice.get(reference_id)
            if invoice:
                invoice._values["outstanding"] = max(0.0, invoice.outstanding - amount)
                if invoice.outstanding <= 0.01:
                    invoice._values["status"] = "Paid"
                else:
                    invoice._values["status"] = "Partly Paid"
                invoice.save()

        elif reference_type == "PurchaseInvoice" and reference_id:
            invoice = PurchaseInvoice.get(reference_id)
            if invoice:
                invoice._values["outstanding"] = max(0.0, invoice.outstanding - amount)
                if invoice.outstanding <= 0.01:
                    invoice._values["status"] = "Paid"
                else:
                    invoice._values["status"] = "Partly Paid"
                invoice.save()

        # Formulate general ledger lines
        gl_lines = []
        if payment_type == "Receive":
            ar_account = self._find_or_create_default_account("Accounts Receivable", "Receivable", "Asset")
            gl_lines = [
                {"account": bank_ledger_acc.id, "debit": amount, "credit": 0.0},
                {"account": ar_account.id, "debit": 0.0, "credit": amount, "party_type": "Customer", "party": party}
            ]
            bank._values["balance"] += amount
            # Also record CashFlowEntry
            cf = CashFlowEntry(
                flow_type="Inflow",
                amount=amount,
                category="Operating",
                description=f"Received payment from customer {party}",
                bank_account=bank_account_id,
                posting_date=posting_date
            )
            cf.save()
        else:
            ap_account = self._find_or_create_default_account("Accounts Payable", "Payable", "Liability")
            gl_lines = [
                {"account": ap_account.id, "debit": amount, "credit": 0.0, "party_type": "Supplier", "party": party},
                {"account": bank_ledger_acc.id, "debit": 0.0, "credit": amount}
            ]
            bank._values["balance"] -= amount
            # Also record CashFlowEntry
            cf = CashFlowEntry(
                flow_type="Outflow",
                amount=amount,
                category="Operating",
                description=f"Paid supplier {party}",
                bank_account=bank_account_id,
                posting_date=posting_date
            )
            cf.save()

        bank.save()

        # Post general ledger entries
        self.post_journal_entry(
            lines=gl_lines,
            narration=f"{payment_type} Payment of ${amount:.2f} via {mode_of_payment}. Ref: {reference_type or ''} {reference_id or ''}",
            posting_date=posting_date,
            entry_type="Payment" if payment_type == "Pay" else "Receipt",
            reference_type="Payment",
            reference_id=payment.id
        )

        return payment.to_dict()

    def get_accounts_receivable(self) -> List[Dict[str, Any]]:
        """List customer accounts outstanding invoicing totals."""
        invoices = SalesInvoice.query().all()
        aging = []
        for inv in invoices:
            if inv.status in ["Submitted", "Partly Paid"] and inv.outstanding > 0.0:
                aging.append({
                    "customer": inv.customer,
                    "invoice_id": inv.id,
                    "posting_date": inv.posting_date,
                    "grand_total": inv.grand_total,
                    "outstanding": inv.outstanding
                })
        return aging

    def get_accounts_payable(self) -> List[Dict[str, Any]]:
        """List supplier accounts outstanding procurement obligations."""
        invoices = PurchaseInvoice.query().all()
        aging = []
        for inv in invoices:
            if inv.status in ["Submitted", "Partly Paid"] and inv.outstanding > 0.0:
                aging.append({
                    "supplier": inv.supplier,
                    "invoice_id": inv.id,
                    "posting_date": inv.posting_date,
                    "grand_total": inv.grand_total,
                    "outstanding": inv.outstanding
                })
        return aging

    # ── Bank Reconciliation & Cash Flow forecasting ─────────────────────────

    def reconcile_bank(
        self,
        bank_account_id: str,
        statement_balance: float,
        statement_date: str
    ) -> Dict[str, Any]:
        """Perform reconciliation check of Bank Statement Balance against System Balance."""
        bank = BankAccount.get(bank_account_id)
        if not bank:
            raise ValueError(f"Bank Account '{bank_account_id}' not found.")

        # Find matching account mapping for ledger balance
        bank_ledger_acc = self._find_or_create_default_account(bank.account_name, "Bank", "Asset")
        system_balance = bank_ledger_acc.balance

        diff = abs(statement_balance - system_balance)

        reconciliation = BankReconciliation(
            bank_account=bank_account_id,
            statement_date=statement_date,
            statement_balance=statement_balance,
            system_balance=system_balance,
            status="Reconciled" if diff < 0.01 else "Draft"
        )
        reconciliation.save()

        # Update last synced tag
        bank._values["last_synced"] = statement_date
        bank.save()

        return {
            "reconciliation_id": reconciliation.id,
            "bank_account": bank.account_name,
            "statement_balance": statement_balance,
            "system_balance": system_balance,
            "difference": diff,
            "status": reconciliation.status
        }

    # ── Budget Enforcement & Checks ──────────────────────────────────────────

    def create_budget(
        self,
        fiscal_year: str,
        department: str,
        allocations: Dict[str, float]
    ) -> Dict[str, Any]:
        """Set up a department budget with allocations to specific expense accounts."""
        total_allocated = sum(allocations.values())

        # Check if budget already exists for this FY + Dept combo
        existing = Budget.query().filter(fiscal_year=fiscal_year, department=department).first()
        if existing:
            # Update existing budget
            budget = existing
            budget._values["total_allocated"] = total_allocated
            budget.save()
            # Remove old lines
            old_lines = BudgetLine.query().filter(budget_id=budget.id).all()
            for line in old_lines:
                line.delete(soft=False)
        else:
            budget = Budget(
                fiscal_year=fiscal_year,
                department=department,
                total_allocated=total_allocated,
                total_spent=0.0,
                status="Active"
            )
            budget.save()

        # Write lines
        for acc_id, amount in allocations.items():
            line = BudgetLine(
                budget_id=budget.id,
                account=acc_id,
                allocated=amount,
                actual=0.0,
                variance=amount
            )
            line.save()

        return budget.to_dict()

    def check_budget_exceeded(self, account_id: str, new_expense_amount: float) -> bool:
        """Check if an expense allocation will exceed the budget limits. Raises warning but does not block."""
        lines = BudgetLine.query().filter(account=account_id).all()
        for line in lines:
            budget = Budget.get(line.budget_id)
            if budget and budget.status == "Active":
                allocated = line.allocated
                projected = line.actual + new_expense_amount
                if projected > allocated:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"⚠️ BUDGET EXCEEDED: Posting of ${new_expense_amount:.2f} on account '{account_id}' "
                        f"exceeds allocated limit of ${allocated:.2f} (Current Spent: ${line.actual:.2f})."
                    )
                    return True
        return False

    def _update_budget_actual(self, account_id: str, debit_amount: float) -> None:
        """Update actual values inside the Budget system post GL entry validation."""
        lines = BudgetLine.query().filter(account=account_id).all()
        for line in lines:
            budget = Budget.get(line.budget_id)
            if budget and budget.status == "Active":
                # Increment actual spend
                line._values["actual"] += debit_amount
                line._values["variance"] = line.allocated - line.actual
                line.save()

                budget._values["total_spent"] += debit_amount
                budget.save()

    # ── Utility Helpers ───────────────────────────────────────────────────────

    def _find_or_create_default_account(self, name: str, account_type: str, root_type: str) -> Account:
        """Find an existing account by name, or create it automatically."""
        existing = Account.query().filter(name=name).first()
        if existing:
            return existing
        acc = Account(
            name=name,
            account_type=account_type,
            root_type=root_type,
            balance=0.0,
            currency="USD",
            is_group=False
        )
        acc.save()
        return acc

    # ── Asset Management & Depreciation ───────────────────────────────────────

    def register_asset(
        self,
        name: str,
        category: str = "Equipment",
        value: float = 0.0,
        method: str = "Straight Line",
        life_years: int = 5,
        cost_center: Optional[str] = None,
        asset_account_id: Optional[str] = None,
        dep_account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Register a new capital asset in the fixed assets registry.

        GL Postings (if applicable - sets starting asset values):
          Debit: Fixed Asset Account (Asset)
          Credit: Operating Bank Account / Equity (Funding Source)
        """
        # If accounts aren't specified, resolve default ones
        if not asset_account_id:
            asset_acc = self._find_or_create_default_account(f"Fixed Asset - {category}", "Asset", "Asset")
            asset_account_id = asset_acc.id
        if not dep_account_id:
            dep_acc = self._find_or_create_default_account("Depreciation Expense", "Depreciation", "Expense")
            dep_account_id = dep_acc.id

        asset = Asset(
            asset_name=name,
            asset_category=category,
            purchase_date=datetime.utcnow().strftime("%Y-%m-%d"),
            purchase_value=value,
            current_value=value,
            depreciation_method=method,
            useful_life_years=life_years,
            status="Active",
            cost_center=cost_center,
            asset_account=asset_account_id,
            depreciation_account=dep_account_id
        )
        asset.save()

        # Post the asset purchase to the ledger
        bank_acc = self._find_or_create_default_account("Operating Bank Account", "Bank", "Asset")
        self.post_journal_entry(
            lines=[
                {"account": asset_account_id, "debit": value, "credit": 0.0, "cost_center": cost_center},
                {"account": bank_acc.id, "debit": 0.0, "credit": value}
            ],
            narration=f"Purchased Fixed Asset: {name}",
            entry_type="Journal Entry",
            reference_type="Asset",
            reference_id=asset.id
        )

        return asset.to_dict()

    def compute_depreciation(self, asset_id: str) -> Dict[str, Any]:
        """Compute and post annual depreciation for an asset.

        GL Postings:
          Debit: Depreciation Expense (Expense)
          Credit: Accumulated Depreciation (Asset/Liability offset)
        """
        asset = Asset.get(asset_id)
        if not asset:
            raise ValueError(f"Asset '{asset_id}' not found.")
        if asset.status != "Active":
            raise ValueError(f"Asset '{asset_id}' is not currently active.")

        # Heuristic calculations
        val = asset.purchase_value
        years = asset.useful_life_years
        method = asset.depreciation_method

        # Fetch previous depreciations to compute accum
        prev_dep = AssetDepreciation.query().filter(asset_id=asset_id).all()
        accum = sum(d.depreciation_amount for d in prev_dep)

        if accum >= val:
            asset._values["status"] = "Retired"
            asset.save()
            return {"status": "fully_depreciated", "asset": asset.asset_name}

        if method == "Straight Line":
            dep_amount = val / float(years)
        else:
            # Declining balance (double declining rate of 40% per annum for simple model)
            dep_amount = (val - accum) * 0.40

        # Safety cap
        if accum + dep_amount > val:
            dep_amount = val - accum

        accum += dep_amount
        rem_value = val - accum

        posting_date = datetime.utcnow().strftime("%Y-%m-%d")

        # Save schedule details
        schedule = AssetDepreciation(
            asset_id=asset_id,
            posting_date=posting_date,
            depreciation_amount=dep_amount,
            accumulated_depreciation=accum,
            remaining_value=rem_value
        )
        schedule.save()

        # Update Asset current value
        asset._values["current_value"] = rem_value
        if rem_value <= 0.01:
            asset._values["status"] = "Retired"
        asset.save()

        # Post depreciation to General Ledger
        accum_dep_acc = self._find_or_create_default_account("Accumulated Depreciation", "Asset", "Asset")
        self.post_journal_entry(
            lines=[
                {"account": asset.depreciation_account, "debit": dep_amount, "credit": 0.0, "cost_center": asset.cost_center},
                {"account": accum_dep_acc.id, "debit": 0.0, "credit": dep_amount}
            ],
            narration=f"Depreciation expense posting for asset '{asset.asset_name}'",
            entry_type="Depreciation",
            reference_type="AssetDepreciation",
            reference_id=schedule.id
        )

        return {
            "asset_id": asset_id,
            "asset_name": asset.asset_name,
            "depreciation_amount": dep_amount,
            "accumulated_depreciation": accum,
            "remaining_value": rem_value
        }

    def get_asset_register(self) -> List[Dict[str, Any]]:
        """List all registered assets in the system."""
        assets = Asset.query().all()
        return [a.to_dict() for a in assets]

    def get_depreciation_schedule(self, asset_id: str) -> List[Dict[str, Any]]:
        """List all posted depreciation schedule records for an asset."""
        deps = AssetDepreciation.query().filter(asset_id=asset_id).all()
        return [d.to_dict() for d in deps]

    # ── Credit Notes & Debit Notes (Returns) ─────────────────────────────────

    def create_credit_note(
        self,
        customer: str,
        original_invoice_id: str,
        items: List[Dict[str, Any]],
        reason: str = "Goods returned",
        tax_rate_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Issue a credit note (sales return) reversing part/all of a sales invoice.

        GL Postings:
          Debit: Sales Revenue (Revenue reversal)
          Credit: Accounts Receivable (AR reduction)
        """
        posting_date = datetime.utcnow().strftime("%Y-%m-%d")
        original = SalesInvoice.get(original_invoice_id)
        if not original:
            raise ValueError(f"Original Sales Invoice '{original_invoice_id}' not found.")

        net_total = sum(float(i.get("qty", 0)) * float(i.get("rate", 0)) for i in items)
        tax_amount = 0.0
        if tax_rate_id:
            tax = TaxRate.get(tax_rate_id)
            if tax:
                tax_amount = net_total * (tax.rate_percent / 100.0)
        grand_total = net_total + tax_amount

        cn = CreditNote(
            original_invoice_id=original_invoice_id,
            customer=customer,
            posting_date=posting_date,
            items_json=json.dumps(items),
            net_total=net_total,
            tax_total=tax_amount,
            grand_total=grand_total,
            reason=reason,
            status="Submitted"
        )
        cn.save()

        # Reduce outstanding on the original invoice
        original._values["outstanding"] = max(0.0, original.outstanding - grand_total)
        if original.outstanding <= 0.01:
            original._values["status"] = "Paid"
        original.save()

        # Reverse GL postings
        ar_acc = self._find_or_create_default_account("Accounts Receivable", "Receivable", "Asset")
        rev_acc = self._find_or_create_default_account("Sales Revenue", "Revenue", "Revenue")
        gl_lines = [
            {"account": rev_acc.id, "debit": net_total, "credit": 0.0},
            {"account": ar_acc.id, "debit": 0.0, "credit": grand_total, "party_type": "Customer", "party": customer}
        ]
        if tax_amount > 0:
            tax_acc = self._find_or_create_default_account("Sales Tax Payable", "Tax", "Liability")
            gl_lines.append({"account": tax_acc.id, "debit": tax_amount, "credit": 0.0})

        self.post_journal_entry(
            lines=gl_lines,
            narration=f"Credit Note #{cn.id} against Invoice #{original_invoice_id}: {reason}",
            entry_type="Journal Entry",
            reference_type="CreditNote",
            reference_id=cn.id
        )
        self._log_audit("CreditNote", cn.id, "Created", f"Credit note for ${grand_total:.2f}")
        return cn.to_dict()

    def create_debit_note(
        self,
        supplier: str,
        original_invoice_id: str,
        items: List[Dict[str, Any]],
        reason: str = "Goods returned to supplier",
        tax_rate_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Issue a debit note (purchase return) reversing part/all of a purchase invoice.

        GL Postings:
          Debit: Accounts Payable (AP reduction)
          Credit: Cost of Goods Sold / Expense (expense reversal)
        """
        posting_date = datetime.utcnow().strftime("%Y-%m-%d")
        original = PurchaseInvoice.get(original_invoice_id)
        if not original:
            raise ValueError(f"Original Purchase Invoice '{original_invoice_id}' not found.")

        net_total = sum(float(i.get("qty", 0)) * float(i.get("rate", 0)) for i in items)
        tax_amount = 0.0
        if tax_rate_id:
            tax = TaxRate.get(tax_rate_id)
            if tax:
                tax_amount = net_total * (tax.rate_percent / 100.0)
        grand_total = net_total + tax_amount

        dn = DebitNote(
            original_invoice_id=original_invoice_id,
            supplier=supplier,
            posting_date=posting_date,
            items_json=json.dumps(items),
            net_total=net_total,
            tax_total=tax_amount,
            grand_total=grand_total,
            reason=reason,
            status="Submitted"
        )
        dn.save()

        original._values["outstanding"] = max(0.0, original.outstanding - grand_total)
        if original.outstanding <= 0.01:
            original._values["status"] = "Paid"
        original.save()

        ap_acc = self._find_or_create_default_account("Accounts Payable", "Payable", "Liability")
        exp_acc = self._find_or_create_default_account("Cost of Goods Sold", "Cost of Goods Sold", "Expense")
        gl_lines = [
            {"account": ap_acc.id, "debit": grand_total, "credit": 0.0, "party_type": "Supplier", "party": supplier},
            {"account": exp_acc.id, "debit": 0.0, "credit": net_total}
        ]
        if tax_amount > 0:
            tax_acc = self._find_or_create_default_account("Purchase Tax Receivable", "Tax", "Asset")
            gl_lines.append({"account": tax_acc.id, "debit": 0.0, "credit": tax_amount})

        self.post_journal_entry(
            lines=gl_lines,
            narration=f"Debit Note #{dn.id} against Purchase #{original_invoice_id}: {reason}",
            entry_type="Journal Entry",
            reference_type="DebitNote",
            reference_id=dn.id
        )
        self._log_audit("DebitNote", dn.id, "Created", f"Debit note for ${grand_total:.2f}")
        return dn.to_dict()

    # ── AR/AP Aging Analysis ─────────────────────────────────────────────────

    def get_ar_aging(self) -> Dict[str, Any]:
        """Accounts Receivable aging breakdown in 30/60/90/120+ day buckets."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        invoices = SalesInvoice.query().all()

        buckets = {"current": 0.0, "1_30": 0.0, "31_60": 0.0, "61_90": 0.0, "91_120": 0.0, "over_120": 0.0}
        details = []

        for inv in invoices:
            if inv.status not in ["Submitted", "Partly Paid"] or inv.outstanding <= 0.01:
                continue
            days = self._days_between(inv.posting_date, today)
            bucket = self._classify_aging_bucket(days)
            buckets[bucket] += inv.outstanding
            details.append({
                "customer": inv.customer,
                "invoice_id": inv.id,
                "posting_date": inv.posting_date,
                "outstanding": inv.outstanding,
                "days_overdue": days,
                "bucket": bucket
            })

        return {
            "as_of_date": today,
            "summary": buckets,
            "total_outstanding": sum(buckets.values()),
            "details": sorted(details, key=lambda x: -x["days_overdue"])
        }

    def get_ap_aging(self) -> Dict[str, Any]:
        """Accounts Payable aging breakdown in 30/60/90/120+ day buckets."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        invoices = PurchaseInvoice.query().all()

        buckets = {"current": 0.0, "1_30": 0.0, "31_60": 0.0, "61_90": 0.0, "91_120": 0.0, "over_120": 0.0}
        details = []

        for inv in invoices:
            if inv.status not in ["Submitted", "Partly Paid"] or inv.outstanding <= 0.01:
                continue
            days = self._days_between(inv.posting_date, today)
            bucket = self._classify_aging_bucket(days)
            buckets[bucket] += inv.outstanding
            details.append({
                "supplier": inv.supplier,
                "invoice_id": inv.id,
                "posting_date": inv.posting_date,
                "outstanding": inv.outstanding,
                "days_overdue": days,
                "bucket": bucket
            })

        return {
            "as_of_date": today,
            "summary": buckets,
            "total_outstanding": sum(buckets.values()),
            "details": sorted(details, key=lambda x: -x["days_overdue"])
        }

    # ── Customer & Supplier Ledgers ──────────────────────────────────────────

    def get_customer_ledger(self, customer: str) -> Dict[str, Any]:
        """Full transaction history for a specific customer."""
        invoices = [i.to_dict() for i in SalesInvoice.query().filter(customer=customer).all()]
        credit_notes = [c.to_dict() for c in CreditNote.query().filter(customer=customer).all()]
        payments = [p.to_dict() for p in Payment.query().filter(party=customer, party_type="Customer").all()]

        total_invoiced = sum(i.get("grand_total", 0) for i in invoices)
        total_returns = sum(c.get("grand_total", 0) for c in credit_notes)
        total_paid = sum(p.get("amount", 0) for p in payments)
        outstanding = total_invoiced - total_returns - total_paid

        return {
            "customer": customer,
            "total_invoiced": total_invoiced,
            "total_returns": total_returns,
            "total_paid": total_paid,
            "outstanding_balance": max(0.0, outstanding),
            "invoices": invoices,
            "credit_notes": credit_notes,
            "payments": payments
        }

    def get_supplier_ledger(self, supplier: str) -> Dict[str, Any]:
        """Full transaction history for a specific supplier."""
        invoices = [i.to_dict() for i in PurchaseInvoice.query().filter(supplier=supplier).all()]
        debit_notes = [d.to_dict() for d in DebitNote.query().filter(supplier=supplier).all()]
        payments = [p.to_dict() for p in Payment.query().filter(party=supplier, party_type="Supplier").all()]

        total_invoiced = sum(i.get("grand_total", 0) for i in invoices)
        total_returns = sum(d.get("grand_total", 0) for d in debit_notes)
        total_paid = sum(p.get("amount", 0) for p in payments)
        outstanding = total_invoiced - total_returns - total_paid

        return {
            "supplier": supplier,
            "total_invoiced": total_invoiced,
            "total_returns": total_returns,
            "total_paid": total_paid,
            "outstanding_balance": max(0.0, outstanding),
            "invoices": invoices,
            "debit_notes": debit_notes,
            "payments": payments
        }

    def get_customer_balance_summary(self) -> List[Dict[str, Any]]:
        """Summarized balance overview for all customers."""
        customers = set()
        for inv in SalesInvoice.query().all():
            customers.add(inv.customer)

        summaries = []
        for cust in sorted(customers):
            ledger = self.get_customer_ledger(cust)
            summaries.append({
                "customer": cust,
                "total_invoiced": ledger["total_invoiced"],
                "total_paid": ledger["total_paid"],
                "outstanding": ledger["outstanding_balance"]
            })
        return summaries

    def get_supplier_balance_summary(self) -> List[Dict[str, Any]]:
        """Summarized balance overview for all suppliers."""
        suppliers = set()
        for inv in PurchaseInvoice.query().all():
            suppliers.add(inv.supplier)

        summaries = []
        for sup in sorted(suppliers):
            ledger = self.get_supplier_ledger(sup)
            summaries.append({
                "supplier": sup,
                "total_invoiced": ledger["total_invoiced"],
                "total_paid": ledger["total_paid"],
                "outstanding": ledger["outstanding_balance"]
            })
        return summaries

    # ── Multi-Currency & Exchange Rates ───────────────────────────────────────

    def set_exchange_rate(
        self, from_currency: str, to_currency: str, rate: float, effective_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record or update a currency exchange rate."""
        date = effective_date or datetime.utcnow().strftime("%Y-%m-%d")
        er = ExchangeRate(
            from_currency=from_currency.upper(),
            to_currency=to_currency.upper(),
            rate=rate,
            effective_date=date
        )
        er.save()
        return er.to_dict()

    def convert_currency(self, amount: float, from_currency: str, to_currency: str) -> Dict[str, Any]:
        """Convert an amount using the latest exchange rate on file."""
        if from_currency.upper() == to_currency.upper():
            return {"amount": amount, "converted": amount, "rate": 1.0}

        rates = ExchangeRate.query().filter(
            from_currency=from_currency.upper(),
            to_currency=to_currency.upper()
        ).all()

        if not rates:
            # Try reverse lookup
            rates = ExchangeRate.query().filter(
                from_currency=to_currency.upper(),
                to_currency=from_currency.upper()
            ).all()
            if rates:
                latest = sorted(rates, key=lambda r: r.effective_date)[-1]
                rate = 1.0 / latest.rate
            else:
                raise ValueError(f"No exchange rate found for {from_currency} → {to_currency}")
        else:
            latest = sorted(rates, key=lambda r: r.effective_date)[-1]
            rate = latest.rate

        converted = amount * rate
        return {"amount": amount, "converted": round(converted, 2), "rate": rate,
                "from": from_currency, "to": to_currency}

    def get_exchange_rates(self) -> List[Dict[str, Any]]:
        """List all exchange rates on file."""
        return [er.to_dict() for er in ExchangeRate.query().all()]

    # ── Cheque Management ────────────────────────────────────────────────────

    def issue_cheque(
        self,
        party_type: str,
        party: str,
        amount: float,
        bank_account_id: str,
        cheque_number: str,
        cheque_date: Optional[str] = None,
        direction: str = "Outgoing"
    ) -> Dict[str, Any]:
        """Issue a new cheque for payment."""
        date = cheque_date or datetime.utcnow().strftime("%Y-%m-%d")
        cheque = ChequeEntry(
            cheque_number=cheque_number,
            party_type=party_type,
            party=party,
            amount=amount,
            bank_account=bank_account_id,
            cheque_date=date,
            status="Issued",
            direction=direction
        )
        cheque.save()
        self._log_audit("ChequeEntry", cheque.id, "Created", f"Cheque #{cheque_number} for ${amount:.2f}")
        return cheque.to_dict()

    def clear_cheque(self, cheque_id: str) -> Dict[str, Any]:
        """Mark a cheque as cleared and update bank balances."""
        cheque = ChequeEntry.get(cheque_id)
        if not cheque:
            raise ValueError(f"Cheque '{cheque_id}' not found.")
        if cheque.status != "Issued":
            raise ValueError(f"Cheque is already {cheque.status}.")

        cheque._values["status"] = "Cleared"
        cheque._values["clearance_date"] = datetime.utcnow().strftime("%Y-%m-%d")
        cheque.save()

        bank = BankAccount.get(cheque.bank_account)
        if bank:
            if cheque.direction == "Outgoing":
                bank._values["balance"] -= cheque.amount
            else:
                bank._values["balance"] += cheque.amount
            bank.save()

        self._log_audit("ChequeEntry", cheque_id, "Updated", f"Cheque cleared on {cheque.clearance_date}")
        return cheque.to_dict()

    def bounce_cheque(self, cheque_id: str) -> Dict[str, Any]:
        """Mark a cheque as bounced and reverse any impact."""
        cheque = ChequeEntry.get(cheque_id)
        if not cheque:
            raise ValueError(f"Cheque '{cheque_id}' not found.")

        was_cleared = cheque.status == "Cleared"
        cheque._values["status"] = "Bounced"
        cheque.save()

        # Reverse bank impact if it was already cleared
        if was_cleared:
            bank = BankAccount.get(cheque.bank_account)
            if bank:
                if cheque.direction == "Outgoing":
                    bank._values["balance"] += cheque.amount
                else:
                    bank._values["balance"] -= cheque.amount
                bank.save()

        self._log_audit("ChequeEntry", cheque_id, "Updated", f"Cheque bounced — amount reversed")
        return cheque.to_dict()

    def get_cheque_register(self, bank_account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all cheques, optionally filtered by bank account."""
        if bank_account_id:
            cheques = ChequeEntry.query().filter(bank_account=bank_account_id).all()
        else:
            cheques = ChequeEntry.query().all()
        return [c.to_dict() for c in cheques]

    def get_bank_clearance_status(self) -> List[Dict[str, Any]]:
        """List all uncleared cheques pending bank clearance."""
        cheques = ChequeEntry.query().filter(status="Issued").all()
        return [{
            "cheque_id": c.id,
            "cheque_number": c.cheque_number,
            "party": c.party,
            "amount": c.amount,
            "cheque_date": c.cheque_date,
            "direction": c.direction
        } for c in cheques]

    # ── Subscriptions & Recurring Entries ────────────────────────────────────

    def create_subscription(
        self,
        customer: str,
        plan_name: str,
        amount: float,
        frequency: str = "Monthly",
        start_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a recurring billing subscription for a customer."""
        date = start_date or datetime.utcnow().strftime("%Y-%m-%d")
        sub = Subscription(
            customer=customer,
            plan_name=plan_name,
            amount=amount,
            frequency=frequency,
            start_date=date,
            next_invoice_date=date,
            status="Active",
            invoices_generated=0,
            total_billed=0.0
        )
        sub.save()
        return sub.to_dict()

    def process_subscriptions(self) -> Dict[str, Any]:
        """Process all due subscriptions and generate invoices."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        subs = Subscription.query().filter(status="Active").all()
        generated = []

        for sub in subs:
            if sub.next_invoice_date <= today:
                # Generate invoice
                inv = self.create_sales_invoice(
                    customer=sub.customer,
                    items=[{"qty": 1, "rate": sub.amount, "description": f"Subscription: {sub.plan_name}"}]
                )
                generated.append({"subscription_id": sub.id, "invoice_id": inv["id"]})

                sub._values["invoices_generated"] += 1
                sub._values["total_billed"] += sub.amount
                sub._values["next_invoice_date"] = self._advance_date(sub.next_invoice_date, sub.frequency)
                sub.save()

        return {"processed": len(generated), "invoices": generated}

    def cancel_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Cancel an active subscription."""
        sub = Subscription.get(subscription_id)
        if not sub:
            raise ValueError(f"Subscription '{subscription_id}' not found.")
        sub._values["status"] = "Cancelled"
        sub.save()
        return sub.to_dict()

    def create_recurring_entry(
        self,
        narration: str,
        lines: List[Dict[str, Any]],
        frequency: str = "Monthly",
        start_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a template for auto-repeat journal entries (rent, salaries, etc.)."""
        date = start_date or datetime.utcnow().strftime("%Y-%m-%d")
        re = RecurringEntry(
            template_narration=narration,
            lines_json=json.dumps(lines),
            frequency=frequency,
            next_posting_date=date,
            is_active=True,
            times_posted=0
        )
        re.save()
        return re.to_dict()

    def process_recurring_entries(self) -> Dict[str, Any]:
        """Post all pending recurring journal entries that are due."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        entries = RecurringEntry.query().filter(is_active=True).all()
        posted = []

        for entry in entries:
            if entry.next_posting_date <= today:
                lines = json.loads(entry.lines_json)
                je = self.post_journal_entry(
                    lines=lines,
                    narration=f"[Recurring] {entry.template_narration}",
                    posting_date=today
                )
                posted.append({"recurring_id": entry.id, "journal_entry_id": je["id"]})

                entry._values["times_posted"] += 1
                entry._values["last_posted_date"] = today
                entry._values["next_posting_date"] = self._advance_date(today, entry.frequency)
                entry.save()

        return {"processed": len(posted), "entries": posted}

    # ── Credit Limits & Dunning ──────────────────────────────────────────────

    def set_credit_limit(self, customer: str, limit: float, bypass: bool = False) -> Dict[str, Any]:
        """Set or update a customer's credit ceiling."""
        existing = CreditLimit.query().filter(customer=customer).first()
        if existing:
            existing._values["credit_limit"] = limit
            existing._values["bypass_credit_limit"] = bypass
            existing.save()
            return existing.to_dict()

        cl = CreditLimit(customer=customer, credit_limit=limit, bypass_credit_limit=bypass)
        cl.save()
        return cl.to_dict()

    def check_credit_limit(self, customer: str, new_amount: float) -> Dict[str, Any]:
        """Check if a new transaction exceeds a customer's credit limit."""
        cl = CreditLimit.query().filter(customer=customer).first()
        if not cl:
            return {"customer": customer, "limit": None, "status": "no_limit_set", "allowed": True}
        if cl.bypass_credit_limit:
            return {"customer": customer, "limit": cl.credit_limit, "status": "bypass", "allowed": True}

        ledger = self.get_customer_ledger(customer)
        current_exposure = ledger["outstanding_balance"] + new_amount
        allowed = current_exposure <= cl.credit_limit

        return {
            "customer": customer,
            "credit_limit": cl.credit_limit,
            "current_outstanding": ledger["outstanding_balance"],
            "new_amount": new_amount,
            "projected_exposure": current_exposure,
            "status": "within_limit" if allowed else "EXCEEDED",
            "allowed": allowed
        }

    def generate_dunning(self, customer: Optional[str] = None) -> List[Dict[str, Any]]:
        """Generate dunning/payment reminder notices for overdue invoices."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        invoices = SalesInvoice.query().all()
        notices = []

        for inv in invoices:
            if inv.status not in ["Submitted", "Partly Paid"] or inv.outstanding <= 0.01:
                continue
            if customer and inv.customer != customer:
                continue

            days = self._days_between(inv.posting_date, today)
            if days < 1:
                continue

            # Determine dunning level
            if days > 120:
                level = "Legal"
            elif days > 90:
                level = "Final Notice"
            elif days > 60:
                level = "Warning"
            else:
                level = "Reminder"

            notice = DunningNotice(
                customer=inv.customer,
                invoice_id=inv.id,
                dunning_date=today,
                outstanding_amount=inv.outstanding,
                days_overdue=days,
                dunning_level=level,
                status="Sent"
            )
            notice.save()
            notices.append(notice.to_dict())

        return notices

    # ── Bad Debt Write-Off ───────────────────────────────────────────────────

    def write_off_bad_debt(self, invoice_id: str, amount: Optional[float] = None) -> Dict[str, Any]:
        """Write off uncollectible customer debt against a sales invoice.

        GL Postings:
          Debit: Bad Debt Expense (Expense)
          Credit: Accounts Receivable (Asset)
        """
        inv = SalesInvoice.get(invoice_id)
        if not inv:
            raise ValueError(f"Sales Invoice '{invoice_id}' not found.")

        write_off_amount = amount or inv.outstanding
        if write_off_amount > inv.outstanding:
            write_off_amount = inv.outstanding

        bad_debt_acc = self._find_or_create_default_account("Bad Debt Expense", "Expense", "Expense")
        ar_acc = self._find_or_create_default_account("Accounts Receivable", "Receivable", "Asset")

        self.post_journal_entry(
            lines=[
                {"account": bad_debt_acc.id, "debit": write_off_amount, "credit": 0.0},
                {"account": ar_acc.id, "debit": 0.0, "credit": write_off_amount, "party_type": "Customer", "party": inv.customer}
            ],
            narration=f"Bad debt write-off for Invoice #{invoice_id}, customer: {inv.customer}",
            reference_type="SalesInvoice",
            reference_id=invoice_id
        )

        inv._values["outstanding"] = max(0.0, inv.outstanding - write_off_amount)
        if inv.outstanding <= 0.01:
            inv._values["status"] = "Paid"
        inv.save()

        self._log_audit("SalesInvoice", invoice_id, "Updated", f"Bad debt write-off of ${write_off_amount:.2f}")
        return {"invoice_id": invoice_id, "amount_written_off": write_off_amount, "remaining_outstanding": inv.outstanding}

    # ── Period Closing ───────────────────────────────────────────────────────

    def close_fiscal_period(self, fiscal_year_id: str) -> Dict[str, Any]:
        """Close a fiscal period by transferring P&L balances to Retained Earnings.

        GL Postings:
          Debit: All Revenue accounts (zeroed)
          Credit: Retained Earnings
          Debit: Retained Earnings
          Credit: All Expense accounts (zeroed)
        """
        fy = FiscalYear.get(fiscal_year_id)
        if not fy:
            raise ValueError(f"Fiscal Year '{fiscal_year_id}' not found.")
        if fy.is_closed:
            raise ValueError(f"Fiscal Year '{fy.year_name}' is already closed.")

        retained_acc = self._find_or_create_default_account("Retained Earnings", "Equity", "Equity")

        accounts = Account.query().all()
        total_revenue = 0.0
        total_expense = 0.0

        closing_lines = []
        for acc in accounts:
            if acc.is_group:
                continue
            balance = self.get_account_balance(acc.id, as_of_date=fy.end_date)
            if acc.root_type == "Revenue" and balance > 0:
                total_revenue += balance
                closing_lines.append({"account": acc.id, "debit": balance, "credit": 0.0})
            elif acc.root_type == "Expense" and balance > 0:
                total_expense += balance
                closing_lines.append({"account": acc.id, "debit": 0.0, "credit": balance})

        net_pl = total_revenue - total_expense
        if net_pl >= 0:
            closing_lines.append({"account": retained_acc.id, "debit": 0.0, "credit": net_pl})
        else:
            closing_lines.append({"account": retained_acc.id, "debit": abs(net_pl), "credit": 0.0})

        if closing_lines:
            self.post_journal_entry(
                lines=closing_lines,
                narration=f"Period Closing Voucher for FY {fy.year_name}",
                posting_date=fy.end_date,
                entry_type="Journal Entry",
                reference_type="PeriodClosing",
                reference_id=fiscal_year_id
            )

        pc = PeriodClosing(
            fiscal_year=fiscal_year_id,
            closing_date=fy.end_date,
            closing_account=retained_acc.id,
            net_pl_amount=net_pl,
            status="Submitted"
        )
        pc.save()

        fy._values["is_closed"] = True
        fy.save()

        self._log_audit("FiscalYear", fiscal_year_id, "Submitted", f"Period closed. Net P&L: ${net_pl:.2f}")
        return {
            "fiscal_year": fy.year_name,
            "net_profit_loss": net_pl,
            "total_revenue_closed": total_revenue,
            "total_expense_closed": total_expense,
            "closing_voucher_id": pc.id
        }

    def set_opening_balances(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Set opening balances for accounts at the start of a new fiscal period.

        entries: [{"account_id": "...", "debit": 100.0, "credit": 0.0}, ...]
        """
        posted = self.post_journal_entry(
            lines=entries,
            narration="Opening Balance Entry",
            entry_type="Opening"
        )
        return {"status": "success", "journal_entry": posted}

    # ── Tax Return Summaries ─────────────────────────────────────────────────

    def get_tax_summary(self, from_date: str, to_date: str) -> Dict[str, Any]:
        """Summarize tax collected (output VAT/sales tax) and tax paid (input VAT) for a period."""
        sales_tax_acc = self._find_or_create_default_account("Sales Tax Payable", "Tax", "Liability")
        purchase_tax_acc = self._find_or_create_default_account("Purchase Tax Receivable", "Tax", "Asset")

        output_tax = 0.0
        input_tax = 0.0

        lines = JournalEntryLine.query().all()
        for line in lines:
            je = JournalEntry.get(line.journal_entry_id)
            if not je or je.status != "Submitted":
                continue
            if je.posting_date < from_date or je.posting_date > to_date:
                continue

            if line.account == sales_tax_acc.id:
                output_tax += line.credit - line.debit
            elif line.account == purchase_tax_acc.id:
                input_tax += line.debit - line.credit

        net_tax = output_tax - input_tax

        return {
            "from_date": from_date,
            "to_date": to_date,
            "output_tax_collected": output_tax,
            "input_tax_paid": input_tax,
            "net_tax_payable": net_tax if net_tax > 0 else 0.0,
            "net_tax_refundable": abs(net_tax) if net_tax < 0 else 0.0
        }

    # ── Costing & Profitability ──────────────────────────────────────────────

    def get_cost_center_profitability(self, cost_center_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Calculate revenue and expenses allocated to each cost center."""
        cost_centers = []
        if cost_center_id:
            cc = CostCenter.get(cost_center_id)
            if cc:
                cost_centers = [cc]
        else:
            cost_centers = CostCenter.query().all()

        results = []
        for cc in cost_centers:
            lines = JournalEntryLine.query().filter(cost_center=cc.id).all()
            revenue = 0.0
            expense = 0.0

            for line in lines:
                je = JournalEntry.get(line.journal_entry_id)
                if not je or je.status != "Submitted":
                    continue
                acc = Account.get(line.account)
                if not acc:
                    continue
                if acc.root_type == "Revenue":
                    revenue += line.credit - line.debit
                elif acc.root_type == "Expense":
                    expense += line.debit - line.credit

            results.append({
                "cost_center_id": cc.id,
                "cost_center_name": cc.name,
                "revenue": revenue,
                "expense": expense,
                "profit": revenue - expense,
                "margin_pct": ((revenue - expense) / revenue * 100.0) if revenue > 0 else 0.0
            })
        return results

    def get_gross_profit_by_customer(self) -> List[Dict[str, Any]]:
        """Calculate gross profit breakdown by customer."""
        customers = set()
        for inv in SalesInvoice.query().all():
            customers.add(inv.customer)

        results = []
        for cust in sorted(customers):
            invoices = SalesInvoice.query().filter(customer=cust).all()
            revenue = sum(i.net_total for i in invoices)
            # Estimate COGS as a proportion (simplified — no item-level cost tracking yet)
            cogs = sum(i.grand_total - i.net_total for i in invoices)  # tax is not COGS
            gp = revenue - cogs
            results.append({
                "customer": cust,
                "revenue": revenue,
                "cogs": 0.0,  # Placeholder — requires item-level costing
                "gross_profit": revenue,
                "gp_margin_pct": 100.0  # Full margin until COGS is tracked
            })
        return results

    # ── Cash Flow Forecasting ────────────────────────────────────────────────

    def forecast_cash_flow(self, days_ahead: int = 90) -> Dict[str, Any]:
        """Project future cash position based on receivables, payables, and subscriptions."""
        today = datetime.utcnow().strftime("%Y-%m-%d")

        # Current cash position
        accounts = Account.query().all()
        current_cash = sum(a.balance for a in accounts if a.account_type in ["Bank", "Cash"])

        # Expected inflows (AR outstanding)
        ar = sum(i.outstanding for i in SalesInvoice.query().all()
                 if i.status in ["Submitted", "Partly Paid"])

        # Expected outflows (AP outstanding)
        ap = sum(i.outstanding for i in PurchaseInvoice.query().all()
                 if i.status in ["Submitted", "Partly Paid"])

        # Subscription income expected
        subs = Subscription.query().filter(status="Active").all()
        sub_income = 0.0
        for sub in subs:
            cycles = self._estimate_cycles_in_days(sub.frequency, days_ahead)
            sub_income += sub.amount * cycles

        # Recurring expense outflows
        recurring = RecurringEntry.query().filter(is_active=True).all()
        recurring_expense = 0.0
        for entry in recurring:
            lines = json.loads(entry.lines_json)
            total_debit = sum(float(l.get("debit", 0)) for l in lines)
            cycles = self._estimate_cycles_in_days(entry.frequency, days_ahead)
            recurring_expense += total_debit * cycles

        # Uncleared cheques
        uncleared_out = sum(c.amount for c in ChequeEntry.query().filter(status="Issued", direction="Outgoing").all())
        uncleared_in = sum(c.amount for c in ChequeEntry.query().filter(status="Issued", direction="Incoming").all())

        projected = current_cash + ar + sub_income + uncleared_in - ap - recurring_expense - uncleared_out

        return {
            "as_of_date": today,
            "forecast_days": days_ahead,
            "current_cash": current_cash,
            "expected_inflows": {
                "accounts_receivable": ar,
                "subscription_income": sub_income,
                "uncleared_incoming_cheques": uncleared_in,
                "total": ar + sub_income + uncleared_in
            },
            "expected_outflows": {
                "accounts_payable": ap,
                "recurring_expenses": recurring_expense,
                "uncleared_outgoing_cheques": uncleared_out,
                "total": ap + recurring_expense + uncleared_out
            },
            "projected_cash_position": projected,
            "runway_status": "Healthy" if projected > 0 else "CASH SHORTFALL PREDICTED"
        }

    # ── Audit Trail ──────────────────────────────────────────────────────────

    def get_audit_trail(self, entity_type: Optional[str] = None, entity_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve the immutable audit log for financial entities."""
        if entity_type and entity_id:
            logs = AuditLog.query().filter(entity_type=entity_type, entity_id=entity_id).all()
        elif entity_type:
            logs = AuditLog.query().filter(entity_type=entity_type).all()
        else:
            logs = AuditLog.query().all()
        return [l.to_dict() for l in logs]

    def verify_gl_integrity(self) -> Dict[str, Any]:
        """Verify the general ledger is balanced: total debits must equal total credits."""
        entries = JournalEntry.query().filter(status="Submitted").all()
        total_debits = 0.0
        total_credits = 0.0
        issues = []

        for je in entries:
            lines = JournalEntryLine.query().filter(journal_entry_id=je.id).all()
            je_debit = sum(l.debit for l in lines)
            je_credit = sum(l.credit for l in lines)

            total_debits += je_debit
            total_credits += je_credit

            if abs(je_debit - je_credit) > 0.001:
                issues.append({
                    "journal_entry_id": je.id,
                    "posting_date": je.posting_date,
                    "debit": je_debit,
                    "credit": je_credit,
                    "difference": je_debit - je_credit
                })

        return {
            "total_debits": total_debits,
            "total_credits": total_credits,
            "difference": total_debits - total_credits,
            "is_balanced": abs(total_debits - total_credits) < 0.01,
            "unbalanced_entries": issues,
            "total_entries_checked": len(entries)
        }

    # ── Utility Helpers (Extended) ───────────────────────────────────────────

    def _log_audit(self, entity_type: str, entity_id: str, action: str, details: str = "") -> None:
        """Write an immutable audit trail entry."""
        log = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            user="system",
            details=details
        )
        log.save()

    def _days_between(self, date_str1: str, date_str2: str) -> int:
        """Calculate days between two ISO date strings."""
        try:
            d1 = datetime.strptime(date_str1[:10], "%Y-%m-%d")
            d2 = datetime.strptime(date_str2[:10], "%Y-%m-%d")
            return abs((d2 - d1).days)
        except (ValueError, TypeError):
            return 0

    def _classify_aging_bucket(self, days: int) -> str:
        """Map day count to aging bucket label."""
        if days <= 0:
            return "current"
        elif days <= 30:
            return "1_30"
        elif days <= 60:
            return "31_60"
        elif days <= 90:
            return "61_90"
        elif days <= 120:
            return "91_120"
        else:
            return "over_120"

    def _advance_date(self, date_str: str, frequency: str) -> str:
        """Advance a date by the specified frequency interval."""
        from datetime import timedelta
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")

        freq_map = {"Monthly": 30, "Quarterly": 90, "Semi-Annual": 180, "Annual": 365}
        days_to_add = freq_map.get(frequency, 30)
        new_date = d + timedelta(days=days_to_add)
        return new_date.strftime("%Y-%m-%d")

    def _estimate_cycles_in_days(self, frequency: str, days: int) -> int:
        """Estimate how many billing/posting cycles fit in a given time span."""
        freq_map = {"Monthly": 30, "Quarterly": 90, "Semi-Annual": 180, "Annual": 365}
        cycle_days = freq_map.get(frequency, 30)
        return max(1, days // cycle_days)

