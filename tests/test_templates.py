"""Tests for appeal templates."""

import pytest

from src.templates.appeal_templates import (
    TEMPLATES,
    get_template,
    get_required_documents,
)


class TestAppealTemplates:
    """Tests for appeal template functions."""

    def test_all_templates_exist(self):
        """Verify all denial types have templates."""
        expected_types = [
            "medical_necessity",
            "not_covered",
            "out_of_network",
            "missing_information",
            "experimental_treatment",
            "step_therapy_required",
            "quantity_limit",
            "prior_auth_required",
            "other",
            "default",
        ]
        for denial_type in expected_types:
            template = get_template(denial_type)
            assert template is not None, f"Missing template for {denial_type}"
            assert len(template) > 0

    def test_template_has_placeholders(self):
        """Verify templates have expected placeholders."""
        template = get_template("medical_necessity")
        assert "{current_date}" in template
        assert "{patient_name}" in template
        assert "{payer_name}" in template

    def test_get_template_unknown_type(self):
        """Test fallback for unknown denial type."""
        template = get_template("unknown_type")
        default_template = get_template("default")
        assert template == default_template

    def test_get_required_documents_medical_necessity(self):
        """Test required documents for medical necessity."""
        docs = get_required_documents("medical_necessity")
        assert isinstance(docs, list)
        assert len(docs) > 0
        assert any("necessity" in doc.lower() or "clinical" in doc.lower() for doc in docs)

    def test_get_required_documents_step_therapy(self):
        """Test required documents for step therapy."""
        docs = get_required_documents("step_therapy_required")
        assert isinstance(docs, list)
        assert len(docs) > 0

    def test_get_required_documents_unknown_type(self):
        """Test required documents for unknown type."""
        docs = get_required_documents("unknown_type")
        assert isinstance(docs, list)
        # Should return default documents

    def test_template_formatting(self):
        """Test that template can be formatted with sample data."""
        template = get_template("medical_necessity")
        formatted = template.format(
            current_date="January 1, 2024",
            patient_name="John Doe",
            member_id="123456",
            claim_number="CLM789",
            service_date="December 1, 2023",
            procedure_code="99213",
            procedure_description="Office visit",
            payer_name="Test Insurance",
            denial_date="December 15, 2023",
            diagnosis_codes="M54.5",
            clinical_notes="Patient has chronic pain...",
            prior_treatments="- PT\n- NSAIDs",
            denial_reason_text="Does not meet criteria",
            treating_physician="Dr. Smith",
            required_documents="1. Letter\n2. Notes",
        )

        assert "January 1, 2024" in formatted
        assert "John Doe" in formatted
        assert "Test Insurance" in formatted
