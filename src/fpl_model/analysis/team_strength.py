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
# How much credit/discount a team's attack_index/defense_index gets for the
# average strength of the opponents it's actually faced so far (see memory:
# fpl-model-project) — previously attack_xg/defense_xgc were taken at face
# value regardless of opposition, so a team that happened to open the season
# against three promoted sides looked artificially strong, and one that
# opened against the reigning champions and the two other "big" sides looked
# artificially weak, purely from schedule luck rather than true quality. This
# is a single-pass adjustment (opponents' PRE-adjustment z-scores), not a
# fully converged Massey/Colley-style rating — deliberately: with 1-2 games
# per team early on, chasing convergence would be false precision on top of
# an already-thin sample. Same in-season shrink factor applies to the
# adjusted value as to the raw one, so this doesn't overreact early either.
SOS_SENSITIVITY = 0.4


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
    # Venue-specific strength, sourced from FPL's own strength_attack_home/away
    # and strength_defence_home/away ratings (ingested every run into
    # teams_snapshots but previously unused). Unlike attack_index/defense_index
    # above — which are shrunk z-scores of THIS season's actual xG/goals and so
    # start near-zero in a new season — these are FPL's own curated ratings and
    # carry signal from day one, which is exactly what's missing early on. Kept
    # as separate fields rather than merged into attack_index/defense_index so
    # xpts.py can blend them in with an explicit, tunable weight per fixture
    # (home strength when the team is at home, away strength when it isn't).
    attack_index_home: float = 0.0
    attack_index_away: float = 0.0
    defense_index_home: float = 0.0
    defense_index_away: float = 0.0
    # The SOS_SENSITIVITY-weighted credit/discount already folded into
    # attack_index/defense_index above — kept visible separately so "why did
    # this team's rating move" has a concrete answer (a tough or soft
    # schedule so far), not just an opaque combined number.
    attack_sos_adjustment: float = 0.0
    defense_sos_adjustment: float = 0.0


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


def _venue_strength_by_team(conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    return {row["team_id"]: row for row in repository.get_latest_team_snapshots(conn)}


def _opponents_faced_by_team(conn: sqlite3.Connection) -> dict[int, list[int]]:
    opponents: dict[int, list[int]] = {}
    for fx in repository.get_finished_fixtures(conn):
        h, a = fx["team_h"], fx["team_a"]
        opponents.setdefault(h, []).append(a)
        opponents.setdefault(a, []).append(h)
    return opponents


def _strength_of_schedule_adjustment(
    team_ids: list[int], opponents_faced: dict[int, list[int]], opponent_index_raw: dict[int, float]
) -> dict[int, float]:
    """Average PRE-adjustment index of the opponents a team has actually
    faced, for use as a credit/discount term — e.g. average DEFENSE index
    faced feeds the ATTACK adjustment (faced tough defenses and still scored
    well -> more credit than the raw number implies; faced weak defenses ->
    discount), and vice versa for defense against opponents' attack index."""
    adjustment: dict[int, float] = {}
    for tid in team_ids:
        opponents = opponents_faced.get(tid, [])
        if not opponents:
            adjustment[tid] = 0.0
            continue
        adjustment[tid] = statistics.fmean(opponent_index_raw.get(opp, 0.0) for opp in opponents)
    return adjustment


def compute_team_strength(conn: sqlite3.Connection) -> dict[int, TeamStrengthResult]:
    goals_for, goals_against, games_played = _actual_goals_by_team(conn)
    attack_xg, defense_xgc = _attack_xg_and_defense_xgc_by_team(conn)
    team_ids = repository.get_all_team_ids(conn)
    venue_strength = _venue_strength_by_team(conn)

    attack_index_raw = {tid: attack_xg.get(tid, 0.0) for tid in team_ids}
    defense_index_raw = {tid: -defense_xgc.get(tid, 0.0) for tid in team_ids}
    attack_z = _zscores(attack_index_raw)
    defense_z = _zscores(defense_index_raw)

    # Strength-of-schedule: credit/discount each team's raw z-score by the
    # average PRE-adjustment strength of who they've actually played —
    # attack gets adjusted by opponents' defense_z faced, defense by
    # opponents' attack_z faced. See SOS_SENSITIVITY docstring.
    opponents_faced = _opponents_faced_by_team(conn)
    attack_sos = _strength_of_schedule_adjustment(team_ids, opponents_faced, defense_z)
    defense_sos = _strength_of_schedule_adjustment(team_ids, opponents_faced, attack_z)
    attack_z = {tid: attack_z.get(tid, 0.0) + SOS_SENSITIVITY * attack_sos.get(tid, 0.0) for tid in team_ids}
    defense_z = {tid: defense_z.get(tid, 0.0) + SOS_SENSITIVITY * defense_sos.get(tid, 0.0) for tid in team_ids}

    # FPL's own home/away ratings, z-scored the same way as the xG-based
    # indices above so they're on a comparable scale for xpts.py to blend.
    # These need no in-season shrinkage — they're not derived from this
    # season's (thin, early) sample, they're FPL's pre-existing rating.
    attack_home_raw = {tid: (venue_strength[tid]["strength_attack_home"] or 0) for tid in team_ids if tid in venue_strength}
    attack_away_raw = {tid: (venue_strength[tid]["strength_attack_away"] or 0) for tid in team_ids if tid in venue_strength}
    defense_home_raw = {tid: -(venue_strength[tid]["strength_defence_home"] or 0) for tid in team_ids if tid in venue_strength}
    defense_away_raw = {tid: -(venue_strength[tid]["strength_defence_away"] or 0) for tid in team_ids if tid in venue_strength}
    attack_home_z = _zscores(attack_home_raw)
    attack_away_z = _zscores(attack_away_raw)
    defense_home_z = _zscores(defense_home_raw)
    defense_away_z = _zscores(defense_away_raw)

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
            attack_index_home=attack_home_z.get(tid, 0.0),
            attack_index_away=attack_away_z.get(tid, 0.0),
            defense_index_home=defense_home_z.get(tid, 0.0),
            defense_index_away=defense_away_z.get(tid, 0.0),
            attack_sos_adjustment=round(SOS_SENSITIVITY * attack_sos.get(tid, 0.0) * shrink, 3),
            defense_sos_adjustment=round(SOS_SENSITIVITY * defense_sos.get(tid, 0.0) * shrink, 3),
        )
    return results
