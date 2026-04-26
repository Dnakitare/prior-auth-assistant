"""Application configuration with validation."""

import secrets
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_JWT_SECRET_UNSET_SENTINEL = "__unset__"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_env: Literal["development", "staging", "production"] = Field(default="development")
    app_name: str = Field(default="Prior Authorization Assistant")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # Security - JWT
    # In non-prod we generate an ephemeral key for convenience. In prod, the
    # production validator below rejects the sentinel outright.
    jwt_secret_key: str = Field(default=_JWT_SECRET_UNSET_SENTINEL)
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiration_hours: int = Field(default=24, ge=1, le=168)
    session_cleanup_interval_minutes: int = Field(default=60, ge=5)

    # Security - CORS
    cors_origins: Annotated[list[str], NoDecode] = Field(default=["http://localhost:3000"])

    # Security - Rate Limiting
    rate_limit_backend: Literal["redis", "memory"] = Field(default="memory")
    rate_limit_requests: int = Field(default=100, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    # Trusted proxy CIDRs/IPs that are allowed to set X-Forwarded-For.
    # Empty = do not trust the header at all.
    trusted_proxies: Annotated[list[str], NoDecode] = Field(default=[])

    # Security - HTTPS / transport
    require_https: bool = Field(default=False)

    # Security - PHI encryption. Generate via:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Multiple keys (comma-separated) enable rotation; first is used for new writes,
    # all are tried for reads (MultiFernet).
    phi_encryption_keys: Annotated[list[str], NoDecode] = Field(default=[])

    # Security - Audit log HMAC (for tamper-evident chain). Distinct from JWT secret.
    audit_hmac_key: str = Field(default=_JWT_SECRET_UNSET_SENTINEL)

    # Bootstrap API keys (seeded into DB on first startup). Comma-separated.
    # After first run, manage keys via the DB/admin endpoint and clear this var.
    bootstrap_api_keys: Annotated[list[str], NoDecode] = Field(default=[])
    bootstrap_api_key_org: str = Field(default="system")

    # LLM / AI
    anthropic_api_key: str = Field(default="")
    llm_model: str = Field(default="claude-sonnet-4-20250514")
    llm_max_tokens_extraction: int = Field(default=1024, ge=64)
    llm_max_tokens_generation: int = Field(default=2500, ge=256)
    # Verbatim OCR responses can be longer than structured extraction.
    llm_max_tokens_ocr: int = Field(default=4096, ge=256)
    # Cap on total input characters passed to the model per request, before delimiters.
    llm_max_input_chars: int = Field(default=50000, ge=1000)

    # AWS region — used only by the optional CloudWatch audit sink. Leave
    # blank to disable boto3 entirely. Textract was previously used for OCR
    # but has been replaced by Claude's document content blocks.
    aws_region: str = Field(default="us-east-1")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://prior_auth:prior_auth_dev@localhost:5432/prior_auth",
    )
    # Optional: separate connection URL for privileged system paths (bootstrap
    # seeder, webhook worker, admin bypass operations). When set, should point
    # at a Postgres role that has BYPASSRLS (or equivalent) while the primary
    # database_url points at a restricted runtime role. Reduces the blast
    # radius of an API-replica compromise: an attacker who leaks the runtime
    # DSN still can't flip app.is_admin meaningfully because its role is
    # constrained. Falls back to database_url if unset.
    database_admin_url: str = Field(default="")
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout: int = Field(default=30, ge=1)

    # Redis (required when rate_limit_backend=redis)
    redis_url: str = Field(default="redis://localhost:6379/0")

    # File upload
    max_upload_size_mb: int = Field(default=10, ge=1, le=100)

    # External audit sink. When set, audit events are also shipped to a
    # CloudWatch Logs group alongside the in-DB HMAC chain. Create the log
    # group in advance with a retention lock (or a subscription filter that
    # writes to S3 Object Lock) for tamper-evidence under application RCE.
    audit_sink_cloudwatch_group: str = Field(default="")

    # Per-org LLM token budget (in tokens). 0 = no enforcement. Applies to
    # both extraction and generation calls, summed.
    org_daily_token_budget: int = Field(default=0, ge=0)

    # Webhook delivery
    webhook_delivery_timeout_seconds: int = Field(default=5, ge=1, le=60)
    webhook_max_attempts: int = Field(default=5, ge=1, le=20)

    # OpenTelemetry tracing. When set, FastAPI + SQLAlchemy + httpx are
    # instrumented and spans are exported to the OTLP endpoint.
    otel_exporter_otlp_endpoint: str = Field(default="")
    otel_service_name: str = Field(default="prior-auth-assistant")

    # Health check: when true, /health calls Anthropic for real (costs tokens
    # per invocation). Usually false; monitoring should use /health/live.
    health_check_llm_live: bool = Field(default=False)

    # Operational: run alembic migrations at app startup. Disable in
    # multi-replica deployments and run migrations as a separate init-container
    # or CI job (scripts/migrate.py) instead.
    migrate_on_startup: bool = Field(default=True)

    @field_validator(
        "cors_origins",
        "trusted_proxies",
        "phi_encryption_keys",
        "bootstrap_api_keys",
        mode="before",
    )
    @classmethod
    def parse_csv_list(cls, v):
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @model_validator(mode="after")
    def finalize_jwt_secret(self):
        """Development convenience: if JWT secret is unset outside production, mint one."""
        if self.jwt_secret_key == _JWT_SECRET_UNSET_SENTINEL and self.app_env != "production":
            object.__setattr__(self, "jwt_secret_key", secrets.token_urlsafe(32))
        if self.audit_hmac_key == _JWT_SECRET_UNSET_SENTINEL and self.app_env != "production":
            object.__setattr__(self, "audit_hmac_key", secrets.token_urlsafe(32))
        return self

    @model_validator(mode="after")
    def validate_production_settings(self):
        """Fail closed on missing production-critical configuration."""
        if self.app_env != "production":
            return self

        errors: list[str] = []

        if self.jwt_secret_key == _JWT_SECRET_UNSET_SENTINEL:
            errors.append("JWT_SECRET_KEY must be explicitly set in production")
        elif len(self.jwt_secret_key) < 32:
            errors.append("JWT_SECRET_KEY must be at least 32 characters in production")

        if self.audit_hmac_key == _JWT_SECRET_UNSET_SENTINEL:
            errors.append("AUDIT_HMAC_KEY must be explicitly set in production")
        elif len(self.audit_hmac_key) < 32:
            errors.append("AUDIT_HMAC_KEY must be at least 32 characters in production")

        if self.audit_hmac_key == self.jwt_secret_key and self.jwt_secret_key != _JWT_SECRET_UNSET_SENTINEL:
            errors.append("AUDIT_HMAC_KEY must not equal JWT_SECRET_KEY")

        if not self.phi_encryption_keys:
            errors.append("PHI_ENCRYPTION_KEYS must be set in production (comma-separated Fernet keys)")

        if self.debug:
            errors.append("DEBUG must be False in production")

        if not self.anthropic_api_key:
            errors.append("ANTHROPIC_API_KEY is required in production")

        if "*" in self.cors_origins:
            errors.append("CORS_ORIGINS must not contain '*' in production")
        if any("localhost" in o for o in self.cors_origins):
            errors.append("CORS_ORIGINS must not contain localhost in production")

        # Note: in-memory rate limiting is fine for single-replica deployments
        # (the portfolio demo target); for multi-replica production set
        # RATE_LIMIT_BACKEND=redis so the window is shared across processes.
        # We don't fail closed here because the single-replica path is a real
        # supported topology — the runbook calls this out explicitly.

        if not self.require_https:
            errors.append("REQUIRE_HTTPS must be true in production")

        if errors:
            raise ValueError("Production validation failed: " + "; ".join(errors))

        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
