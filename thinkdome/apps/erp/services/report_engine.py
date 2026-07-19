"""Financial Report Engine.

Generates standard financial statements (P&L, Balance Sheet, Cash Flow) and computed
decision-support reports like ratios, dashboard metrics, and overall health scores.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

from thinkdome.apps.erp.models.accounting import (
    Account,
    JournalEntry,
    JournalEntryLine,
    BankAccount,
    SalesInvoice,
    PurchaseInvoice,
    Budget,
)
from thinkdome.apps.erp.services.accounting_service import AccountingService


class ReportEngine:
    """Calculates and aggregates general ledger balances into executive-ready reports."""

    def __init__(self, accounting_service: Optional[AccountingService] = None) -> None:
        self.accounting_service = accounting_service or AccountingService()

    def profit_and_loss(self, from_date: str, to_date: str) -> Dict[str, Any]:
        """Generate Profit and Loss Statement (Revenue - Expenses = Net Profit)."""
        accounts = Account.query().all()

        revenue_items = []
        expense_items = []

        total_revenue = 0.0
        total_expense = 0.0

        for acc in accounts:
            if acc.is_group:
                continue

            # Compute balance within the time window
            balance = self._get_account_period_balance(acc.id, from_date, to_date)

            if acc.root_type == "Revenue":
                total_revenue += balance
                revenue_items.append({
                    "account_id": acc.id,
                    "account_name": acc.name,
                    "balance": balance
                })
            elif acc.root_type == "Expense":
                total_expense += balance
                expense_items.append({
                    "account_id": acc.id,
                    "account_name": acc.name,
                    "balance": balance
                })

        net_profit = total_revenue - total_expense

        return {
            "from_date": from_date,
            "to_date": to_date,
            "revenue": {
                "items": revenue_items,
                "total": total_revenue
            },
            "expense": {
                "items": expense_items,
                "total": total_expense
            },
            "net_profit": net_profit,
            "profit_margin_pct": (net_profit / total_revenue * 100.0) if total_revenue > 0.0 else 0.0
        }

    def balance_sheet(self, as_of_date: str) -> Dict[str, Any]:
        """Generate Balance Sheet Statement (Assets = Liabilities + Equity)."""
        accounts = Account.query().all()

        asset_items = []
        liability_items = []
        equity_items = []

        total_assets = 0.0
        total_liabilities = 0.0
        total_equity = 0.0

        for acc in accounts:
            if acc.is_group:
                continue

            balance = self.accounting_service.get_account_balance(acc.id, as_of_date)

            if acc.root_type == "Asset":
                total_assets += balance
                asset_items.append({
                    "account_id": acc.id,
                    "account_name": acc.name,
                    "balance": balance
                })
            elif acc.root_type == "Liability":
                total_liabilities += balance
                liability_items.append({
                    "account_id": acc.id,
                    "account_name": acc.name,
                    "balance": balance
                })
            elif acc.root_type == "Equity":
                total_equity += balance
                equity_items.append({
                    "account_id": acc.id,
                    "account_name": acc.name,
                    "balance": balance
                })

        # Calculate current net income/profit to close out retained earnings in equity side
        # P&L calculation from start of year or inception up to as_of_date
        # For simplicity, we look at the difference Assets - Liabilities - Equity
        retained_earnings_balancing = total_assets - (total_liabilities + total_equity)
        if abs(retained_earnings_balancing) > 0.01:
            total_equity += retained_earnings_balancing
            equity_items.append({
                "account_id": "retained_earnings_derived",
                "account_name": "Retained Earnings (Derived)",
                "balance": retained_earnings_balancing
            })

        return {
            "as_of_date": as_of_date,
            "assets": {
                "items": asset_items,
                "total": total_assets
            },
            "liabilities": {
                "items": liability_items,
                "total": total_liabilities
            },
            "equity": {
                "items": equity_items,
                "total": total_equity
            },
            "total_liabilities_and_equity": total_liabilities + total_equity,
            "is_balanced": abs(total_assets - (total_liabilities + total_equity)) < 0.01
        }

    def cash_flow_statement(self, from_date: str, to_date: str) -> Dict[str, Any]:
        """Aggregate bank/cash journal ledger changes into cash flow statement."""
        # Query all submitted transactions affecting bank/cash accounts
        accounts = Account.query().all()
        bank_cash_ids = [acc.id for acc in accounts if acc.account_type in ["Bank", "Cash"]]

        operating_flow = 0.0
        investing_flow = 0.0
        financing_flow = 0.0

        gl_lines = JournalEntryLine.query().all()
        for line in gl_lines:
            if line.account in bank_cash_ids:
                je = JournalEntry.get(line.journal_entry_id)
                if not je or je.status != "Submitted":
                    continue
                if je.posting_date < from_date or je.posting_date > to_date:
                    continue

                # Cash impact: Debit increases cash, Credit decreases cash
                cash_change = line.debit - line.credit

                # Classify based on other accounts in same entry or default heuristics
                # For simplicity, look at narration keywords or default to operating
                narration = (je.narration or "").lower()
                if "equity" in narration or "loan" in narration or "financing" in narration:
                    financing_flow += cash_change
                elif "asset" in narration or "purchase asset" in narration or "invest" in narration:
                    investing_flow += cash_change
                else:
                    operating_flow += cash_change

        total_net_flow = operating_flow + investing_flow + financing_flow

        return {
            "from_date": from_date,
            "to_date": to_date,
            "operating_activities": operating_flow,
            "investing_activities": investing_flow,
            "financing_activities": financing_flow,
            "net_increase_in_cash": total_net_flow
        }

    def get_financial_ratios(self, as_of_date: str) -> Dict[str, Any]:
        """Calculate key financial ratios for solvency and profitability checks."""
        bs = self.balance_sheet(as_of_date)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        from_date = as_of_date[:4] + "-01-01"
        pl = self.profit_and_loss(from_date, as_of_date)

        # 1. Liquidity
        current_assets = sum(
            item["balance"] for item in bs["assets"]["items"]
            if Account.get(item["account_id"]).account_type in ["Bank", "Cash", "Receivable"]
        )
        current_liabilities = sum(
            item["balance"] for item in bs["liabilities"]["items"]
            if Account.get(item["account_id"]).account_type in ["Payable", "Tax"]
        )
        current_ratio = (current_assets / current_liabilities) if current_liabilities > 0.0 else 99.9

        # 2. Solvency
        total_debt = bs["liabilities"]["total"]
        total_equity = bs["equity"]["total"]
        debt_to_equity = (total_debt / total_equity) if total_equity > 0.0 else 0.0

        # 3. Profitability
        revenue = pl["revenue"]["total"]
        net_profit = pl["net_profit"]
        net_profit_margin = (net_profit / revenue * 100.0) if revenue > 0.0 else 0.0

        return {
            "as_of_date": as_of_date,
            "current_ratio": round(current_ratio, 2),
            "debt_to_equity": round(debt_to_equity, 2),
            "net_profit_margin_pct": round(net_profit_margin, 2),
            "liquidity_status": "Healthy" if current_ratio >= 1.5 else "Leaky Cash/Risk",
            "debt_status": "Leveraged" if debt_to_equity > 2.0 else "Stable"
        }

    def executive_dashboard(self) -> Dict[str, Any]:
        """Generate high-level real-time business performance KPI summaries."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        from_date = today[:4] + "-01-01"  # Year-to-date

        # Fetch financial indicators
        pl = self.profit_and_loss(from_date, today)
        bs = self.balance_sheet(today)

        # Calculate Cash Position
        cash_accounts = Account.query().all()
        cash_position = sum(acc.balance for acc in cash_accounts if acc.account_type in ["Bank", "Cash"])

        # Accounts Receivable and Payable
        ar_total = sum(inv.outstanding for inv in SalesInvoice.query().all() if inv.status in ["Submitted", "Partly Paid"])
        ap_total = sum(inv.outstanding for inv in PurchaseInvoice.query().all() if inv.status in ["Submitted", "Partly Paid"])

        # Headcount count placeholder (from stubs employee model)
        from thinkdome.apps.erp.models.stubs import Employee
        employee_count = len(Employee.query().all())

        return {
            "cash_position": cash_position,
            "ytd_revenue": pl["revenue"]["total"],
            "ytd_expense": pl["expense"]["total"],
            "ytd_net_profit": pl["net_profit"],
            "net_profit_margin_pct": pl["profit_margin_pct"],
            "outstanding_receivables": ar_total,
            "outstanding_payables": ap_total,
            "employee_count": employee_count if employee_count > 0 else "0 (HR not initialized)",
            "update_timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        }

    def company_health_score(self) -> Dict[str, Any]:
        """Aggregate metrics to calculate a corporate stability health index (0 to 100)."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        ratios = self.get_financial_ratios(today)
        db = self.executive_dashboard()

        # Score calculation parameters
        score = 60.0  # baseline

        # Profitability factor (weight: 30%)
        margin = ratios["net_profit_margin_pct"]
        if margin > 20:
            score += 25
        elif margin > 10:
            score += 15
        elif margin > 0:
            score += 5
        else:
            score -= 10

        # Liquidity factor (weight: 30%)
        cr = ratios["current_ratio"]
        if cr >= 1.8:
            score += 25
        elif cr >= 1.2:
            score += 15
        elif cr >= 0.8:
            score += 5
        else:
            score -= 15

        # Solvency debt-to-equity (weight: 20%)
        de = ratios["debt_to_equity"]
        if de < 0.5:
            score += 20
        elif de < 1.2:
            score += 10
        elif de > 2.0:
            score -= 15

        # Operating Cash position (weight: 20%)
        cash = db["cash_position"]
        if cash > 50000:
            score += 20
        elif cash > 10000:
            score += 10
        elif cash < 0:
            score -= 20

        final_score = max(0.0, min(100.0, score))

        # Classification label
        if final_score >= 85:
            label = "Excellent"
        elif final_score >= 70:
            label = "Stable/Good"
        elif final_score >= 50:
            label = "Caution/Average"
        else:
            label = "Critical Distress"

        return {
            "health_score": round(final_score, 1),
            "classification": label,
            "factors": {
                "profitability_margin": ratios["net_profit_margin_pct"],
                "current_ratio": ratios["current_ratio"],
                "debt_to_equity_ratio": ratios["debt_to_equity"],
                "cash_balance": cash
            }
        }

    # ── Heuristic Utilities ───────────────────────────────────────────────────

    def _get_account_period_balance(self, account_id: str, from_date: str, to_date: str) -> float:
        """Sum total net GL movement for a specific account within a date window."""
        lines = JournalEntryLine.query().filter(account=account_id).all()
        total_debit = 0.0
        total_credit = 0.0

        for line in lines:
            je = JournalEntry.get(line.journal_entry_id)
            if je and je.status == "Submitted":
                if from_date <= je.posting_date <= to_date:
                    total_debit += line.debit
                    total_credit += line.credit

        acc = Account.get(account_id)
        if acc and acc.root_type in ["Asset", "Expense"]:
            return total_debit - total_credit
        else:
            return total_credit - total_debit
