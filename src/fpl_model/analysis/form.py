from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from fpl_model.analysis.rate_blend import shrink_toward_expected, blend_rate
from fpl_model.config import FormWeights
from fpl_model.constants import ELEMENT_TYPE_ID_TO_POSITION, LAST_SEASON_LABEL
from fpl_model.data.scoring_rules import ScoringRules
from fpl_model.storage import repository


@dataclass
class FormResult:
    player_id: int
    position: str
    last_season_rate: float
    season_rate: float
    recent_rate_raw: float
    recent_rate_adjusted: float
    form_score: float
    games_played: int
    used_position_fallback: bool


def _rate_per90(rows: list[sqlite3.Row], value_key: str) -> tuple[float, float]:
    minutes_sum = sum((r["minutes"] or 0) for r in rows)
    value_sum = sum((r[value_key] or 0) for r in rows)
    if minutes_sum <= 0:
        return 0.0, 0.0
    return value_sum / (minutes_sum / 90), minutes_sum


def _last_season_rate(conn: sqlite3.Connection, player_id: int) -> float | None:
    row = repository.get_player_history_past(conn, player_id, LAST_SEASON_LABEL)
    if row is None or not row["minutes"]:
        return None
    return row["total_points"] / (row["minutes"] / 90)


def _position_average_last_season(
    conn: sqlite3.Connection, player_ids: list[int], positions: dict[int, str]
) -> dict[str, float]:
    sums: dict[str, list[float]] = {}
    for pid in player_ids:
        rate = _last_season_rate(conn, pid)
        if rate is None:
            continue
        pos = positions.get(pid)
        if pos is None:
            continue
        sums.setdefault(pos, []).append(rate)
    return {pos: sum(vals) / len(vals) for pos, vals in sums.items() if vals}


def compute_form_score(
    conn: sqlite3.Connection,
    player_id: int,
    position: str,
    scoring: ScoringRules,
    weights: FormWeights,
    position_avg_last_season: dict[str, float],
) -> FormResult:
    last_rate = _last_season_rate(conn, player_id)
    used_fallback = last_rate is None
    if last_rate is None:
        last_rate = position_avg_last_season.get(position, 0.0)

    latest_snap = repository.get_latest_snapshot_for_player(conn, player_id)
    if latest_snap is not None and (latest_snap["minutes"] or 0) > 0:
        season_rate = latest_snap["total_points"] / (latest_snap["minutes"] / 90)
    else:
        season_rate = 0.0

    all_rows = repository.get_player_gw_history_all(conn, player_id)
    played_rows = [r for r in all_rows if (r["minutes"] or 0) > 0]
    n = len(played_rows)
    recent_rows = played_rows[-6:]

    recent_raw, recent_minutes = _rate_per90(recent_rows, "total_points")
    expected_points_sum = sum(
        scoring.attacking_points(position, r["expected_goals"] or 0.0, r["expected_assists"] or 0.0)
        for r in recent_rows
    )
    expected_rate = expected_points_sum / (recent_minutes / 90) if recent_minutes > 0 else 0.0
    recent_adjusted = shrink_toward_expected(recent_raw, expected_rate, recent_minutes, weights.recent_form_shrinkage_minutes)

    blend = blend_rate(last_rate, season_rate, recent_adjusted, n, weights)

    return FormResult(
        player_id=player_id,
        position=position,
        last_season_rate=last_rate,
        season_rate=season_rate,
        recent_rate_raw=recent_raw,
        recent_rate_adjusted=recent_adjusted,
        form_score=blend.blended_rate,
        games_played=n,
        used_position_fallback=used_fallback,
    )


def compute_all(
    conn: sqlite3.Connection, player_ids: list[int], scoring: ScoringRules, weights: FormWeights
) -> dict[int, FormResult]:
    positions: dict[int, str] = {}
    for pid in player_ids:
        snap = repository.get_latest_snapshot_for_player(conn, pid)
        positions[pid] = ELEMENT_TYPE_ID_TO_POSITION.get(snap["element_type"], "MID") if snap else "MID"

    position_avg_last_season = _position_average_last_season(conn, player_ids, positions)

    results: dict[int, FormResult] = {}
    for pid in player_ids:
        results[pid] = compute_form_score(conn, pid, positions[pid], scoring, weights, position_avg_last_season)
    return results
