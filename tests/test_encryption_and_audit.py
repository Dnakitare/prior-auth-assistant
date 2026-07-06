"""Tests for field-level PHI encryption and the HMAC-chained audit log."""

from __future__ import annotations

import uuid

import pytest

from src.core.audit import AuditAction, audit
# Direct DB inspection in tests uses the ADMIN session maker: since
# migration 006 the runtime role has no RLS bypass, so an org-less
# session would see zero rows on the Postgres CI job. (On SQLite the
# two makers are the same object.)
from src.core.database import async_admin_session_maker as async_session_maker
from src.core.db_models import AppealRecord, AuditLogRecord
from src.core.encryption import PHIEncryptionError, decrypt_str, encrypt_str


class TestEncryption:
    def test_roundtrip(self):
        pt = "Patient John Doe, DOB 1980-01-15, MEM9999"
        ct = encrypt_str(pt)
        assert ct != pt
        assert decrypt_str(ct) == pt

    def test_ciphertext_is_ascii(self):
        ct = encrypt_str("x")
        ct.encode("ascii")  # should not raise

    def test_tampered_ciphertext_rejected(self):
        ct = encrypt_str("hello")
        tampered = ct[:-1] + ("A" if ct[-1] != "A" else "B")
        with pytest.raises(PHIEncryptionError):
            decrypt_str(tampered)


class TestAppealRecordEncryption:
    @pytest.mark.asyncio
    async def test_phi_columns_encrypted_on_disk(self):
        """Write a record, then read the raw column via text SQL — it must not contain plaintext."""
        from sqlalchemy import text

        appeal_id = str(uuid.uuid4())
        plaintext = "PatientSecret12345"
        async with async_session_maker() as db:
            db.add(
                AppealRecord(
                    id=appeal_id,
                    created_by="u",
                    org_id="o",
                    patient_name=plaintext,
                    denial_reason="other",
                    appeal_letter="letter body",
                )
            )
            await db.commit()

        async with async_session_maker() as db:
            result = await db.execute(
                text("SELECT patient_name, appeal_letter FROM appeals WHERE id = :id"),
                {"id": appeal_id},
            )
            row = result.fetchone()

        raw_name, raw_letter = row
        assert plaintext not in raw_name, "plaintext patient_name leaked to disk"
        assert "letter body" not in raw_letter, "plaintext appeal_letter leaked to disk"

        # ORM round-trip decrypts transparently.
        async with async_session_maker() as db:
            record = await db.get(AppealRecord, appeal_id)
        assert record.patient_name == plaintext
        assert record.appeal_letter == "letter body"


class TestAuditChain:
    @pytest.mark.asyncio
    async def test_chain_verifies_after_writes(self):
        async with async_session_maker() as db:
            await audit.log(
                db=db,
                action=AuditAction.APPEAL_READ,
                user_id="u1",
                org_id="o1",
                resource_type="appeal",
                resource_id="a1",
            )
            await audit.log(
                db=db,
                action=AuditAction.APPEAL_CREATE,
                user_id="u1",
                org_id="o1",
                resource_type="appeal",
                resource_id="a2",
                contains_phi=True,
            )
            await db.commit()

        async with async_session_maker() as db:
            ok, bad_seq = await audit.verify_chain(db)
        assert ok, f"audit chain broken at sequence {bad_seq}"

    @pytest.mark.asyncio
    async def test_chain_detects_tampering(self):
        """Flip a byte in a stored row's action — the chain check must fail."""
        async with async_session_maker() as db:
            await audit.log(
                db=db,
                action=AuditAction.APPEAL_READ,
                user_id="tamper-user",
                resource_id="r",
            )
            await audit.log(
                db=db,
                action=AuditAction.APPEAL_CREATE,
                user_id="tamper-user",
                resource_id="r",
            )
            await db.commit()

        # Mutate an existing row's metadata; its row_hmac is no longer valid.
        from sqlalchemy import select

        async with async_session_maker() as db:
            result = await db.execute(
                select(AuditLogRecord).where(AuditLogRecord.user_id == "tamper-user")
            )
            rows = list(result.scalars().all())
            rows[0].resource_id = "tampered"
            await db.commit()

        async with async_session_maker() as db:
            ok, bad_seq = await audit.verify_chain(db)
        assert ok is False
        assert bad_seq is not None
