"""OCR integration for document processing.

Claude reads PDFs and images directly via document/image content blocks, so the
full pipeline is OCR → extraction → enhancement against a single vendor. The
mock provider returns a deterministic synthetic denial letter for offline
development.
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod

import anthropic
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.config import settings

logger = structlog.get_logger()


class OCRError(Exception):
    """Raised when OCR extraction fails."""


# Claude accepts these image media types directly. PDFs go through the
# document content block; everything else needs upstream conversion.
_IMAGE_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_PDF_MEDIA_TYPE = "application/pdf"


def _detect_media_type(document_bytes: bytes) -> str:
    head = document_bytes[:16]
    if head.startswith(b"%PDF-"):
        return _PDF_MEDIA_TYPE
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    raise OCRError("Unsupported document format for OCR (need PDF, PNG, JPEG, GIF, or WebP)")


class OCRProvider(ABC):
    """Abstract base class for OCR providers."""

    @abstractmethod
    async def extract_text(self, document_bytes: bytes) -> str:
        """Extract text from a document."""


class ClaudeOCRProvider(OCRProvider):
    """OCR via Claude's document/image content blocks.

    One vendor for OCR + extraction + enhancement keeps the pipeline simple
    and removes the second BAA scope item that AWS Textract used to add.
    """

    _OCR_INSTRUCTION = (
        "Extract every line of text from this document verbatim. "
        "Preserve line breaks. Do not summarize, paraphrase, or comment. "
        "Return only the extracted text."
    )

    def __init__(self, api_key: str | None = None) -> None:
        key = (api_key or settings.anthropic_api_key or "").strip()
        if not key:
            raise OCRError("ANTHROPIC_API_KEY is not configured for ClaudeOCRProvider")
        self.client = anthropic.AsyncAnthropic(api_key=key)
        self.model = settings.llm_model

    @retry(
        retry=retry_if_exception_type(
            (anthropic.RateLimitError, anthropic.APIConnectionError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def extract_text(self, document_bytes: bytes) -> str:
        log = logger.bind(doc_size=len(document_bytes))
        log.info("Starting Claude OCR extraction")

        media_type = _detect_media_type(document_bytes)
        b64 = base64.b64encode(document_bytes).decode("ascii")

        if media_type == _PDF_MEDIA_TYPE:
            doc_block = {
                "type": "document",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            }
        else:
            doc_block = {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            }

        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=settings.llm_max_tokens_ocr,
                # Verbatim transcription needs no reasoning; Sonnet 5 would
                # otherwise run adaptive thinking by default (latency + cost).
                thinking={"type": "disabled"},
                messages=[
                    {
                        "role": "user",
                        "content": [doc_block, {"type": "text", "text": self._OCR_INSTRUCTION}],
                    }
                ],
            )
        except anthropic.APIStatusError as e:
            log.error("Claude OCR failed", status_code=e.status_code, error=str(e))
            raise OCRError(f"Claude OCR API error: {e.status_code}") from e

        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        ).strip()

        log.info("OCR complete", char_count=len(text))
        if not text:
            raise OCRError("No text extracted from document")
        return text


class MockOCRProvider(OCRProvider):
    """Mock OCR provider for testing without API access."""

    async def extract_text(self, document_bytes: bytes) -> str:
        logger.info("Using mock OCR provider")
        return """
INSURANCE COMPANY NAME: Blue Cross Blue Shield
CLAIMS DEPARTMENT
123 Insurance Way
Anytown, ST 12345

Date: December 15, 2024

RE: DENIAL OF PRIOR AUTHORIZATION
Member Name: John Smith
Member ID: BCB123456789
Claim Number: CLM-2024-987654
Date of Service: December 10, 2024

Dear Member,

This letter is to inform you that your request for prior authorization has been DENIED.

Procedure Requested: 27447 - Total Knee Arthroplasty
Diagnosis: M17.11 - Primary osteoarthritis, right knee

REASON FOR DENIAL:
Your request has been denied because the documentation provided does not demonstrate medical necessity for the requested procedure. Specifically, there is insufficient evidence that conservative treatments have been attempted and failed.

According to our clinical guidelines, total knee replacement requires documentation of:
- Failure of at least 3 months of conservative therapy
- Physical therapy records
- Documentation of pain medication usage
- Recent imaging showing severe joint deterioration

APPEAL RIGHTS:
You have the right to appeal this decision within 180 days of the date of this letter. To file an appeal, please submit:
1. A written request for appeal
2. Additional medical records supporting medical necessity
3. Letter of medical necessity from treating physician

Appeals should be sent to:
Blue Cross Blue Shield Appeals Department
PO Box 54321
Anytown, ST 12345

If you have questions about this denial, please call Member Services at 1-800-555-0123.

Sincerely,

Medical Review Department
Blue Cross Blue Shield
"""


def get_ocr_provider() -> OCRProvider:
    """Default OCR provider, keyed off settings.anthropic_api_key.

    Falls back to the mock when no Anthropic API key is configured (local
    development without credentials).
    """
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not configured, using mock OCR provider")
        return MockOCRProvider()
    return ClaudeOCRProvider()


def make_byok_ocr_provider(api_key: str) -> OCRProvider:
    """One-shot OCR provider for a per-request BYOK key. Not cached."""
    return ClaudeOCRProvider(api_key=api_key)
