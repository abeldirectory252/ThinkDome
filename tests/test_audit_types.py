"""Unit tests for audit types, enums, and response wrapping."""

from __future__ import annotations

import json
from thinkdome.apps.erp.audit.types import (
    AuditFinding,
    AuditEvidence,
    AuditAssertion,
    RiskRating,
    Confidence,
    audit_response,
)


def test_audit_evidence_creation():
    """Test creating an AuditEvidence model."""
    evidence = AuditEvidence(
        source="GL Entry",
        document_name="GLE-001",
        description="Verify ledger entry",
        data={"amount": 100.0},
    )
    assert evidence.source == "GL Entry"
    assert evidence.document_name == "GLE-001"
    assert evidence.data == {"amount": 100.0}
    assert isinstance(evidence.collected_at, str)


def test_audit_finding_creation():
    """Test creating an AuditFinding model."""
    evidence = AuditEvidence(
        source="GL Entry",
        document_name="GLE-001",
        description="Verify ledger entry",
    )
    finding = AuditFinding(
        title="Unauthorized entry",
        risk_rating=RiskRating.HIGH,
        assertions=[AuditAssertion.EXISTENCE, AuditAssertion.OCCURRENCE],
        erpnext_documents=["GLE-001"],
        evidence=[evidence],
        observation="Found unauthorized entry",
        audit_reasoning="Bypassed controls",
    )
    assert finding.title == "Unauthorized entry"
    assert finding.risk_rating == RiskRating.HIGH
    assert AuditAssertion.EXISTENCE in finding.assertions
    assert len(finding.evidence) == 1
    assert finding.evidence[0].document_name == "GLE-001"


def test_audit_response_envelope():
    """Test standard response envelope generation."""
    finding = AuditFinding(
        title="Unauthorized entry",
        risk_rating=RiskRating.HIGH,
        assertions=[AuditAssertion.EXISTENCE],
    )
    resp = audit_response(
        data={"test": "data"},
        evidence_source="GL Entry",
        confidence=Confidence.HIGH,
        warnings=["Check details"],
        findings=[finding],
    )
    assert resp["data"] == {"test": "data"}
    assert resp["evidence_source"] == "GL Entry"
    assert resp["confidence"] == "HIGH"
    assert resp["warnings"] == ["Check details"]
    assert len(resp["findings"]) == 1
    assert resp["findings"][0]["title"] == "Unauthorized entry"
