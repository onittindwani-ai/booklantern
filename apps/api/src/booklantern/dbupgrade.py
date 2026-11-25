"""Columns added after release 1.0.0, for the SQLite zero setup path. `create_all` makes missing tables but never adds a column to a table that already exists, so a
database file made by an older version would fail with "no such column". Postgres installs use `alembic upgrade head` instead (migration 0003)."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

ADDED_COLUMNS = (("ll_document", "read_attempts", "INTEGER NOT NULL DEFAULT 0"),)


def add_missing_columns(engine: Engine) -> list[str]:
    """Add every column in ADDED_COLUMNS that an existing SQLite table lacks. Returns what it added. Does nothing on other databases."""
    if engine.dialect.name != "sqlite":
        return []
    added: list[str] = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            if insp.has_table(table) and column not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
                added.append(f"{table}.{column}")
    return added
