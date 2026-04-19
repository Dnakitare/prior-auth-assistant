"""HIPAA-compliant audit log with HMAC-chained integrity.

Every audit event is persisted to the audit_log table. Each row stores:
- row_hmac = HMAC-SHA256(audit_hmac_key, prev_hmac || canonical_event_json)
- prev_hmac = the previous row's row_hmac (None for genesis)

Tamper verification iterates rows in sequence order and recomputes row_hmac.
Any divergence proves insertion/deletion/modification. Rows also continue to
emit to structlog for log shipping and real-time alerting.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit_sink import get_audit_sink
from src.core.config import settings
from src.core.db_models import AuditLogRecord
from src.core.metrics import audit_write_failures_total

audit_logger = structlog.get_logger("audit")


class AuditAction(str, Enum):
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILURE = "auth.login.failure"
    LOGOUT = "auth.logout"
    TOKEN_REFRESH = "auth.token.refresh"

    APPEAL_CREATE = "appeal.create"
    APPEAL_READ = "appeal.read"
    APPEAL_UPDATE = "appeal.update"
    APPEAL_DELETE = "appeal.delete"
    APPEAL_EXPORT = "appeal.export"

    DOCUMENT_UPLOAD = "document.upload"
    DOCUMENT_OCR = "document.ocr"

    PATIENT_DATA_ACCESS = "patient.data.access"
    PATIENT_DATA_MODIFY = "patient.data.modify"

    API_KEY_CREATE = "admin.apikey.create"
    API_KEY_REVOKE = "admin.apikey.revoke"
    SETTINGS_CHANGE = "admin.settings.change"


def _canonical(event: dict[str, Any]) -> bytes:
    """Deterministic byte representation of an event for HMAC input."""
    return json.dumps(event, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _normalize_ts(ts: datetime) -> str:
    """Canonicalize a timestamp to tz-aware UTC ISO. Tolerates DBs that drop tz."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def _hmac(prev: str | None, event_bytes: bytes) -> str:
    key = settings.audit_hmac_key.encode("utf-8")
    mac = hmac.new(key, digestmod=hashlib.sha256)
    mac.update((prev or "").encode("ascii"))
    mac.update(b"|")
    mac.update(event_bytes)
    return mac.hexdigest()


MAX_SEQUENCE_RETRIES = 5


class AuditLogger:
    async def log(
        self,
        *,
        db: AsyncSession,
        action: AuditAction,
        user_id: str | None = None,
        org_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        contains_phi: bool = False,
        phi_types: list[str] | None = None,
        **metadata: Any,
    ) -> AuditLogRecord:
        """Persist an audit row, linking it into the HMAC chain, and emit a log line.

        Concurrency model: sequence + prev_hmac are computed from the current
        tail. Two concurrent writers can compute the same next sequence; the
        unique constraint on sequence rejects the loser. We retry by wrapping
        the whole compute+insert in a savepoint (SQLAlchemy nested transaction)
        so the outer transaction survives the integrity error.
        """
        timestamp = datetime.now(timezone.utc)
        event_core = {
            "action": action.value,
            "timestamp": _normalize_ts(timestamp),
            "user_id": user_id,
            "org_id": org_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "request_id": request_id,
            "success": success,
            "error_message": error_message,
            "contains_phi": contains_phi,
            "phi_types": phi_types or [],
            "metadata": metadata,
        }

        last_error: Exception | None = None
        for attempt in range(MAX_SEQUENCE_RETRIES):
            # Re-read the tail every attempt: on a conflict the winner has
            # incremented sequence and we must re-link to their row_hmac.
            tail = await db.execute(
                select(AuditLogRecord.row_hmac, AuditLogRecord.sequence)
                .order_by(AuditLogRecord.sequence.desc())
                .limit(1)
            )
            tail_row = tail.first()
            prev = tail_row[0] if tail_row else None
            next_sequence = (tail_row[1] + 1) if tail_row else 1
            row_hmac = _hmac(prev, _canonical(event_core))

            record = AuditLogRecord(
                id=str(uuid.uuid4()),
                sequence=next_sequence,
                timestamp=timestamp,
                action=action.value,
                user_id=user_id,
                org_id=org_id,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                success=success,
                error_message=error_message,
                contains_phi=contains_phi,
                phi_types=phi_types or [],
                metadata_json=metadata,
                prev_hmac=prev,
                row_hmac=row_hmac,
            )

            # Savepoint so the outer transaction survives conflicts.
            try:
                async with db.begin_nested():
                    db.add(record)
            except IntegrityError as e:
                last_error = e
                audit_logger.debug(
                    "audit_sequence_conflict",
                    attempt=attempt + 1,
                    sequence=next_sequence,
                )
                continue

            if success:
                audit_logger.info("audit_event", **event_core)
            else:
                audit_logger.warning("audit_event", **event_core)
            # Ship to external sink (CloudWatch or no-op). Enqueue only —
            # delivery happens asynchronously and cannot block this path.
            await get_audit_sink().ship(
                {**event_core, "sequence": next_sequence, "row_hmac": row_hmac}
            )
            return record

        raise RuntimeError(
            f"audit log sequence contention after {MAX_SEQUENCE_RETRIES} retries"
        ) from last_error

    async def safe_log(self, **kwargs: Any) -> AuditLogRecord | None:
        """Best-effort audit. Logs failures to structlog but never raises.

        Use this from HTTP handlers where a failed audit must not roll back
        the business transaction. The structlog line (emitted by `log`) is
        still produced on failure; an external log shipper picks it up even
        when the DB row can't be written.
        """
        try:
            return await self.log(**kwargs)
        except Exception as e:
            audit_write_failures_total.inc()
            audit_logger.error(
                "audit_db_write_failed",
                error=str(e),
                error_type=type(e).__name__,
                action=kwargs.get("action").value if kwargs.get("action") else None,
                user_id=kwargs.get("user_id"),
                resource_id=kwargs.get("resource_id"),
            )
            return None

    async def verify_chain(self, db: AsyncSession) -> tuple[bool, int | None]:
        """Recompute the chain. Return (ok, first_bad_sequence).

        O(n) scan. Intended for scheduled integrity checks, not per-request.
        """
        prev: str | None = None
        result = await db.execute(
            select(AuditLogRecord).order_by(AuditLogRecord.sequence.asc())
        )
        for row in result.scalars().all():
            event = {
                "action": row.action,
                "timestamp": _normalize_ts(row.timestamp),
                "user_id": row.user_id,
                "org_id": row.org_id,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "ip_address": row.ip_address,
                "user_agent": row.user_agent,
                "request_id": row.request_id,
                "success": row.success,
                "error_message": row.error_message,
                "contains_phi": row.contains_phi,
                "phi_types": row.phi_types or [],
                "metadata": row.metadata_json or {},
            }
            expected = _hmac(prev, _canonical(event))
            if not hmac.compare_digest(expected, row.row_hmac) or row.prev_hmac != prev:
                return False, row.sequence
            prev = row.row_hmac
        return True, None


audit = AuditLogger()
