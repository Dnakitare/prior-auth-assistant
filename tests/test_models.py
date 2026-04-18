"""Tests for core data models."""

import pytest
from datetime import datetime

from src.core.models import (
    DenialExtraction,
    DenialReason,
    PatientContext,
    AppealLetter,
)


class TestDenialReason:
    """Tests for DenialReason enum."""

    def test_all_reasons_defined(self):
        """Verify all expected denial reasons exist."""
        expected = [
            "medical_necessity",
            "not_covered",
            "out_of_network",
            "missing_information",
            "experimental_treatment",
            "step_therapy_required",
            "quantity_limit",
            "prior_auth_required",
            "other",
        ]
        actual = [r.value for r in DenialReason]
        assert set(expected) == set(actual)

    def test_reason_from_string(self):
        """Test creating reason from string value."""
        reason = DenialReason("medical_necessity")
        assert reason == DenialReason.MEDICAL_NECESSITY


class TestDenialExtraction:
    """Tests for DenialExtraction model."""

    def test_minimal_extraction(self):
        """Test creating extraction with minimal data."""
        extraction = DenialExtraction(raw_text="Sample text")
        assert extraction.raw_text == "Sample text"
        assert extraction.denial_reason == DenialReason.OTHER
        assert extraction.payer_name is None

    def test_full_extraction(self, sample_denial_extraction):
        """Test full extraction with all fields."""
        assert sample_denial_extraction.payer_name == "Blue Cross Blue Shield"
        assert sample_denial_extraction.denial_reason == DenialReason.MEDICAL_NECESSITY
        assert "99213" in sample_denial_extraction.procedure_codes
        assert "M54.5" in sample_denial_extraction.diagnosis_codes

    def test_serialization(self, sample_denial_extraction):
        """Test model serialization to dict."""
        data = sample_denial_extraction.model_dump()
        assert data["payer_name"] == "Blue Cross Blue Shield"
        assert data["denial_reason"] == DenialReason.MEDICAL_NECESSITY


class TestPatientContext:
    """Tests for PatientContext model."""

    def test_minimal_context(self):
        """Test creating context with required fields only."""
        context = PatientContext(
            patient_name="Test Patient",
            procedure_code="99213",
        )
        assert context.patient_name == "Test Patient"
        assert context.diagnosis_codes == []

    def test_full_context(self, sample_patient_context):
        """Test full patient context."""
        assert sample_patient_context.patient_name == "John Doe"
        assert sample_patient_context.treating_physician == "Dr. Jane Smith"
        assert len(sample_patient_context.prior_treatments) == 3


class TestAppealLetter:
    """Tests for AppealLetter model."""

    def test_appeal_creation(self, sample_appeal_letter):
        """Test appeal letter creation."""
        assert sample_appeal_letter.id  # UUID-generated
        assert sample_appeal_letter.confidence_score == 0.85
        assert len(sample_appeal_letter.required_attachments) == 2

    def test_appeal_has_denial_info(self, sample_appeal_letter):
        """Test appeal includes denial extraction."""
        assert sample_appeal_letter.denial_extraction is not None
        assert sample_appeal_letter.denial_extraction.payer_name == "Blue Cross Blue Shield"
