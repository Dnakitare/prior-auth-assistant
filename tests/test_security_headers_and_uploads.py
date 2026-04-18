"""Tests for security headers and upload magic-byte validation."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.core.upload_validation import UnsupportedFileType, detect_type, safe_filename


class TestSecurityHeaders:
    @pytest.mark.asyncio
    async def test_strict_csp_on_root(self, async_client: AsyncClient):
        response = await async_client.get("/")
        csp = response.headers["Content-Security-Policy"]
        # script-src must not allow unsafe-inline (that's the dangerous vector).
        assert "script-src 'self';" in csp
        assert "'unsafe-eval'" not in csp
        # img-src should not allow data: URIs (XSS vector).
        assert "data:" not in csp
        assert "img-src 'self' blob:" in csp
        assert "frame-ancestors 'none'" in csp
        assert "base-uri 'self'" in csp
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "Permissions-Policy" in response.headers

    @pytest.mark.asyncio
    async def test_request_id_echoed(self, async_client: AsyncClient):
        response = await async_client.get("/", headers={"X-Request-ID": "req-abc"})
        assert response.headers["X-Request-ID"] == "req-abc"


class TestUploadMagicBytes:
    def test_pdf_detected(self):
        detected = detect_type(b"%PDF-1.7\nblah")
        assert detected.mime == "application/pdf"

    def test_png_detected(self):
        detected = detect_type(b"\x89PNG\r\n\x1a\nrest")
        assert detected.mime == "image/png"

    def test_jpeg_detected(self):
        detected = detect_type(b"\xff\xd8\xffrest")
        assert detected.mime == "image/jpeg"

    def test_tiff_le_detected(self):
        assert detect_type(b"II*\x00rest").mime == "image/tiff"

    def test_tiff_be_detected(self):
        assert detect_type(b"MM\x00*rest").mime == "image/tiff"

    def test_unknown_rejected(self):
        with pytest.raises(UnsupportedFileType):
            detect_type(b"not a known format blah")

    def test_zip_disguised_as_pdf_rejected(self):
        # Client-declared MIME wouldn't save this file — the magic bytes are what matter.
        with pytest.raises(UnsupportedFileType):
            detect_type(b"PK\x03\x04 zip content")

    def test_safe_filename_strips_paths(self):
        assert safe_filename("../../etc/passwd") == "passwd"
        assert safe_filename("a\\b\\c.pdf") == "c.pdf"
        assert safe_filename(None) == "(unnamed)"

    def test_safe_filename_strips_control_chars(self):
        assert "\x00" not in safe_filename("bad\x00name")


class TestUploadEndpoint:
    @pytest.mark.asyncio
    async def test_upload_rejects_text_masquerading_as_pdf(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        """A .txt file with a PDF content-type still fails magic-byte check."""
        files = {"denial_letter": ("fake.pdf", b"this is plain text", "application/pdf")}
        response = await async_client.post(
            "/api/v1/appeals/upload", files=files, headers=auth_headers
        )
        assert response.status_code == 400
        assert "match" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_upload_unauthenticated(self, async_client: AsyncClient):
        files = {"denial_letter": ("x.pdf", b"%PDF-1.4", "application/pdf")}
        response = await async_client.post("/api/v1/appeals/upload", files=files)
        assert response.status_code == 401
