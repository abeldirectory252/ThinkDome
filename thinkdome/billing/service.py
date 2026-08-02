"""Billing service for calculating sandbox costs, usage reports, and compiling invoice PDFs."""

from __future__ import annotations

import calendar
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from thinkdome.database.service import DatabaseService

logger = logging.getLogger(__name__)

class BillingService:
    """Calculates compute and API usage costs for billing cycles and compiles invoice PDFs."""

    def __init__(self, db_service: DatabaseService) -> None:
        self.db_service = db_service
        self.settings = db_service.settings
        self.invoices_dir = Path(self.settings.FILE_STORAGE_DIR) / "invoices"
        self.invoices_dir.mkdir(parents=True, exist_ok=True)

    def get_cycle_boundaries(self, cycle: str) -> Tuple[datetime, datetime, str]:
        """Calculate start and end datetime boundaries and label for a cycle name."""
        now = datetime.utcnow()
        if cycle == "last":
            # Previous calendar month
            first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = first_of_this_month - timedelta(seconds=1)
            start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            label = start.strftime("%B %Y")
        elif cycle == "ytd":
            # Year to date (start of year to current time)
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
            label = f"{now.year} YTD"
        else:
            # Current calendar month ("this" or default)
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
            label = now.strftime("%B %Y")
        return start, end, label

    def get_billing_data(self, cycle: str, username: str) -> Dict[str, Any]:
        """Aggregate sandbox usage details and execution counts to compute the bill."""
        start, end, label = self.get_cycle_boundaries(cycle)
        start_str = start.isoformat()
        end_str = end.isoformat()

        # 1. Fetch all sandboxes
        all_sandboxes = self.db_service.list_sandboxes()
        # Non-admin users only see their own sandboxes
        if username not in ("admin", "administrator"):
            all_sandboxes = [s for s in all_sandboxes if s["owner"] == username]

        # 2. Fetch all execution request logs in the cycle time window
        logs = self.db_service.fetch_all(
            "SELECT * FROM request_logs WHERE timestamp >= ? AND timestamp <= ?",
            (start_str, end_str)
        )

        budget_limit = 600.0  # matches front-end budgetLimit mockup limit of $600.00
        total_compute = 0.0
        total_execs = 0
        sandboxes_billing = {}

        for sb in all_sandboxes:
            sb_id = sb["sandbox_id"]
            created_at_str = sb["created_at"]
            
            try:
                created_at = datetime.fromisoformat(created_at_str)
            except Exception:
                created_at = start

            # Active overlap window
            active_start = max(created_at, start)
            active_end = min(datetime.utcnow(), end)

            if active_start > active_end:
                uptime_hours = 0.0
            else:
                uptime_hours = (active_end - active_start).total_seconds() / 3600.0

            # Scale down uptime if stopped to reflect inactive usage (mockup model)
            if sb["status"] == "stopped":
                uptime_hours = max(0.5, uptime_hours * 0.25)

            rate = sb.get("cost_per_hour", 0.0)
            if rate is None or rate == 0.0:
                # Docker cost formula fallback: $0.01 per 128MB RAM/hr + $0.02 per vCPU/hr + $0.005 for network
                memory_mb = sb.get("memory_mb", 256)
                cpu_cores = sb.get("cpu_cores", 1.0)
                net = bool(sb.get("network_enabled", 0))
                rate = (memory_mb / 128) * 0.01 + cpu_cores * 0.02 + (0.005 if net else 0.0)

            compute_cost = uptime_hours * rate
            total_compute += compute_cost

            # Attribute executions count
            sb_execs = 0
            for log in logs:
                log_sb_id = log.get("sandbox_id")
                if log_sb_id == sb_id:
                    sb_execs += 1
                elif not log_sb_id:
                    # Fallback default sandbox matching logic
                    if len(all_sandboxes) == 1 or sb_id == all_sandboxes[0]["sandbox_id"]:
                        sb_execs += 1
            
            total_execs += sb_execs

            memory_mb = sb.get("memory_mb", 256)
            cpu_cores = sb.get("cpu_cores", 1.0)
            runtime_env = f"Docker ({memory_mb}MB RAM, {cpu_cores} vCPU)"

            sandboxes_billing[sb_id] = {
                "uptime": f"{uptime_hours:.1f} hrs",
                "rate": f"${rate:.3f}/hr",
                "compute": f"${compute_cost:.2f}",
                "execs": str(sb_execs),
                "subtotal": f"${compute_cost:.2f}",
                "runtime": runtime_env
            }

        # Keep total execs matching actual logs fetched
        total_execs = len(logs)

        # Cost Breakdown (Compute, API, Storage, Network)
        # API fee: $0.01 per execution
        api_spend = total_execs * 0.01
        # Storage fee: $1.50 per sandbox in DB
        storage_spend = len(all_sandboxes) * 1.50
        # Network fee: $0.10 for each network-enabled sandbox
        network_spend = sum(0.10 for sb in all_sandboxes if sb.get("network_enabled", 0))

        total_spend = total_compute + api_spend + storage_spend + network_spend
        budget_pct = (total_spend / budget_limit) * 100.0

        # EOM projection
        if cycle in ("last", "ytd"):
            projected_spend = total_spend
        else:
            day_of_month = datetime.utcnow().day
            days_in_month = calendar.monthrange(datetime.utcnow().year, datetime.utcnow().month)[1]
            projected_spend = total_spend * (days_in_month / max(1, day_of_month))

        over_budget = projected_spend > budget_limit
        over_pct = max(0.0, (projected_spend - budget_limit) / budget_limit * 100.0)

        return {
            "label": label,
            "total": f"${total_spend:.2f}",
            "budgetPct": f"{budget_pct:.1f}",
            "budgetLimit": f"${budget_limit:.2f}",
            "projected": f"${projected_spend:.2f}",
            "overBudget": over_budget,
            "overPct": f"{over_pct:.1f}",
            "execs": str(total_execs),
            "compute": f"${total_compute:.2f}",
            "api": f"${api_spend:.2f}",
            "storage": f"${storage_spend:.2f}",
            "network": f"${network_spend:.2f}",
            "sandboxes": sandboxes_billing
        }

    def compile_invoice_pdf(self, cycle: str, username: str) -> Tuple[str, Path]:
        """Compile a dynamic billing invoice PDF and write to storage."""
        invoice_id = f"inv_{uuid.uuid4().hex[:8]}"
        billing_data = self.get_billing_data(cycle, username)
        
        pdf_path = self.invoices_dir / f"invoice_{invoice_id}.pdf"
        
        # Build self-contained valid PDF bytes
        text_lines = [
            "============================================================",
            "                   THINKDOME SYSTEM INVOICE",
            "============================================================",
            f"Invoice Number : #{invoice_id}",
            f"Billing Cycle  : {billing_data['label']}",
            f"Client Account : {username}",
            f"Generated Date : {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "------------------------------------------------------------",
            "SPENDING SUMMARY:",
            f" - Compute Spend       : {billing_data['compute']}",
            f" - Execution API Spend : {billing_data['api']}",
            f" - Workspace Storage   : {billing_data['storage']}",
            f" - Network Data Fees   : {billing_data['network']}",
            "------------------------------------------------------------",
            f" TOTAL DUE AMOUNT      : {billing_data['total']}",
            "============================================================",
            "ITEMIZED SANDBOX CHARGES:",
        ]

        for sb_id, details in billing_data["sandboxes"].items():
            text_lines.append(
                f" - {sb_id} ({details['runtime']}):"
            )
            text_lines.append(
                f"   Uptime: {details['uptime']} | Rate: {details['rate']} | Cost: {details['compute']} | Execs: {details['execs']}"
            )
            text_lines.append("")

        text_lines.extend([
            "------------------------------------------------------------",
            "Thank you for using ThinkDome Sandbox Environment Services.",
            "If you have any billing inquiries, contact billing@thinkdome.io.",
            "============================================================"
        ])

        # Write text commands into the PDF content stream
        stream_content = "BT\n/F1 11 Tf\n50 780 Td\n15 Tl\n"
        for line in text_lines:
            escaped = line.replace("(", "\\(").replace(")", "\\)")
            stream_content += f"({escaped}) Tj T*\n"
        stream_content += "ET"

        pdf_body = (
            "%PDF-1.4\n"
            "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
            "3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /MediaBox [0 0 595 842] /Contents 5 0 R >>\nendobj\n"
            "4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj\n"
            "5 0 obj\n"
            f"<< /Length {len(stream_content)} >>\n"
            "stream\n"
            f"{stream_content}\n"
            "endstream\n"
            "endobj\n"
            "xref\n"
            "0 6\n"
            "0000000000 65535 f \n"
            "trailer\n"
            "<< /Size 6 /Root 1 0 R >>\n"
            "startxref\n"
            "0\n"
            "%%EOF"
        )

        pdf_path.write_bytes(pdf_body.encode("utf-8"))
        logger.info(f"Compiled invoice PDF generated at {pdf_path}")
        return invoice_id, pdf_path
