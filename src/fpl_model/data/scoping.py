"""Decides which players get expensive element-summary API calls each run.

Calling element-summary for all ~700 players every run is wasteful (rate limits,
run time). Scope = squad + top-owned per position ("template" pool) + top
underlying-form per position not already included ("differential" pool) — union
is typically ~100-160 players, still covering every realistic transfer target.
player_snapshots itself is NOT scoped — that comes from bootstrap-static
directly for all players, so team_strength.py and value.py's percentile ranks
still see the full player pool even though only the scoped subset gets
element-summary-derived form/xPts data.
"""

from __future__ import annotations

import sqlite3

from fpl_model.constants import ELEMENT_TYPE_ID_TO_POSITION, POSITIONS
from fpl_model.storage import repository

DEFAULT_TOP_N_OWNED = 15
DEFAULT_TOP_N_FORM = 15


def _xgi_per90(row: sqlite3.Row) -> float:
    minutes = row["minutes"] or 0
    if minutes <= 0:
        return -1.0
    return (row["expected_goal_involvements"] or 0.0) / (minutes / 90)


def select_scoped_players(
    conn: sqlite3.Connection,
    squad_player_ids: list[int],
    top_n_owned: int = DEFAULT_TOP_N_OWNED,
    top_n_form: int = DEFAULT_TOP_N_FORM,
) -> set[int]:
    snapshots = repository.get_latest_player_snapshots(conn)
    by_position: dict[str, list[sqlite3.Row]] = {pos: [] for pos in POSITIONS}
    for row in snapshots:
        pos = ELEMENT_TYPE_ID_TO_POSITION.get(row["element_type"])
        if pos:
            by_position[pos].append(row)

    scoped: set[int] = set(squad_player_ids)

    for pos, rows in by_position.items():
        top_owned = sorted(rows, key=lambda r: r["selected_by_percent"] or 0.0, reverse=True)[:top_n_owned]
        scoped.update(r["player_id"] for r in top_owned)

        top_form = sorted(rows, key=_xgi_per90, reverse=True)[:top_n_form]
        scoped.update(r["player_id"] for r in top_form)

    return scoped
