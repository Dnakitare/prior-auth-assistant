"""Pytest configuration and fixtures.

Tests run against a real SQLite database (aiosqlite) with the full schema
created via SQLAlchemy metadata, seeded with an API key and org. This
mirrors how auth actually works in production (DB-backed) — no mocks —
so the tests exercise cross-tenant filtering, revocation, and encryption.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio

# --- Environment (must be set BEFORE importing application modules) -------
# Two supported backends:
#   * SQLite (default for fast local runs)
#   * Postgres (CI job; required to exercise RLS enforcement)
# If DATABASE_URL is already set and points at Postgres, we trust it and
# assume migrations have been applied externally (see .github/workflows/ci.yml).
_PRESET_DB_URL = os.environ.get("DATABASE_URL", "")
_USING_POSTGRES = _PRESET_DB_URL.startswith("postgresql")

if not _USING_POSTGRES:
    _TEST_DB_FILE = Path(__file__).resolve().parent / "test.db"
    if _TEST_DB_FILE.exists():
        _TEST_DB_FILE.unlink()
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_FILE}"

# Generate a Fernet key inline so tests don't require operator setup.
from cryptography.fernet import Fernet as _Fernet  # noqa: E402

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DEBUG", "true")
# Force NullPool for tests — pytest-asyncio's function-scoped event loops
# otherwise leave pooled asyncpg connections attached to closed loops.
os.environ.setdefault("DATABASE_USE_NULLPOOL", "1")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-key-for-testing")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-" + "x" * 32)
os.environ.setdefault("AUDIT_HMAC_KEY", "test-audit-hmac-key-" + "y" * 32)
os.environ.setdefault("PHI_ENCRYPTION_KEYS", _Fernet.generate_key().decode())
os.environ.setdefault("RATE_LIMIT_BACKEND", "memory")

# ---------------------------------------------------------------------------
from httpx import ASGITransport, AsyncClient  # noqa: E402

from src.api.main import app  # noqa: E402
from src.core import database as _database_module  # noqa: E402
from src.core.database import Base, async_session_maker as _original_session_maker, engine  # noqa: E402


# Test-only session wrapper: opens an admin-context session so direct
# fixture inserts aren't blocked by Postgres RLS. Production code paths
# that need tenant scoping go through FastAPI's get_session dependency,
# which is independent of this wrapper. Tests that specifically need a
# non-admin context (e.g., tests/test_rls.py) override inside their own
# session body.
class _AdminContextSession:
    def __init__(self, inner_cm):
        self._inner_cm = inner_cm
        self._session = None

    async def __aenter__(self):
        self._session = await self._inner_cm.__aenter__()
        from src.core.security import set_rls_context
        await set_rls_context(self._session, org_id=None, is_admin=True, source="test")
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return await self._inner_cm.__aexit__(exc_type, exc, tb)


def _test_session_maker(*args, **kwargs):
    return _AdminContextSession(_original_session_maker(*args, **kwargs))


# Replace the module-level attribute so test imports of the form
# `from src.core.database import async_session_maker` resolve to the
# admin-context wrapper. Must happen before any test module is imported.
_database_module.async_session_maker = _test_session_maker
async_session_maker = _test_session_maker
from src.core.db_models import (  # noqa: E402,F401
    ApiKeyRecord,
    AppealRecord,
    AuditLogRecord,
    PayerRecord,
    PayerRuleRecord,
    UserSessionRecord,
)
from src.core.models import (  # noqa: E402
    AppealLetter,
    DenialExtraction,
    DenialReason,
    PatientContext,
)
from src.core.security import AuthenticatedUser, hash_api_key  # noqa: E402


TEST_API_KEY_ORG_A = "test-org-A"
TEST_API_KEY_ORG_B = "test-org-B"
TEST_PLAINTEXT_KEY_A = "pa_test-api-key-A"
TEST_PLAINTEXT_KEY_B = "pa_test-api-key-B"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _init_schema():
    """Schema + seed. On SQLite we create tables from metadata; on Postgres
    we assume migrations have already run (CI applies them before pytest).
    Either way, we seed two tenants and bypass RLS via the admin context so
    the seed rows land in the table regardless of policies."""
    from src.core.security import set_rls_context

    if _USING_POSTGRES:
        # Wipe any state left by a prior run so tests are deterministic.
        from sqlalchemy import text

        async with engine.begin() as conn:
            for table in [
                "webhook_deliveries",
                "webhook_endpoints",
                "audit_log",
                "appeals",
                "org_quotas",
                "user_sessions",
                "api_keys",
                "payer_rules",
                "payers",
            ]:
                await conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as db:
        # Seed with the admin context active so RLS (if enabled) allows the write.
        await set_rls_context(db, org_id=None, is_admin=True, source="test")
        db.add(
            ApiKeyRecord(
                id=str(uuid.uuid4()),
                key_hash=hash_api_key(TEST_PLAINTEXT_KEY_A),
                org_id=TEST_API_KEY_ORG_A,
                name="test-A",
                scopes=["appeals:read", "appeals:write"],
                created_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            ApiKeyRecord(
                id=str(uuid.uuid4()),
                key_hash=hash_api_key(TEST_PLAINTEXT_KEY_B),
                org_id=TEST_API_KEY_ORG_B,
                name="test-B",
                scopes=["appeals:read", "appeals:write"],
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    yield

    await engine.dispose()
    if _TEST_DB_FILE.exists():
        _TEST_DB_FILE.unlink()


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """ASGI async client that skips lifespan (we manage schema explicitly)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def auth_headers() -> dict:
    """Headers authenticating as tenant A."""
    return {"X-API-Key": TEST_PLAINTEXT_KEY_A}


