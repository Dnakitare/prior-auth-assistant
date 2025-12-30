"""OCR integration for document processing."""

from abc import ABC, abstractmethod

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import settings

logger = structlog.get_logger()


class OCRError(Exception):
    """Raised when OCR extraction fails."""

    pass


class OCRProvider(ABC):
    """Abstract base class for OCR providers."""

    @abstractmethod
    async def extract_text(self, document_bytes: bytes) -> str:
        """Extract text from a document."""
        pass


class AWSTextractProvider(OCRProvider):
    """AWS Textract OCR provider."""

    def __init__(self) -> None:
        import boto3

        self.client = boto3.client(
            "textract",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def extract_text(self, document_bytes: bytes) -> str:
        """Extract text from a document using AWS Textract."""
        log = logger.bind(doc_size=len(document_bytes))
        log.info("Starting Textract extraction")

        try:
            response = self.client.detect_document_text(
                Document={"Bytes": document_bytes}
            )
        except Exception as e:
            log.error("Textract extraction failed", error=str(e))
            raise OCRError(f"Failed to extract text: {str(e)}") from e

        extracted_lines = []
        for block in response.get("Blocks", []):
            if block["BlockType"] == "LINE":
                extracted_lines.append(block["Text"])

        text = "\n".join(extracted_lines)
        log.info("Extraction complete", line_count=len(extracted_lines))

        if not text.strip():
            raise OCRError("No text extracted from document")

        return text


class MockOCRProvider(OCRProvider):
    """Mock OCR provider for testing without AWS credentials."""

    async def extract_text(self, document_bytes: bytes) -> str:
        """Return mock denial letter text for testing."""
        logger.info("Using mock OCR provider")

        # Return a sample denial letter for testing
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
    """Factory function to get the configured OCR provider."""
    # Use mock provider if AWS credentials are not configured
    if not settings.aws_access_key_id or not settings.aws_secret_access_key:
        logger.warning("AWS credentials not configured, using mock OCR provider")
        return MockOCRProvider()

    return AWSTextractProvider()
