"""Audit core types, enums, and data structures.

Every audit finding, evidence item, and test result uses these types
to ensure consistent, structured output across all audit tools.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────


class RiskRating(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Confidence(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AuditAssertion(str, enum.Enum):
    EXISTENCE = "Existence"
    OCCURRENCE = "Occurrence"
    COMPLETENESS = "Completeness"
    ACCURACY = "Accuracy"
    CUTOFF = "Cutoff"
    CLASSIFICATION = "Classification"
    VALUATION = "Valuation"
    RIGHTS_AND_OBLIGATIONS = "Rights & Obligations"
    PRESENTATION_AND_DISCLOSURE = "Presentation & Disclosure"


class ControlEffectiveness(str, enum.Enum):
    EFFECTIVE = "EFFECTIVE"
    INEFFECTIVE = "INEFFECTIVE"
    NOT_TESTED = "NOT_TESTED"
    UNABLE_TO_CONCLUDE = "UNABLE_TO_CONCLUDE"


# ── Core Data Structures ────────────────────────────────────────────────────


class AuditEvidence(BaseModel):
    """A single piece of audit evidence."""

    source: str = Field(description="ERPNext doctype/document or data source")
    document_name: Optional[str] = Field(default=None, description="Specific document ID")
    description: str = Field(description="What this evidence shows")
    data: Any = Field(default=None, description="Raw evidence data")
    collected_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AuditFinding(BaseModel):
    """A structured audit finding following professional standards."""

    finding_id: str = Field(default_factory=lambda: f"AF-{uuid.uuid4().hex[:8].upper()}")
    title: str
    risk_rating: RiskRating
    assertions: List[AuditAssertion] = Field(default_factory=list)
    erpnext_documents: List[str] = Field(default_factory=list)
    evidence: List[AuditEvidence] = Field(default_factory=list)
    observation: str = ""
    audit_reasoning: str = ""
    impact: str = ""
    recommendation: str = ""
    management_response: Optional[str] = None
    auditor_conclusion: str = ""
    confidence: Confidence = Confidence.HIGH
    confidence_explanation: Optional[str] = None


class ControlTestResult(BaseModel):
    """Result of a control design and operating effectiveness test."""

    control: str
    description: str = ""
    design_effectiveness: ControlEffectiveness = ControlEffectiveness.NOT_TESTED
    operating_effectiveness: ControlEffectiveness = ControlEffectiveness.NOT_TESTED
    exceptions: List[Dict[str, Any]] = Field(default_factory=list)
    sample_size: int = 0
    exception_count: int = 0
    evidence: List[AuditEvidence] = Field(default_factory=list)
    conclusion: str = ""


class SoDConflict(BaseModel):
    """A segregation of duties conflict for a user."""

    user: str
    user_email: Optional[str] = None
    role_a: str
    role_b: str
    conflict: str
    risk: RiskRating = RiskRating.HIGH


class AuditWorkpaper(BaseModel):
    """Structured audit workpaper containing evidence and analysis."""

    workpaper_id: str = Field(default_factory=lambda: f"WP-{uuid.uuid4().hex[:8].upper()}")
    title: str
    objective: str = ""
    scope: str = ""
    procedure: str = ""
    evidence: List[AuditEvidence] = Field(default_factory=list)
    findings: List[AuditFinding] = Field(default_factory=list)
    conclusion: str = ""
    prepared_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── Standard Audit Response Wrapper ──────────────────────────────────────────


def audit_response(
    data: Any,
    evidence_source: str,
    confidence: Confidence = Confidence.HIGH,
    warnings: Optional[List[str]] = None,
    findings: Optional[List[AuditFinding]] = None,
) -> Dict[str, Any]:
    """Wrap audit tool output in the standard response envelope.

    Every audit tool returns data through this function to ensure
    consistent structure with evidence metadata.
    """
    resp: Dict[str, Any] = {
        "data": data,
        "evidence_source": evidence_source,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "confidence": confidence.value,
        "warnings": warnings or [],
    }
    if findings:
        resp["findings"] = [f.model_dump() for f in findings]
    return resp


# ── Pydantic Input Schemas ───────────────────────────────────────────────────


class CompanyInput(BaseModel):
    company: Optional[str] = Field(default=None, description="Company name (uses default if omitted)")


class DateRangeInput(BaseModel):
    from_date: str = Field(description="Start date (YYYY-MM-DD)")
    to_date: str = Field(description="End date (YYYY-MM-DD)")
    company: Optional[str] = Field(default=None, description="Company name")


class PeriodCompareInput(BaseModel):
    period1_start: str = Field(description="First period start (YYYY-MM-DD)")
    period1_end: str = Field(description="First period end (YYYY-MM-DD)")
    period2_start: str = Field(description="Second period start (YYYY-MM-DD)")
    period2_end: str = Field(description="Second period end (YYYY-MM-DD)")
    company: Optional[str] = Field(default=None, description="Company name")


class LedgerSearchInput(BaseModel):
    from_date: Optional[str] = Field(default=None, description="Start date (YYYY-MM-DD)")
    to_date: Optional[str] = Field(default=None, description="End date (YYYY-MM-DD)")
    account: Optional[str] = Field(default=None, description="Account name filter")
    party: Optional[str] = Field(default=None, description="Party name filter")
    min_amount: Optional[float] = Field(default=None, description="Minimum absolute amount")
    max_amount: Optional[float] = Field(default=None, description="Maximum absolute amount")
    voucher_type: Optional[str] = Field(default=None, description="Voucher type filter")
    company: Optional[str] = Field(default=None, description="Company name")
    limit: int = Field(default=500, description="Max rows to return")


class ThresholdInput(BaseModel):
    from_date: Optional[str] = Field(default=None, description="Start date (YYYY-MM-DD)")
    to_date: Optional[str] = Field(default=None, description="End date (YYYY-MM-DD)")
    threshold: Optional[float] = Field(default=None, description="Amount threshold (uses materiality default if omitted)")
    company: Optional[str] = Field(default=None, description="Company name")
    limit: int = Field(default=200, description="Max rows")


class DocumentInput(BaseModel):
    doctype: str = Field(description="ERPNext DocType (e.g. 'Journal Entry')")
    name: str = Field(description="Document name/ID")


class DocumentListInput(BaseModel):
    doctype: str = Field(description="ERPNext DocType")
    from_date: Optional[str] = Field(default=None, description="Start date")
    to_date: Optional[str] = Field(default=None, description="End date")
    status: Optional[str] = Field(default=None, description="Document status filter")
    limit: int = Field(default=200, description="Max rows")


class SalesDocInput(BaseModel):
    name: str = Field(description="Sales Order / Invoice name")


class PurchaseDocInput(BaseModel):
    name: str = Field(description="Purchase Order / Invoice name")


class ThreeWayMatchInput(BaseModel):
    from_date: Optional[str] = Field(default=None, description="Start date")
    to_date: Optional[str] = Field(default=None, description="End date")
    supplier: Optional[str] = Field(default=None, description="Supplier filter")
    company: Optional[str] = Field(default=None, description="Company name")
    limit: int = Field(default=100, description="Max results")


class StockLedgerInput(BaseModel):
    item_code: Optional[str] = Field(default=None, description="Item code filter")
    warehouse: Optional[str] = Field(default=None, description="Warehouse filter")
    from_date: Optional[str] = Field(default=None, description="Start date")
    to_date: Optional[str] = Field(default=None, description="End date")
    company: Optional[str] = Field(default=None, description="Company name")
    limit: int = Field(default=500, description="Max rows")


class BankReconciliationInput(BaseModel):
    bank_account: Optional[str] = Field(default=None, description="Bank account name")
    from_date: Optional[str] = Field(default=None, description="Start date")
    to_date: Optional[str] = Field(default=None, description="End date")
    company: Optional[str] = Field(default=None, description="Company name")


class AssetInput(BaseModel):
    from_date: Optional[str] = Field(default=None, description="Start date")
    to_date: Optional[str] = Field(default=None, description="End date")
    company: Optional[str] = Field(default=None, description="Company name")
    limit: int = Field(default=200, description="Max rows")


class UserListInput(BaseModel):
    enabled: Optional[bool] = Field(default=None, description="Filter by enabled status")
    role: Optional[str] = Field(default=None, description="Filter by role")
    limit: int = Field(default=500, description="Max rows")


class UserInput(BaseModel):
    user: Optional[str] = Field(default=None, description="User email filter")
    from_date: Optional[str] = Field(default=None, description="Start date")
    to_date: Optional[str] = Field(default=None, description="End date")
    limit: int = Field(default=500, description="Max rows")


class SoDInput(BaseModel):
    company: Optional[str] = Field(default=None, description="Company name")


class WorkflowInput(BaseModel):
    doctype: Optional[str] = Field(default=None, description="DocType filter")
    document_name: Optional[str] = Field(default=None, description="Document name")


class ActivityLogInput(BaseModel):
    user: Optional[str] = Field(default=None, description="User filter")
    doctype: Optional[str] = Field(default=None, description="DocType filter")
    from_date: Optional[str] = Field(default=None, description="Start date")
    to_date: Optional[str] = Field(default=None, description="End date")
    limit: int = Field(default=500, description="Max rows")


class FraudDetectionInput(BaseModel):
    doctype: Optional[str] = Field(default=None, description="DocType to analyze")
    from_date: Optional[str] = Field(default=None, description="Start date")
    to_date: Optional[str] = Field(default=None, description="End date")
    company: Optional[str] = Field(default=None, description="Company name")
    limit: int = Field(default=500, description="Max rows")


class BenfordInput(BaseModel):
    doctype: str = Field(description="DocType to analyze (e.g. 'Journal Entry', 'Purchase Invoice')")
    amount_field: str = Field(default="grand_total", description="Field name containing amounts")
    from_date: Optional[str] = Field(default=None, description="Start date")
    to_date: Optional[str] = Field(default=None, description="End date")
    company: Optional[str] = Field(default=None, description="Company name")


class ControlTestInput(BaseModel):
    control_name: str = Field(description="Control to test (e.g. 'purchase_approval_workflow', 'invoice_matching')")
    from_date: Optional[str] = Field(default=None, description="Testing period start")
    to_date: Optional[str] = Field(default=None, description="Testing period end")
    sample_size: int = Field(default=25, description="Number of items to test")
    company: Optional[str] = Field(default=None, description="Company name")


class SampleInput(BaseModel):
    doctype: str = Field(description="ERPNext DocType to sample from")
    from_date: Optional[str] = Field(default=None, description="Start date")
    to_date: Optional[str] = Field(default=None, description="End date")
    sample_size: int = Field(default=25, description="Number of items to select")
    amount_field: str = Field(default="grand_total", description="Amount field for value-based sampling")
    company: Optional[str] = Field(default=None, description="Company name")


class InvestigateInput(BaseModel):
    doctype: str = Field(description="Document type (e.g. 'Payment Entry')")
    name: str = Field(description="Document name/ID (e.g. 'PAY-00045')")
    objective: str = Field(default="Check validity and fraud risk", description="Investigation objective")


class EvidenceInput(BaseModel):
    doctype: str = Field(description="DocType of document to collect evidence for")
    name: str = Field(description="Document name/ID")


class WorkpaperInput(BaseModel):
    title: str = Field(description="Workpaper title")
    objective: str = Field(description="Audit objective")
    scope: str = Field(default="", description="Scope description")
    procedure: str = Field(default="", description="Audit procedure performed")
    evidence_refs: List[str] = Field(default_factory=list, description="Document references (doctype:name)")
    conclusion: str = Field(default="", description="Auditor conclusion")


class FindingInput(BaseModel):
    title: str = Field(description="Finding title")
    risk_rating: str = Field(description="Risk rating: CRITICAL, HIGH, MEDIUM, LOW")
    assertions: List[str] = Field(default_factory=list, description="Affected assertions")
    erpnext_documents: List[str] = Field(default_factory=list, description="Related ERPNext document references")
    observation: str = Field(description="What was observed")
    audit_reasoning: str = Field(description="Why this is a finding")
    impact: str = Field(default="", description="Impact description")
    recommendation: str = Field(default="", description="Recommended action")
    confidence: str = Field(default="HIGH", description="Confidence level: HIGH, MEDIUM, LOW")
    confidence_explanation: Optional[str] = Field(default=None, description="Explain if confidence is not HIGH")


class ReportInput(BaseModel):
    company: Optional[str] = Field(default=None, description="Company name")
    from_date: Optional[str] = Field(default=None, description="Audit period start")
    to_date: Optional[str] = Field(default=None, description="Audit period end")
    include_findings: bool = Field(default=True, description="Include detailed findings")


class EmptyInput(BaseModel):
    pass
