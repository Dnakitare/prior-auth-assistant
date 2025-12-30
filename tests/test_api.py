"""Tests for API endpoints."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_health_check():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_generate_appeal_from_text_validation():
    """Test that text endpoint validates input."""
    # Too short denial text should fail
    response = client.post(
        "/api/v1/appeals/text",
        json={"denial_text": "too short"},
    )
    assert response.status_code == 400
    assert "at least 50 characters" in response.json()["detail"]


def test_get_appeal_not_found():
    """Test getting non-existent appeal."""
    response = client.get("/api/v1/appeals/nonexistent-id")
    assert response.status_code == 200
    assert response.json()["status"] == "not_found"
