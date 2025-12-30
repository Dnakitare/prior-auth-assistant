"""OCR integration for document processing."""

from abc import ABC, abstractmethod

import boto3

from src.core.config import settings


class OCRProvider(ABC):
    """Abstract base class for OCR providers."""

    @abstractmethod
    async def extract_text(self, document_bytes: bytes) -> str:
        """Extract text from a document."""
        pass


class AWSTextractProvider(OCRProvider):
    """AWS Textract OCR provider."""

    def __init__(self) -> None:
        self.client = boto3.client(
            "textract",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )

    async def extract_text(self, document_bytes: bytes) -> str:
        """Extract text from a document using AWS Textract."""
        response = self.client.detect_document_text(Document={"Bytes": document_bytes})

        extracted_lines = []
        for block in response.get("Blocks", []):
            if block["BlockType"] == "LINE":
                extracted_lines.append(block["Text"])

        return "\n".join(extracted_lines)


def get_ocr_provider() -> OCRProvider:
    """Factory function to get the configured OCR provider."""
    return AWSTextractProvider()
