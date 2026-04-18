"""Tests for health check endpoints."""

import pytest
from httpx import AsyncClient


class TestHealthEndpoints:
    """Tests for health check API endpoints."""

    @pytest.mark.asyncio
    async def test_liveness_probe(self, async_client: AsyncClient):
        """Test Kubernetes liveness probe."""
        response = await async_client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"

    @pytest.mark.asyncio
    async def test_readiness_probe_in_development(self, async_client: AsyncClient):
        """Test readiness probe (may fail if DB not available)."""
        response = await async_client.get("/health/ready")
        # In development without DB, this might return 503
        assert response.status_code in [200, 503]

    @pytest.mark.asyncio
    async def test_comprehensive_health_check(self, async_client: AsyncClient):
        """Test comprehensive health endpoint."""
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "status" in data
        assert "timestamp" in data
        assert "version" in data
        assert "environment" in data
        assert "components" in data

        # Check component structure
        assert len(data["components"]) > 0
        for component in data["components"]:
            assert "name" in component
            assert "status" in component

    @pytest.mark.asyncio
    async def test_root_endpoint(self, async_client: AsyncClient):
        """Test root endpoint returns app info."""
        response = await async_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "status" in data
