"""Tests for core services."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock

from src.core.services import AppealGenerationService
from src.core.models import DenialExtraction, DenialReason


class TestAppealGenerationService:
    """Tests for AppealGenerationService."""

    @pytest.fixture
    def service(self, mock_ocr_provider, mock_llm_client):
        """Create service with mocked dependencies."""
        return AppealGenerationService(
            ocr_provider=mock_ocr_provider,
            llm_client=mock_llm_client,
        )

    @pytest.mark.asyncio
    async def test_process_denial_from_text(
        self,
        service,
        mock_llm_client,
        sample_denial_extraction,
    ):
        """Test processing denial from text."""
        mock_llm_client.extract_denial_info.return_value = sample_denial_extraction
        mock_llm_client.generate_appeal.return_value = "Dear Sir/Madam..."

        appeal = await service.process_denial_from_text("Sample denial text...")

        assert appeal is not None
        assert appeal.id is not None
        assert appeal.letter_content == "Dear Sir/Madam..."
        assert appeal.denial_extraction == sample_denial_extraction
        mock_llm_client.extract_denial_info.assert_called_once()
        mock_llm_client.generate_appeal.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_denial_from_document(
        self,
        service,
        mock_ocr_provider,
        mock_llm_client,
        sample_denial_extraction,
    ):
        """Test processing denial from document bytes."""
        mock_llm_client.extract_denial_info.return_value = sample_denial_extraction
        mock_llm_client.generate_appeal.return_value = "Dear Sir/Madam..."

        appeal = await service.process_denial(b"fake document bytes")

        assert appeal is not None
        mock_ocr_provider.extract_text.assert_called_once()
        mock_llm_client.extract_denial_info.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_with_patient_context(
        self,
        service,
        mock_llm_client,
        sample_denial_extraction,
        sample_patient_context,
    ):
        """Test processing with patient context."""
        mock_llm_client.extract_denial_info.return_value = sample_denial_extraction
        mock_llm_client.generate_appeal.return_value = "Appeal with context..."

        appeal = await service.process_denial_from_text(
            "Sample denial text...",
            patient_context=sample_patient_context,
        )

        assert appeal is not None
        # Verify patient context was passed to generate_appeal
        mock_llm_client.generate_appeal.assert_called_once_with(
            sample_denial_extraction,
            sample_patient_context,
        )

    def test_calculate_confidence_full_info(self, service, sample_denial_extraction):
        """Test confidence calculation with full information."""
        confidence = service._calculate_confidence(sample_denial_extraction)
        assert confidence > 0.8  # High confidence with complete data

    def test_calculate_confidence_minimal_info(self, service):
        """Test confidence calculation with minimal information."""
        minimal_extraction = DenialExtraction(raw_text="Sample text")
        confidence = service._calculate_confidence(minimal_extraction)
        assert confidence < 0.2  # Low confidence with minimal data

    def test_get_required_documents_medical_necessity(self, service):
        """Test document requirements for medical necessity denial."""
        extraction = DenialExtraction(
            denial_reason=DenialReason.MEDICAL_NECESSITY,
            raw_text="test",
        )
        docs = service._get_required_documents(extraction)
        assert len(docs) > 0
        assert any("medical necessity" in doc.lower() for doc in docs)

    def test_get_required_documents_step_therapy(self, service):
        """Test document requirements for step therapy denial."""
        extraction = DenialExtraction(
            denial_reason=DenialReason.STEP_THERAPY,
            raw_text="test",
        )
        docs = service._get_required_documents(extraction)
        assert len(docs) > 0
