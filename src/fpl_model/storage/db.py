from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# CREATE TABLE IF NOT EXISTS in schema.sql only handles brand-new databases —
# an existing on-disk DB keeps its old column set forever otherwise. SQLite
# has no "ADD COLUMN IF NOT EXISTS", so each addition here is applied by hand,
# guarded by a PRAGMA table_info check for idempotency across repeated runs.
_COLUMN_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "player_history_past": [
        ("expected_goals", "REAL"),
        ("expected_assists", "REAL"),
        ("defensive_contribution", "INTEGER"),
    ],
}


def _apply_column_migrations(conn: sqlite3.Connection) -> None:
    for table, columns in _COLUMN_MIGRATIONS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, sql_type in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
    conn.commit()


def apply_schema(conn: sqlite3.Connection) -> None:
    schema_sql = resources.files("fpl_model.storage").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()
    _apply_column_migrations(conn)
