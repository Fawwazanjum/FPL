"""Decides which players get expensive element-summary API calls each run.

Used to scope this down to squad + top-owned + top-form per position (~100-160
players) on the assumption that fetching all ~620 was too slow/heavy to do
every run. Measured directly against the live API: ~26ms/request, ~16s for
the full player pool — that assumption doesn't hold, so this now just returns
every player, restricted only to those with a real team assigned (excludes
unavailable/retired elements bootstrap-static sometimes carries with no
team_id). See memory: fpl-model-project (user specifically asked for
full-league coverage so transfer recommendations aren't blind to anyone
outside the current template/differential pool).

player_snapshots itself was never scoped either way — that comes from
bootstrap-static directly for all players regardless of this function.

Kept as its own function (not inlined at the call site) so a future need to
scope back down — if the API ever gets meaningfully slower, or a much larger
candidate pool needs trimming for the optimizer's own runtime — has one place
to change.
"""

from __future__ import annotations

import sqlite3

from fpl_model.storage import repository


def select_scoped_players(conn: sqlite3.Connection, squad_player_ids: list[int]) -> set[int]:
    snapshots = repository.get_latest_player_snapshots(conn)
    scoped = {row["player_id"] for row in snapshots if row["team_id"] is not None}
    scoped.update(squad_player_ids)
    return scoped
