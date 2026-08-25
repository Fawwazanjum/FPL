"""Club-level attack/defense over/underperformance vs their underlying xG.

Sign convention (matches the approved plan):
- attack_overperformance = actual goals scored - team xG. Positive = scoring
  more than their chances deserve (regression risk for their attackers going
  forward). Negative = due a positive correction (buy-low attacking signal).
- defense_overperformance = team xGC - actual goals conceded. Positive = the
  defense is conceding fewer goals than their underlying numbers suggest
  (regression risk — clean sheets may dry up). Negative = defense is
  underperforming and due to tighten up (buy-low defensive signal).
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass

from fpl_model.storage import repository

# Same purple-patch/blip discipline applied to player minutes/form (see
# rate_blend.py) applied at the team level: a z-score computed from just 1-2
# games is extremely noisy (one big win/loss swings it by several std devs)
# and gets treated by xpts.py as a stable clean-sheet-probability signal if
# left unshrunk. Denominator chosen so index magnitude ramps up gradually
# over a team's first ~8-10 games rather than being taken at face value
# immediately — deliberately conservative, not calibrated against real data.
TEAM_STRENGTH_SHRINKAGE_GAMES = 8


@dataclass
class TeamStrengthResult:
    team_id: int
    games_played: int
    actual_goals_for: int
    actual_goals_against: int
    attack_xg: float
    defense_xgc: float
    attack_overperformance: float
    defense_overperformance: float
    attack_index: float
    defense_index: float


def _actual_goals_by_team(conn: sqlite3.Connection) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
    goals_for: dict[int, int] = {}
    goals_against: dict[int, int] = {}
    games_played: dict[int, int] = {}
    for fx in repository.get_finished_fixtures(conn):
        h, a = fx["team_h"], fx["team_a"]
        hs, as_ = fx["team_h_score"] or 0, fx["team_a_score"] or 0
        goals_for[h] = goals_for.get(h, 0) + hs
        goals_against[h] = goals_against.get(h, 0) + as_
        goals_for[a] = goals_for.get(a, 0) + as_
        goals_against[a] = goals_against.get(a, 0) + hs
        games_played[h] = games_played.get(h, 0) + 1
        games_played[a] = games_played.get(a, 0) + 1
    return goals_for, goals_against, games_played


def _attack_xg_and_defense_xgc_by_team(conn: sqlite3.Connection) -> tuple[dict[int, float], dict[int, float]]:
    snapshots = repository.get_latest_player_snapshots(conn)
    attack_xg: dict[int, float] = {}
    best_minutes: dict[int, int] = {}
    defense_xgc: dict[int, float] = {}
    for row in snapshots:
        tid = row["team_id"]
        attack_xg[tid] = attack_xg.get(tid, 0.0) + (row["expected_goals"] or 0.0)
        minutes = row["minutes"] or 0
        if minutes > best_minutes.get(tid, -1):
            best_minutes[tid] = minutes
            defense_xgc[tid] = row["expected_goals_conceded"] or 0.0
    return attack_xg, defense_xgc


def _zscores(values: dict[int, float]) -> dict[int, float]:
    if not values:
        return {}
    vals = list(values.values())
    mean = statistics.fmean(vals)
    stdev = statistics.pstdev(vals)
    if stdev == 0:
        return {k: 0.0 for k in values}
    return {k: (v - mean) / stdev for k, v in values.items()}


def compute_team_strength(conn: sqlite3.Connection) -> dict[int, TeamStrengthResult]:
    goals_for, goals_against, games_played = _actual_goals_by_team(conn)
    attack_xg, defense_xgc = _attack_xg_and_defense_xgc_by_team(conn)
    team_ids = repository.get_all_team_ids(conn)

    attack_index_raw = {tid: attack_xg.get(tid, 0.0) for tid in team_ids}
    defense_index_raw = {tid: -defense_xgc.get(tid, 0.0) for tid in team_ids}
    attack_z = _zscores(attack_index_raw)
    defense_z = _zscores(defense_index_raw)

    results: dict[int, TeamStrengthResult] = {}
    for tid in team_ids:
        gf = goals_for.get(tid, 0)
        ga = goals_against.get(tid, 0)
        xg = attack_xg.get(tid, 0.0)
        xgc = defense_xgc.get(tid, 0.0)
        n = games_played.get(tid, 0)
        shrink = n / (n + TEAM_STRENGTH_SHRINKAGE_GAMES)
        results[tid] = TeamStrengthResult(
            team_id=tid,
            games_played=n,
            actual_goals_for=gf,
            actual_goals_against=ga,
            attack_xg=xg,
            defense_xgc=xgc,
            attack_overperformance=gf - xg,
            defense_overperformance=xgc - ga,
            attack_index=attack_z.get(tid, 0.0) * shrink,
            defense_index=defense_z.get(tid, 0.0) * shrink,
        )
    return results