@pytest.fixture
def auth_headers_b() -> dict:
    """Headers authenticating as tenant B (for cross-tenant tests)."""
    return {"X-API-Key": TEST_PLAINTEXT_KEY_B}


@pytest.fixture
def mock_authenticated_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id="test-user-123",
        org_id=TEST_API_KEY_ORG_A,
        scopes=["appeals:read", "appeals:write"],
        auth_method="api_key",
    )


@pytest.fixture
def sample_denial_extraction() -> DenialExtraction:
    return DenialExtraction(
        payer_name="Blue Cross Blue Shield",
        denial_date=datetime(2024, 12, 1),
        denial_reason=DenialReason.MEDICAL_NECESSITY,
        denial_reason_text="The requested service does not meet medical necessity criteria",
        procedure_codes=["99213", "99214"],
        diagnosis_codes=["M54.5", "G89.29"],
        member_id="MEM123456789",
        claim_number="CLM987654321",
        appeal_deadline=datetime(2025, 6, 1),
        raw_text=(
            "Sample denial letter text with codes 99213, 99214 and M54.5, G89.29 "
            "for member MEM123456789 claim CLM987654321"
        ),
    )


@pytest.fixture
def sample_patient_context() -> PatientContext:
    return PatientContext(
        patient_name="John Doe",
        date_of_birth="1980-01-15",
        member_id="MEM123456789",
        procedure_code="99213",
        procedure_description="Office visit, established patient",
        diagnosis_codes=["M54.5", "G89.29"],
        clinical_notes="Patient presents with chronic lower back pain.",
        prior_treatments=["Physical therapy", "NSAIDs", "Muscle relaxants"],
        treating_physician="Dr. Jane Smith",
    )


@pytest.fixture
def sample_appeal_letter(sample_denial_extraction) -> AppealLetter:
    return AppealLetter(
        id=str(uuid.uuid4()),
        denial_extraction=sample_denial_extraction,
        letter_content="Dear Sir/Madam,\n\nI am writing to appeal for patient MEM123456789...",
        required_attachments=["Letter of medical necessity", "Clinical notes"],
        generated_at=datetime.now(timezone.utc),
        confidence_score=0.85,
    )


@pytest.fixture
def mock_llm_client():
    from unittest.mock import AsyncMock
    mock = AsyncMock()
    mock.extract_denial_info = AsyncMock()
    mock.generate_appeal = AsyncMock()
    return mock


@pytest.fixture
def mock_ocr_provider():
    from unittest.mock import AsyncMock
    mock = AsyncMock()
    mock.extract_text = AsyncMock(return_value="Sample denial letter text...")
    return mock


@pytest.fixture
def sample_denial_text() -> str:
    return (
        "Blue Cross Blue Shield\nClaims Department\n\n"
        "Date: December 1, 2024\n\n"
        "RE: Denial of Prior Authorization\n"
        "Member ID: MEM123456789\n"
        "Claim Number: CLM987654321\n\n"
        "Dear Member,\n\n"
        "Your request for prior authorization for the following service has been denied:\n\n"
        "Procedure: 99213 - Office visit, established patient\n"
        "Diagnosis: M54.5 - Low back pain\n\n"
        "Reason for Denial: The requested service does not meet medical necessity "
        "criteria based on the clinical information provided.\n\n"
        "You have the right to appeal this decision within 180 days of this notice.\n\n"
        "Sincerely,\nMedical Review Department\n"
    )
