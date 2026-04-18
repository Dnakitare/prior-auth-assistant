"""Field-level encryption for PHI at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256). MultiFernet enables key rotation:
all configured keys are tried for decryption; the first key is used for
new writes. Rotate by prepending a new key and scheduling a rewrite job.

Keys come from settings.phi_encryption_keys (comma-separated env).
Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import String, Text
from sqlalchemy.types import TypeDecorator

from src.core.config import settings


class PHIEncryptionError(RuntimeError):
    """Raised when encryption/decryption fails."""


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    keys = settings.phi_encryption_keys
    if not keys:
        # Non-production dev convenience: derive an ephemeral key so tests run.
        # Production validator in config rejects empty keys.
        if settings.is_production:
            raise PHIEncryptionError("PHI_ENCRYPTION_KEYS is not configured")
        keys = [Fernet.generate_key().decode()]
    instances = []
    for raw in keys:
        try:
            instances.append(Fernet(raw.encode() if isinstance(raw, str) else raw))
        except Exception as e:
            raise PHIEncryptionError(f"invalid Fernet key: {e}") from e
    return MultiFernet(instances)


def encrypt_str(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_str(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise PHIEncryptionError("ciphertext failed integrity check") from e


class _EncryptedMixin:
    """Shared bind/result logic. Ciphertext is ASCII-safe base64."""

    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        return encrypt_str(value)

    def process_result_value(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None
        return decrypt_str(value)


class EncryptedText(_EncryptedMixin, TypeDecorator):
    """Encrypted variable-length text column."""

    impl = Text


class EncryptedString(_EncryptedMixin, TypeDecorator):
    """Encrypted bounded-length string column.

    Note: ciphertext is ~1.4× plaintext; size the column generously or
    use EncryptedText when length is uncertain.
    """

    impl = String

    def __init__(self, length: int = 512, *args, **kwargs):
        super().__init__(length, *args, **kwargs)
