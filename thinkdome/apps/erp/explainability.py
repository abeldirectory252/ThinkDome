"""ERP Explainability and CEO Decision-Support Narrative Engine.

Translates complex ledger states, balances, and reports into clear, structured,
natural language executive summaries for the CEO.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

from thinkdome.apps.erp.services.accounting_service import AccountingService
from thinkdome.apps.erp.services.report_engine import ReportEngine


class ExplainabilityEngine:
    """Intelligent interpreter layer converting accounting data matrices into CEO narratives."""

    def __init__(
        self,
        accounting_service: Optional[AccountingService] = None,
        report_engine: Optional[ReportEngine] = None
    ) -> None:
        self.accounting_service = accounting_service or AccountingService()
        self.report_engine = report_engine or ReportEngine(self.accounting_service)

    def explain_for_ceo(self) -> str:
        """Provide a one-page natural language executive briefing of the company's financial status."""
        db = self.report_engine.executive_dashboard()
        hs = self.report_engine.company_health_score()

        cash = db["cash_position"]
        rev = db["ytd_revenue"]
        exp = db["ytd_expense"]
        profit = db["ytd_net_profit"]
        margin = db["net_profit_margin_pct"]
        ar = db["outstanding_receivables"]
        ap = db["outstanding_payables"]

        narrative = [
            "======================================================================",
            "                   EXECUTIVE FINANCIAL BRIEFING FOR CEO",
            "======================================================================",
            f"Generated: {db['update_timestamp']}",
            f"Company Financial Health Index: {hs['health_score']}/100 ({hs['classification'].upper()})",
            "----------------------------------------------------------------------",
            "1. LIQUIDITY & CAPITAL POSITION:",
            f"   - Cash Position: Your total liquid cash reserves stand at ${cash:,.2f}.",
            f"   - Accounts Receivable (AR): Outstanding customer invoices total ${ar:,.2f}.",
            f"   - Accounts Payable (AP): Pending supplier obligations total ${ap:,.2f}.",
            f"   - Quick Take: Your immediate net cash position (Cash + AR - AP) is ${cash + ar - ap:,.2f}.",
            "     " + self._get_cash_takeaway(cash, ar, ap),
            "",
            "2. YTD INCOME PERFORMANCE:",
            f"   - Revenue: Total sales booked this calendar year are ${rev:,.2f}.",
            f"   - Expenses: Operational costs consumed ${exp:,.2f}.",
            f"   - Net Profit: Bottom-line profitability stands at ${profit:,.2f}.",
            f"   - Operating Margin: Your current profit margin is {margin:.1f}%.",
            "     " + self._get_profitability_takeaway(margin, profit),
            "",
            "3. RECOMMENDATIONS & KEY ACTIONS:",
            self._get_action_recommendations(cash, ar, ap, margin),
            "======================================================================"
        ]

        return "\n".join(narrative)

    def explain_financial_health(self) -> str:
        """Provide a detailed breakdown narrative of the company's financial health score."""
        hs = self.report_engine.company_health_score()
        factors = hs["factors"]

        explanation = [
            f"Financial Health Classification: {hs['classification']} (Score: {hs['health_score']}/100)",
            "",
            "Health Indicator Breakdown:",
            f"1. Profitability (Margin: {factors['profitability_margin']:.1f}%):",
            "   " + self._explain_profitability_factor(factors["profitability_margin"]),
            "",
            f"2. Liquidity (Current Ratio: {factors['current_ratio']:.2f}):",
            "   " + self._explain_liquidity_factor(factors["current_ratio"]),
            "",
            f"3. Solvency (Debt-to-Equity Ratio: {factors['debt_to_equity_ratio']:.2f}):",
            "   " + self._explain_solvency_factor(factors["debt_to_equity_ratio"]),
            "",
            f"4. Cash Position (Cash Balance: ${factors['cash_balance']:,.2f}):",
            "   " + self._explain_cash_factor(factors["cash_balance"])
        ]
        return "\n".join(explanation)

    def explain_trend(self, metric: str, period: str = "monthly") -> str:
        """Explain the trajectory trend of a financial metric over time."""
        metric_norm = metric.lower().strip()
        db = self.report_engine.executive_dashboard()

        if "revenue" in metric_norm:
            val = db["ytd_revenue"]
            return (
                f"Revenue Trend Analysis ({period}):\n"
                f"Your Year-To-Date revenue of ${val:,.2f} indicates positive customer acquisition. "
                "To optimize growth, compare this period against last year's historical revenue. "
                "Maintaining an operating expense growth rate lower than your revenue growth is key to scaling."
            )
        elif "cash" in metric_norm or "bank" in metric_norm:
            val = db["cash_position"]
            return (
                f"Cash Reserves Trend Analysis ({period}):\n"
                f"Current cash balance is ${val:,.2f}. Cash reserves fluctuate with billing cycles. "
                "A steady upward trend is healthy. If cash is declining while revenue increases, "
                "it implies an collection cycle delay; review Accounts Receivable aging."
            )
        elif "receivable" in metric_norm or "ar" in metric_norm:
            val = db["outstanding_receivables"]
            return (
                f"Accounts Receivable Trend Analysis ({period}):\n"
                f"Total AR is ${val:,.2f}. If this trend is rising faster than sales, it means "
                "customers are taking longer to pay. We recommend shortening payment terms or offering "
                "early payment discounts to speed up cash inflows."
            )
        else:
            return f"Trend analysis for metric '{metric}' is not supported yet."

    def explain_anomalies(self) -> str:
        """Scan accounting modules and reports to flag financial anomalies or outliers."""
        db = self.report_engine.executive_dashboard()
        anomalies = []

        # Heuristic 1: AR vs Cash
        if db["outstanding_receivables"] > db["cash_position"] * 1.5 and db["cash_position"] > 0:
            anomalies.append(
                "⚠️ LIQUIDITY CONSTRAINTS: Outstanding customer invoices (AR) exceed cash balance by > 150%. "
                "This indicates cash flow is heavily locked up in customer receivables."
            )

        # Heuristic 2: Net profit negative
        if db["ytd_net_profit"] < 0:
            anomalies.append(
                f"⚠️ NEGATIVE EARNINGS: Year-To-Date operations are running at a net loss of ${abs(db['ytd_net_profit']):,.2f}."
            )

        # Heuristic 3: AP accumulation
        if db["outstanding_payables"] > db["cash_position"] * 0.8:
            anomalies.append(
                f"⚠️ HIGH DEBT PRESSURES: Pending vendor bills (AP) exceed 80% of your liquid cash balance. "
                "You may face short-term cash crunches when paying suppliers."
            )

        if not anomalies:
            return "No critical financial anomalies detected. Core indicators remain within standard ranges."

        return "Financial Anomalies Detected:\n\n" + "\n\n".join(anomalies)

    def answer_question(self, question: str) -> str:
        """Handle natural language questions about corporate financial data using heuristic routing."""
        q_norm = question.lower()
        db = self.report_engine.executive_dashboard()

        if "how much cash" in q_norm or "cash balance" in q_norm or "money in the bank" in q_norm:
            return f"The company currently holds ${db['cash_position']:,.2f} in cash and bank reserves."

        elif "revenue" in q_norm or "sales" in q_norm or "what did we sell" in q_norm:
            return f"Your Year-To-Date revenue stands at ${db['ytd_revenue']:,.2f}."

        elif "profit" in q_norm or "loss" in q_norm or "make money" in q_norm:
            if db["ytd_net_profit"] >= 0:
                return f"Yes, the company is profitable. YTD Net Profit is ${db['ytd_net_profit']:,.2f} (Margin: {db['net_profit_margin_pct']:.1f}%)."
            else:
                return f"No, the company is currently operating at a net loss of ${abs(db['ytd_net_profit']):,.2f}."

        elif "who owes" in q_norm or "receivable" in q_norm or "outstanding invoices" in q_norm:
            return f"Customers currently owe a total of ${db['outstanding_receivables']:,.2f} in outstanding invoices."

        elif "we owe" in q_norm or "payable" in q_norm or "vendor bills" in q_norm:
            return f"You currently owe vendors/suppliers a total of ${db['outstanding_payables']:,.2f}."

        else:
            # Fallback to general dashboard summary
            return (
                "I couldn't isolate the exact metric for your question. Here is the financial snapshot:\n"
                f"- Cash: ${db['cash_position']:,.2f}\n"
                f"- YTD Revenue: ${db['ytd_revenue']:,.2f}\n"
                f"- YTD Net Income: ${db['ytd_net_profit']:,.2f}\n"
                f"- Receivables: ${db['outstanding_receivables']:,.2f}\n"
                f"- Payables: ${db['outstanding_payables']:,.2f}\n"
            )

    # ── Heuristic Heuristics ──────────────────────────────────────────────────

    def _get_cash_takeaway(self, cash: float, ar: float, ap: float) -> str:
        net_cash = cash + ar - ap
        if net_cash < 0:
            return "Attention: Net liquid position is negative. Operational expenses cannot be covered by collection backlogs alone."
        elif cash < ap:
            return "Warning: Liquid cash balance is less than immediate vendor payables. Short-term cash crunch likely."
        else:
            return "Liquid capital levels are secure. Cash reserves are sufficient to cover operating payables."

    def _get_profitability_takeaway(self, margin: float, profit: float) -> str:
        if profit < 0:
            return "Attention: Operations are running at a net loss. Overhead costs must be rationalized immediately."
        elif margin < 10.0:
            return "Note: Core margins are tight (< 10%). Standardize pricing models or reduce variable vendor fees."
        else:
            return "Operating margins are strong. Reinvest surplus profit into scale-up channels."

    def _get_action_recommendations(self, cash: float, ar: float, ap: float, margin: float) -> str:
        recs = []
        if cash < ap:
            recs.append("   - [URGENT] Defer non-essential purchases to preserve cash. Contact customers in the AR backlog to expedite collections.")
        if ar > cash * 1.2:
            recs.append("   - Optimize Collections: Offer early-settlement discounts (e.g. 2/10 net 30) to speed up AR invoice recovery.")
        if margin < 10.0 and margin >= 0:
            recs.append("   - Margin Protection: Review unit economics. Focus sales efforts on higher-margin services or renegotiate bulk purchase rates.")
        if not recs:
            recs.append("   - Maintain Strategy: Core indicators are robust. Surplus cash can be allocated towards capital assets or pre-paying debt.")

        return "\n".join(recs)

    def _explain_profitability_factor(self, margin: float) -> str:
        if margin > 20:
            return "Excellent efficiency. For every dollar of revenue, you retain over 20 cents in net profits."
        elif margin > 10:
            return "Stable operating margins. Typical for healthy operations."
        elif margin > 0:
            return "Tight margins. Susceptible to sudden expense shocks."
        else:
            return "Deficit margins. Operating costs are higher than revenues. Immediate intervention needed."

    def _explain_liquidity_factor(self, ratio: float) -> str:
        if ratio >= 1.8:
            return "High liquidity. You have ample short-term assets to satisfy immediate vendor claims."
        elif ratio >= 1.2:
            return "Stable liquidity. Adequate cover for obligations."
        else:
            return "High risk of cash crunch. Short-term claims exceed easily reachable cash/receivables."

    def _explain_solvency_factor(self, ratio: float) -> str:
        if ratio < 0.5:
            return "Very low debt leverage. Highly stable capital backing."
        elif ratio < 1.5:
            return "Standard corporate leverage. Healthy balance between equity and debt financing."
        else:
            return "High debt load relative to equity. Substantial portion of capital is financed by creditors."

    def _explain_cash_factor(self, balance: float) -> str:
        if balance > 50000:
            return "Substantial cash reserves. High buffer against economic cycles."
        elif balance > 10000:
            return "Adequate operational buffer. Can sustain standard monthly expenditures."
        else:
            return "Low liquid cash reserves. Highly sensitive to payment delays."
