"""Per-org token budget enforcement.

Daily rolling window. Operators can set a per-org override in `org_quotas`;
unknown orgs fall back to `settings.org_daily_token_budget`. Budget of 0
means unlimited.

Implementation is an in-session `SELECT … FOR UPDATE` + `UPDATE` to serialize
concurrent writers. Acceptable for the volumes expected here; if contention
becomes a bottleneck, replace with a Redis INCR + expire pattern.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.db_models import OrgQuotaRecord


class QuotaExceeded(RuntimeError):
    def __init__(self, org_id: str, used: int, budget: int) -> None:
        super().__init__(f"org {org_id} daily token budget exceeded: {used}/{budget}")
        self.org_id = org_id
        self.used = used
        self.budget = budget


@dataclass
class QuotaStatus:
    budget: int  # 0 == unlimited
    used_today: int
    used_month: int
    remaining_today: int  # -1 if unlimited


async def check_and_reserve(
    session: AsyncSession, *, org_id: str, tokens: int
) -> QuotaStatus:
    """Reserve `tokens` against the org's daily budget, or raise QuotaExceeded.

    "Reserve" is eager: we count the tokens *before* the LLM call, so a
    budget-exceeding call fails fast. If the actual call uses fewer tokens,
    we effectively under-count utilization slightly — acceptable. If it uses
    *more* than planned, the next call sees the accumulated total and will
    be rejected; we do not refund on undercount.
    """
    now = datetime.now(timezone.utc)
    # Lock the row for the remainder of the transaction so two concurrent
    # callers in the same org serialize here. Postgres: row-level lock.
    # SQLite (tests): with_for_update is a no-op — concurrent writes aren't
    # an issue in the test fixtures we run against SQLite.
    row = await session.get(
        OrgQuotaRecord, org_id, with_for_update=True
    )
    if row is None:
        row = OrgQuotaRecord(
            org_id=org_id,
            daily_token_budget=settings.org_daily_token_budget,
            tokens_used_today=0,
            tokens_used_month=0,
            day_window_start=now,
            month_window_start=now,
        )
        session.add(row)

    # Roll the daily and monthly windows.
    if _day_start(row.day_window_start) < _day_start(now):
        row.tokens_used_today = 0
        row.day_window_start = now
    if _month_start(row.month_window_start) < _month_start(now):
        row.tokens_used_month = 0
        row.month_window_start = now

    budget = row.daily_token_budget or settings.org_daily_token_budget
    if budget > 0 and row.tokens_used_today + tokens > budget:
        raise QuotaExceeded(org_id, row.tokens_used_today, budget)

    row.tokens_used_today += tokens
    row.tokens_used_month += tokens
    await session.flush()

    remaining = -1 if budget == 0 else max(budget - row.tokens_used_today, 0)
    return QuotaStatus(
        budget=budget,
        used_today=row.tokens_used_today,
        used_month=row.tokens_used_month,
        remaining_today=remaining,
    )


def _day_start(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(ts: datetime) -> datetime:
    d = _day_start(ts)
    return d.replace(day=1)


def _next_day(ts: datetime) -> datetime:
    return _day_start(ts) + timedelta(days=1)
