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


def apply_schema(conn: sqlite3.Connection) -> None:
    schema_sql = resources.files("fpl_model.storage").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()
