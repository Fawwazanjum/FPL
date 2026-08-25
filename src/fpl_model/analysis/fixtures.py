"""Blank/double gameweek detection and fixture-difficulty lookups over a
horizon. Blank/double gameweeks are rare early in a season (they mostly come
from postponements, cup replays, and end-of-season scheduling), so these will
usually return empty early on — that's expected, not a bug, this is
forward-looking infrastructure for when the fixture list gets congested later.
"""

from __future__ import annotations

import sqlite3

from fpl_model.storage import repository


def detect_blank_gameweeks(conn: sqlite3.Connection, team_ids: list[int], from_gw: int, horizon: int) -> dict[int, list[int]]:
    """gw -> team_ids with zero fixtures that gameweek."""
    blanks: dict[int, list[int]] = {}
    for gw in range(from_gw, from_gw + horizon):
        fixtures = repository.get_fixtures_for_gw(conn, gw)
        teams_playing = set()
        for fx in fixtures:
            teams_playing.add(fx["team_h"])
            teams_playing.add(fx["team_a"])
        missing = [tid for tid in team_ids if tid not in teams_playing]
        if missing:
            blanks[gw] = missing
    return blanks


def detect_double_gameweeks(conn: sqlite3.Connection, team_ids: list[int], from_gw: int, horizon: int) -> dict[int, list[int]]:
    """gw -> team_ids with 2+ fixtures that gameweek."""
    doubles: dict[int, list[int]] = {}
    for gw in range(from_gw, from_gw + horizon):
        fixtures = repository.get_fixtures_for_gw(conn, gw)
        counts: dict[int, int] = {}
        for fx in fixtures:
            counts[fx["team_h"]] = counts.get(fx["team_h"], 0) + 1
            counts[fx["team_a"]] = counts.get(fx["team_a"], 0) + 1
        dgw_teams = [tid for tid in team_ids if counts.get(tid, 0) >= 2]
        if dgw_teams:
            doubles[gw] = dgw_teams
    return doubles


def fixture_difficulty_for_horizon(conn: sqlite3.Connection, team_id: int, from_gw: int, horizon: int) -> list[int]:
    """Difficulty rating for each of this team's fixtures in the horizon (can
    have 0, 1, or 2+ entries for a given gameweek if blank/double)."""
    difficulties: list[int] = []
    for gw in range(from_gw, from_gw + horizon):
        for fx in repository.get_fixtures_for_team_gw(conn, team_id, gw):
            is_home = fx["team_h"] == team_id
            diff = fx["team_h_difficulty"] if is_home else fx["team_a_difficulty"]
            if diff is not None:
                difficulties.append(diff)
    return difficulties
