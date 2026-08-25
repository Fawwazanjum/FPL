"""Position-aware expected-points model. Each player's xPts is built from
separately-weighted components (attacking return, clean sheet, DEFCON, bonus,
conceded penalty, card risk) rather than one blended number, so a defender who
racks up defensive actions is compared on the right axis against a defender who
doesn't, and both are compared correctly against attackers. See constants in
data/scoring_rules.py for the live, position-keyed point values driving this.

The appearance-probability and clean-sheet-probability pieces below are
deliberately simple heuristics (not a calibrated Poisson goal model) — a
reasonable first pass for a personal tool, easy to refine later without
changing the surrounding architecture.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from fpl_model.analysis.rate_blend import blend_rate
from fpl_model.analysis.team_strength import TeamStrengthResult
from fpl_model.config import AppConfig, FormWeights
from fpl_model.constants import ELEMENT_TYPE_ID_TO_POSITION
from fpl_model.data.scoring_rules import DEFCON_THRESHOLD, ScoringRules
from fpl_model.storage import repository

CLEAN_SHEET_BASE_RATE = 0.30
CLEAN_SHEET_INDEX_SENSITIVITY = 0.12
CLEAN_SHEET_MIN, CLEAN_SHEET_MAX = 0.03, 0.75
CONCEDED_INDEX_SENSITIVITY = 0.15
UNKNOWN_INVOLVEMENT_START_RATIO = 0.3
MIN_MINUTES_FACTOR = 0.15


@dataclass
class XptsBreakdown:
    player_id: int
    gameweek: int
    opponent_team_id: int | None
    is_home: bool | None
    p_full_involvement: float
    appearance_pts: float
    attacking_pts: float
    clean_sheet_pts: float
    clean_sheet_prob: float
    defcon_pts: float
    defcon_hit_rate: float
    conceded_penalty: float
    bonus_pts: float
    card_penalty: float
    total: float
    reasoning: str


def _attacking_rate_per90(
    conn: sqlite3.Connection, player_id: int, position: str, scoring: ScoringRules, weights: FormWeights, last_season_row
) -> tuple[float, int]:
    if last_season_row is not None and (last_season_row["minutes"] or 0) > 0:
        last_rate = scoring.attacking_points(
            position, last_season_row["goals_scored"] or 0, last_season_row["assists"] or 0
        ) / (last_season_row["minutes"] / 90)
    else:
        last_rate = 0.0

    snap = repository.get_latest_snapshot_for_player(conn, player_id)
    if snap is not None and (snap["minutes"] or 0) > 0:
        season_rate = scoring.attacking_points(position, snap["expected_goals"] or 0.0, snap["expected_assists"] or 0.0) / (
            snap["minutes"] / 90
        )
    else:
        season_rate = 0.0

    all_rows = repository.get_player_gw_history_all(conn, player_id)
    played_rows = [r for r in all_rows if (r["minutes"] or 0) > 0]
    n = len(played_rows)
    recent_rows = played_rows[-6:]
    recent_minutes = sum((r["minutes"] or 0) for r in recent_rows)
    recent_points = sum(
        scoring.attacking_points(position, r["expected_goals"] or 0.0, r["expected_assists"] or 0.0) for r in recent_rows
    )
    recent_rate = recent_points / (recent_minutes / 90) if recent_minutes > 0 else 0.0

    blend = blend_rate(last_rate, season_rate, recent_rate, n, weights)
    return blend.blended_rate, n


def _bonus_rate_per90(conn: sqlite3.Connection, player_id: int, weights: FormWeights, last_season_row, n: int) -> float:
    # player_history_past doesn't store a 'bonus' column (see storage/schema.sql),
    # so there's no last-season prior for this component — neutral (0) is used,
    # and the blend schedule already down-weights it once n > 0 anyway.
    last_rate = 0.0

    all_rows = repository.get_player_gw_history_all(conn, player_id)
    played_rows = [r for r in all_rows if (r["minutes"] or 0) > 0]
    season_minutes = sum((r["minutes"] or 0) for r in played_rows)
    season_bonus = sum((r["bonus"] or 0) for r in played_rows)
    season_rate = season_bonus / (season_minutes / 90) if season_minutes > 0 else 0.0

    recent_rows = played_rows[-6:]
    recent_minutes = sum((r["minutes"] or 0) for r in recent_rows)
    recent_bonus = sum((r["bonus"] or 0) for r in recent_rows)
    recent_rate = recent_bonus / (recent_minutes / 90) if recent_minutes > 0 else 0.0

    blend = blend_rate(last_rate, season_rate, recent_rate, n, weights)
    return blend.blended_rate


def _defcon_hit_rate(conn: sqlite3.Connection, player_id: int, position: str) -> float:
    threshold = DEFCON_THRESHOLD.get(position)
    if not threshold:
        return 0.0
    all_rows = repository.get_player_gw_history_all(conn, player_id)
    played_rows = [r for r in all_rows if (r["minutes"] or 0) > 0]
    if not played_rows:
        return 0.0
    hits = sum(1 for r in played_rows if (r["defensive_contribution"] or 0) >= threshold)
    return hits / len(played_rows)


def _card_rate_per90(conn: sqlite3.Connection, player_id: int, scoring: ScoringRules) -> float:
    all_rows = repository.get_player_gw_history_all(conn, player_id)
    played_rows = [r for r in all_rows if (r["minutes"] or 0) > 0]
    minutes = sum((r["minutes"] or 0) for r in played_rows)
    if minutes <= 0:
        return 0.0
    points = sum(
        (r["yellow_cards"] or 0) * scoring.yellow_cards + (r["red_cards"] or 0) * scoring.red_cards for r in played_rows
    )
    return points / (minutes / 90)


def _involvement_probability(snap: sqlite3.Row | None, recent_rows: list[sqlite3.Row]) -> tuple[float, float]:
    chance = snap["chance_of_playing_next_round"] if snap is not None else None
    p_available = 1.0 if chance is None else max(0.0, min(1.0, chance / 100))
    if recent_rows:
        start_ratio = sum(1 for r in recent_rows if (r["minutes"] or 0) >= 60) / len(recent_rows)
    else:
        start_ratio = UNKNOWN_INVOLVEMENT_START_RATIO
    minutes_factor = max(MIN_MINUTES_FACTOR, min(1.0, start_ratio))
    return p_available, minutes_factor


def _clean_sheet_probability(own_defense_index: float, opp_attack_index: float) -> float:
    p = CLEAN_SHEET_BASE_RATE + CLEAN_SHEET_INDEX_SENSITIVITY * (own_defense_index - opp_attack_index)
    return max(CLEAN_SHEET_MIN, min(CLEAN_SHEET_MAX, p))


def _expected_conceded_this_fixture(team_strength: TeamStrengthResult, opp_attack_index: float, team_games: int) -> float:
    per_game_xgc = team_strength.defense_xgc / team_games if team_games > 0 else team_strength.defense_xgc
    adjusted = per_game_xgc * (1 + CONCEDED_INDEX_SENSITIVITY * opp_attack_index)
    return max(0.2, min(4.0, adjusted))


def compute_player_xpts_gw(
    conn: sqlite3.Connection,
    player_id: int,
    gameweek: int,
    scoring: ScoringRules,
    weights: FormWeights,
    team_strength: dict[int, TeamStrengthResult],
) -> XptsBreakdown | None:
    from fpl_model.constants import LAST_SEASON_LABEL

    snap = repository.get_latest_snapshot_for_player(conn, player_id)
    if snap is None:
        return None
    position = ELEMENT_TYPE_ID_TO_POSITION.get(snap["element_type"], "MID")
    team_id = snap["team_id"]

    last_season_row = repository.get_player_history_past(conn, player_id, LAST_SEASON_LABEL)
    attacking_rate, n = _attacking_rate_per90(conn, player_id, position, scoring, weights, last_season_row)
    bonus_rate = _bonus_rate_per90(conn, player_id, weights, last_season_row, n)
    defcon_rate = _defcon_hit_rate(conn, player_id, position)
    card_rate = _card_rate_per90(conn, player_id, scoring)

    all_rows = repository.get_player_gw_history_all(conn, player_id)
    played_rows = [r for r in all_rows if (r["minutes"] or 0) > 0]
    recent_rows = played_rows[-4:]
    p_available, minutes_factor = _involvement_probability(snap, recent_rows)
    p_full = p_available * minutes_factor
    appearance_pts = p_available * (minutes_factor * scoring.long_play + (1 - minutes_factor) * scoring.short_play)

    fixtures = repository.get_fixtures_for_team_gw(conn, team_id, gameweek)
    opponent_id: int | None = None
    is_home: bool | None = None
    clean_sheet_prob = 0.0
    conceded_penalty = 0.0
    reasoning_parts = []

    if fixtures and team_id in team_strength:
        fx = fixtures[0]
        is_home = fx["team_h"] == team_id
        opponent_id = fx["team_a"] if is_home else fx["team_h"]
        own_strength = team_strength[team_id]
        opp_strength = team_strength.get(opponent_id)
        opp_attack_index = opp_strength.attack_index if opp_strength else 0.0
        clean_sheet_prob = _clean_sheet_probability(own_strength.defense_index, opp_attack_index)
        team_games = max(1, len(repository.get_finished_fixtures(conn)) // 10)  # rough per-team game count proxy
        expected_conceded = _expected_conceded_this_fixture(own_strength, opp_attack_index, team_games)
        conceded_penalty = scoring.goals_conceded.get(position, 0) * (expected_conceded / 2)
        reasoning_parts.append(f"vs team {opponent_id} ({'H' if is_home else 'A'}), CS prob {clean_sheet_prob:.0%}")
    else:
        reasoning_parts.append("no fixture found for this gameweek")

    clean_sheet_pts = scoring.clean_sheets.get(position, 0) * clean_sheet_prob
    defcon_pts = scoring.defensive_contribution_points.get(position, 0) * defcon_rate
    attacking_pts_full90 = attacking_rate

    total = appearance_pts + p_full * (
        attacking_pts_full90 + clean_sheet_pts + defcon_pts + conceded_penalty + bonus_rate + card_rate
    )

    if attacking_pts_full90 > 1.0:
        reasoning_parts.append(f"strong attacking rate ({attacking_pts_full90:.2f} pts/90)")
    if defcon_pts > 0.3:
        reasoning_parts.append(f"high DEFCON hit-rate ({defcon_rate:.0%})")
    if p_full < 0.5:
        reasoning_parts.append(f"rotation/fitness risk (p_involved={p_full:.0%})")

    return XptsBreakdown(
        player_id=player_id,
        gameweek=gameweek,
        opponent_team_id=opponent_id,
        is_home=is_home,
        p_full_involvement=p_full,
        appearance_pts=appearance_pts,
        attacking_pts=p_full * attacking_pts_full90,
        clean_sheet_pts=p_full * clean_sheet_pts,
        clean_sheet_prob=clean_sheet_prob,
        defcon_pts=p_full * defcon_pts,
        defcon_hit_rate=defcon_rate,
        conceded_penalty=p_full * conceded_penalty,
        bonus_pts=p_full * bonus_rate,
        card_penalty=p_full * card_rate,
        total=total,
        reasoning="; ".join(reasoning_parts),
    )


def compute_horizon_xpts(
    conn: sqlite3.Connection,
    player_id: int,
    from_gw: int,
    horizon: int,
    decay: float,
    scoring: ScoringRules,
    weights: FormWeights,
    team_strength: dict[int, TeamStrengthResult],
) -> float:
    total = 0.0
    for i in range(horizon):
        gw = from_gw + i
        result = compute_player_xpts_gw(conn, player_id, gw, scoring, weights, team_strength)
        if result is not None:
            total += result.total * (decay**i)
    return total


def compute_all(
    conn: sqlite3.Connection,
    player_ids: list[int],
    gameweek: int,
    config: AppConfig,
    scoring: ScoringRules,
    team_strength: dict[int, TeamStrengthResult],
) -> dict[int, XptsBreakdown]:
    results: dict[int, XptsBreakdown] = {}
    for pid in player_ids:
        breakdown = compute_player_xpts_gw(conn, pid, gameweek, scoring, config.form_weights, team_strength)
        if breakdown is not None:
            results[pid] = breakdown
    return results
