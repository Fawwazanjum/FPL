"""Rival-relative analysis for private mini-leagues.

Distinct from the whole-player-base ownership%/differential logic used
elsewhere in the model: "differential" for overall rank means low-owned
across ~10 million managers, but for beating a specific 6-person mini-league
what matters is ownership among exactly those 6 people, which can point in
the opposite direction from the global number entirely (see memory:
fpl-model-project). See config.py's mini_league_ids and data/ingest.py's
_ingest_rivals for how the underlying data gets populated — this module only
reads what's already in the database, no network calls of its own.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from fpl_model.storage import repository


@dataclass
class RivalStanding:
    league_id: int
    league_name: str
    team_id: int
    entry_name: str
    player_name: str
    rank: int
    total_points: int
    gap_to_me: int  # my_total - their_total; negative = they're ahead of me


@dataclass
class RivalOwnership:
    player_id: int
    rivals_owning: int
    rivals_captaining: int
    total_rivals: int
    owned_by: list[str] = field(default_factory=list)
    captained_by: list[str] = field(default_factory=list)


def _entry_names(conn: sqlite3.Connection) -> dict[int, str]:
    names: dict[int, str] = {}
    for league_id in repository.get_all_tracked_league_ids(conn):
        for row in repository.get_league_standings(conn, league_id):
            names[row["team_id"]] = row["entry_name"] or str(row["team_id"])
    return names


def get_rival_standings(conn: sqlite3.Connection, my_total_points: int) -> list[RivalStanding]:
    standings: list[RivalStanding] = []
    for league_id in repository.get_all_tracked_league_ids(conn):
        for row in repository.get_league_standings(conn, league_id):
            standings.append(
                RivalStanding(
                    league_id=league_id,
                    league_name=row["league_name"] or str(league_id),
                    team_id=row["team_id"],
                    entry_name=row["entry_name"] or str(row["team_id"]),
                    player_name=row["player_name"] or "",
                    rank=row["rank"] or 0,
                    total_points=row["total_points"] or 0,
                    gap_to_me=my_total_points - (row["total_points"] or 0),
                )
            )
    return standings


def compute_rival_ownership(
    conn: sqlite3.Connection, gw: int, player_ids: list[int], my_team_id: int
) -> dict[int, RivalOwnership]:
    rival_team_ids = repository.get_all_rival_team_ids(conn, exclude_team_id=my_team_id)
    if not rival_team_ids:
        return {}

    entry_names = _entry_names(conn)
    player_id_set = set(player_ids)

    owning: dict[int, list[int]] = {pid: [] for pid in player_ids}
    captaining: dict[int, list[int]] = {pid: [] for pid in player_ids}
    for rival_team_id in rival_team_ids:
        # A rival's own team_id might itself appear across multiple tracked
        # leagues (same person, both leagues) — get_squad_for_gw is already
        # per-team_id so this naturally de-dupes rather than double counting.
        for p in repository.get_squad_for_gw(conn, rival_team_id, gw):
            pid = p["player_id"]
            if pid not in player_id_set:
                continue
            owning[pid].append(rival_team_id)
            if p["is_captain"]:
                captaining[pid].append(rival_team_id)

    return {
        pid: RivalOwnership(
            player_id=pid,
            rivals_owning=len(owning.get(pid, [])),
            rivals_captaining=len(captaining.get(pid, [])),
            total_rivals=len(rival_team_ids),
            owned_by=[entry_names.get(tid, str(tid)) for tid in owning.get(pid, [])],
            captained_by=[entry_names.get(tid, str(tid)) for tid in captaining.get(pid, [])],
        )
        for pid in player_ids
    }
