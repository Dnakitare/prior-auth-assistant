"""File upload content validation.

Client-declared Content-Type is not trusted. Instead, we sniff the first bytes
of the file and match against the magic numbers for PDF, PNG, JPEG, and TIFF.
"""

from __future__ import annotations

from dataclasses import dataclass


class UnsupportedFileType(ValueError):
    """File did not match any supported magic-number signature."""


@dataclass(frozen=True)
class DetectedType:
    mime: str
    extension: str


_SIGNATURES: list[tuple[bytes, DetectedType]] = [
    (b"%PDF-", DetectedType("application/pdf", "pdf")),
    (b"\x89PNG\r\n\x1a\n", DetectedType("image/png", "png")),
    (b"\xff\xd8\xff", DetectedType("image/jpeg", "jpg")),
    (b"II*\x00", DetectedType("image/tiff", "tif")),  # little-endian
    (b"MM\x00*", DetectedType("image/tiff", "tif")),  # big-endian
]


def detect_type(data: bytes) -> DetectedType:
    """Return the detected type or raise UnsupportedFileType."""
    head = data[:16]
    for signature, detected in _SIGNATURES:
        if head.startswith(signature):
            return detected
    raise UnsupportedFileType(
        "File content does not match supported types (PDF, PNG, JPEG, TIFF)."
    )


def safe_filename(raw: str | None) -> str:
    """Strip path components for safe logging. Does not sanitize for filesystem use."""
    if not raw:
        return "(unnamed)"
    # Keep only the basename; also reject control chars.
    base = raw.replace("\\", "/").rsplit("/", 1)[-1]
    return "".join(c for c in base if 32 <= ord(c) < 127)[:255] or "(unnamed)"
