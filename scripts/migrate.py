"""Apply Alembic migrations against the configured database.

Intended for use as a CI step or init container when
MIGRATE_ON_STARTUP=false in the main application. Exits non-zero on failure
so orchestrators (Kubernetes, CI) can gate app rollout on success.

Usage:
    python -m scripts.migrate [upgrade head]
    python -m scripts.migrate downgrade -1
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from src.core.config import settings

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_PROJECT_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)

    args = argv or ["upgrade", "head"]
    op = args[0]
    target = args[1] if len(args) > 1 else "head"

    if op == "upgrade":
        command.upgrade(cfg, target)
    elif op == "downgrade":
        command.downgrade(cfg, target)
    elif op == "current":
        command.current(cfg)
    elif op == "history":
        command.history(cfg)
    else:
        print(f"unknown operation: {op}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
