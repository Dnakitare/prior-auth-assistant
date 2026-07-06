"""Database configuration and session management."""

import os
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
    # Test runs under pytest-asyncio use function-scoped event loops; asyncpg
    # connections held in a shared pool end up orphaned when the loop closes,
    # producing "Event loop is closed" crashes on the next test. NullPool
    # disables pooling — each session opens and closes a fresh connection
    # bound to the current test's loop. Opt in via env var so production
    # keeps the pool.
    if os.environ.get("DATABASE_USE_NULLPOOL") == "1":
        from sqlalchemy.pool import NullPool
        kwargs.pop("pool_size", None)
        kwargs.pop("max_overflow", None)
        kwargs.pop("pool_timeout", None)
        kwargs.pop("pool_recycle", None)
        kwargs["poolclass"] = NullPool
    return kwargs


engine = create_async_engine(settings.database_url, **_engine_kwargs())

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Admin engine/session: used by system paths (auth-time API-key lookup,
# bootstrap seeder, audit writer, webhook worker) that legitimately need
# cross-tenant visibility. The role behind DATABASE_ADMIN_URL must carry
# BYPASSRLS (or be superuser): since migration 006 the RLS policies have no
# GUC escape hatch, so bypass is a role attribute the runtime role cannot
# self-grant — an attacker who leaks the runtime DSN cannot promote to admin.
# When DATABASE_ADMIN_URL is unset we fall back to the runtime engine, which
# only works where RLS doesn't bind (SQLite dev/tests, superuser dev DBs);
# the production validator requires it on Postgres.
def _admin_engine_kwargs() -> dict:
    kwargs = _engine_kwargs()
    # Smaller pool — admin path is low-traffic (bootstrap + a handful of
    # worker ticks per second). Keep connections cheap. Skip when tests
    # forced NullPool: pool sizing args are invalid there.
    if kwargs.get("poolclass") is None:
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


async def get_admin_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for admin-scoped routes (require_scope("admin")).

    Runs on the admin engine: global admins legitimately create/list/revoke
    resources across orgs, which the runtime role cannot do since migration
    006 removed the GUC bypass. Tenant scoping for org-bound admins is
    enforced in the route handlers' explicit org filters; RLS is not the
    control on this path — the admin scope check is.
    """
    async with async_admin_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
