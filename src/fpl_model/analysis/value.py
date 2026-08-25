from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from fpl_model.config import AppConfig
from fpl_model.constants import ELEMENT_TYPE_ID_TO_POSITION, POSITIONS
from fpl_model.storage import repository


@dataclass
class ValueResult:
    player_id: int
    position: str
    web_name: str
    now_cost_millions: float
    points_per_million: float
    xpts_horizon: float
    xpts_percentile_in_position: float
    ownership_percentile_in_position: float
    selected_by_percent: float
    differential_score: float
    template_score: float


def _percentile_rank(value: float, all_values: list[float]) -> float:
    if len(all_values) <= 1:
        return 0.5
    below_or_equal = sum(1 for v in all_values if v <= value)
    return (below_or_equal - 1) / (len(all_values) - 1)


def compute_value(
    conn: sqlite3.Connection, player_ids: list[int], xpts_horizon: dict[int, float], config: AppConfig
) -> dict[int, ValueResult]:
    positions: dict[int, str] = {}
    ownership: dict[int, float] = {}
    now_cost: dict[int, int] = {}
    total_points: dict[int, int] = {}
    web_names: dict[int, str] = {}

    for pid in player_ids:
        snap = repository.get_latest_snapshot_for_player(conn, pid)
        if snap is None:
            continue
        positions[pid] = ELEMENT_TYPE_ID_TO_POSITION.get(snap["element_type"], "MID")
        ownership[pid] = snap["selected_by_percent"] or 0.0
        now_cost[pid] = snap["now_cost"]
        total_points[pid] = snap["total_points"] or 0
        web_names[pid] = snap["web_name"]

    by_position: dict[str, list[int]] = {pos: [] for pos in POSITIONS}
    for pid, pos in positions.items():
        by_position.setdefault(pos, []).append(pid)

    results: dict[int, ValueResult] = {}
    for pos, pids in by_position.items():
        xpts_values = [xpts_horizon.get(pid, 0.0) for pid in pids]
        ownership_values = [ownership[pid] for pid in pids]
        for pid in pids:
            xpts = xpts_horizon.get(pid, 0.0)
            xpts_pct = _percentile_rank(xpts, xpts_values)
            own_pct = _percentile_rank(ownership[pid], ownership_values)
            ppm = total_points[pid] / (now_cost[pid] / 10) if now_cost[pid] > 0 else 0.0

            differential_score = xpts_pct * (1 - ownership[pid] / 100) ** config.differential_gamma
            template_score = (xpts_pct + own_pct) / 2

            results[pid] = ValueResult(
                player_id=pid,
                position=pos,
                web_name=web_names[pid],
                now_cost_millions=round(now_cost[pid] / 10, 1),
                points_per_million=round(ppm, 2),
                xpts_horizon=round(xpts, 2),
                xpts_percentile_in_position=round(xpts_pct, 3),
                ownership_percentile_in_position=round(own_pct, 3),
                selected_by_percent=ownership[pid],
                differential_score=round(differential_score, 3),
                template_score=round(template_score, 3),
            )
    return results


def top_differentials(
    results: dict[int, ValueResult], position: str, ownership_threshold: float, n: int = 5
) -> list[ValueResult]:
    candidates = [r for r in results.values() if r.position == position and r.selected_by_percent < ownership_threshold]
    return sorted(candidates, key=lambda r: r.differential_score, reverse=True)[:n]


def top_template_picks(results: dict[int, ValueResult], position: str, n: int = 5) -> list[ValueResult]:
    candidates = [r for r in results.values() if r.position == position]
    return sorted(candidates, key=lambda r: r.template_score, reverse=True)[:n]
