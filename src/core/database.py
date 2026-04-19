"""Database configuration and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.core.config import settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


def _engine_kwargs() -> dict:
    """Build engine kwargs. Adds Postgres-specific statement timeout when the
    URL targets asyncpg; SQLite (tests) ignores these.
    """
    kwargs: dict = dict(
        echo=settings.debug,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
    )
    if settings.database_url.startswith("postgresql+asyncpg"):
        # asyncpg server-side settings: kill runaway queries / idle tx.
        kwargs["connect_args"] = {
            "server_settings": {
                "statement_timeout": "30000",  # 30 seconds
                "idle_in_transaction_session_timeout": "60000",  # 1 minute
                "application_name": settings.app_name,
            }
        }
    return kwargs


engine = create_async_engine(settings.database_url, **_engine_kwargs())

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Admin engine/session: used by system paths (bootstrap seeder, webhook
# worker, scheduled background jobs) that legitimately need cross-tenant
# visibility. When DATABASE_ADMIN_URL is unset, we reuse the runtime engine
# and rely on the app explicitly calling set_rls_context(is_admin=True).
# When set, operators can deploy a distinct Postgres role with BYPASSRLS —
# an attacker who leaks the runtime DSN still can't promote to admin.
def _admin_engine_kwargs() -> dict:
    kwargs = _engine_kwargs()
    # Smaller pool — admin path is low-traffic (bootstrap + a handful of
    # worker ticks per second). Keep connections cheap.
    kwargs["pool_size"] = 2
    kwargs["max_overflow"] = 4
    return kwargs


if settings.database_admin_url:
    admin_engine = create_async_engine(settings.database_admin_url, **_admin_engine_kwargs())
    async_admin_session_maker = async_sessionmaker(
        admin_engine, class_=AsyncSession, expire_on_commit=False
    )
else:
    admin_engine = engine
    async_admin_session_maker = async_session_maker


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: per-request DB session with commit-on-success / rollback-on-error."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
