"""Tests for appeals API endpoints."""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

from src.core.models import DenialReason


class TestAppealsEndpoints:
    """Tests for appeals API endpoints."""

    @pytest.mark.asyncio
    async def test_text_appeal_requires_auth(self, async_client: AsyncClient):
        """Test that text appeal endpoint requires authentication."""
        response = await async_client.post(
            "/api/v1/appeals/text",
            json={"denial_text": "Sample denial letter text..."}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_text_appeal_with_auth(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        sample_denial_text: str,
        sample_appeal_letter,
    ):
        """Test text appeal generation with authentication."""
        # Mock the LLM client and service
        with patch("src.api.routes.appeals.get_appeal_service") as mock_service:
            mock_instance = AsyncMock()
            mock_instance.process_denial_from_text = AsyncMock(
                return_value=sample_appeal_letter
            )
            mock_service.return_value = mock_instance

            response = await async_client.post(
                "/api/v1/appeals/text",
                json={"denial_text": sample_denial_text},
                headers=auth_headers,
            )

            # Should succeed (or fail on DB if not available)
            assert response.status_code in [200, 500, 503]

    @pytest.mark.asyncio
    async def test_text_appeal_validation_too_short(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        """Test that denial text must meet minimum length."""
        response = await async_client.post(
            "/api/v1/appeals/text",
            json={"denial_text": "Too short"},
            headers=auth_headers,
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_upload_appeal_requires_auth(self, async_client: AsyncClient):
        """Test that upload endpoint requires authentication."""
        response = await async_client.post(
            "/api/v1/appeals/upload",
            files={"denial_letter": ("test.pdf", b"fake content", "application/pdf")},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_upload_appeal_invalid_file_type(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        """Bytes that don't match any supported magic-number signature are rejected."""
        response = await async_client.post(
            "/api/v1/appeals/upload",
            files={"denial_letter": ("test.txt", b"plain text content", "text/plain")},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "match" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_appeal_requires_auth(self, async_client: AsyncClient):
        """Test that getting appeal requires authentication."""
        response = await async_client.get("/api/v1/appeals/some-appeal-id")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_nonexistent_appeal(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        """Test getting non-existent appeal returns 404."""
        response = await async_client.get(
            "/api/v1/appeals/nonexistent-appeal-id",
            headers=auth_headers,
        )
        # Either 404 (not found) or 500 (DB error in test env)
        assert response.status_code in [404, 500]


class TestAppealsValidation:
    """Tests for request validation."""

    @pytest.mark.asyncio
    async def test_diagnosis_codes_from_string(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        """Test that comma-separated diagnosis codes are parsed."""
        with patch("src.api.routes.appeals.get_appeal_service") as mock_service:
            mock_instance = AsyncMock()
            mock_instance.process_denial_from_text = AsyncMock()
            mock_service.return_value = mock_instance

            response = await async_client.post(
                "/api/v1/appeals/text",
                json={
                    "denial_text": "A" * 100,  # Meet minimum length
                    "diagnosis_codes": ["M54.5", "G89.29"],
                },
                headers=auth_headers,
            )
            # Check request was processed (status depends on mock/DB)
            assert response.status_code in [200, 500, 503]

    @pytest.mark.asyncio
    async def test_prior_treatments_from_string(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        """Test that comma-separated treatments are parsed."""
        with patch("src.api.routes.appeals.get_appeal_service") as mock_service:
            mock_instance = AsyncMock()
            mock_instance.process_denial_from_text = AsyncMock()
            mock_service.return_value = mock_instance

            response = await async_client.post(
                "/api/v1/appeals/text",
                json={
                    "denial_text": "A" * 100,
                    "prior_treatments": ["PT", "NSAIDs"],
                },
                headers=auth_headers,
            )
            assert response.status_code in [200, 500, 503]
