"""Chip timing advice: wildcard, free hit, bench boost, triple captain, plus a
captaincy summary. Rule-based on top of the xPts/optimizer machinery already
built in Phases 2-3, not a new model.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from fpl_model.analysis.fixtures import detect_blank_gameweeks, detect_double_gameweeks
from fpl_model.analysis.squad_state import SquadState
from fpl_model.analysis.xpts import XptsBreakdown
from fpl_model.config import AppConfig
from fpl_model.optimizer.lineup_optimizer import solve as solve_lineup
from fpl_model.optimizer.transfer_optimizer import TransferRecommendation, compute_squad_value, solve_unconstrained_best_squad
from fpl_model.storage import repository


@dataclass
class ChipAdvice:
    chip_name: str
    recommended_now: bool
    reasoning: str
    best_window_gw: int | None = None


@dataclass
class ChipAdviceBundle:
    captain: ChipAdvice
    wildcard: ChipAdvice
    free_hit: ChipAdvice
    bench_boost: ChipAdvice
    triple_captain: ChipAdvice
    blank_gameweeks: dict[int, list[int]] = field(default_factory=dict)
    double_gameweeks: dict[int, list[int]] = field(default_factory=dict)


def recommend_captain(squad_state: SquadState, xpts_results: dict[int, XptsBreakdown], positions: dict[int, str]) -> ChipAdvice:
    lineup = solve_lineup(squad_state.current_squad, positions, {pid: xr.total for pid, xr in xpts_results.items()})
    if lineup.captain is None:
        return ChipAdvice("captain", False, "Could not determine a captain — insufficient xPts data for this squad.")
    captain_xr = xpts_results.get(lineup.captain)
    captain_total = captain_xr.total if captain_xr else 0.0
    detail = f" ({captain_xr.reasoning})" if captain_xr else ""
    return ChipAdvice(
        "captain", True,
        f"Captain: player {lineup.captain} at {captain_total:.2f} xPts this gameweek{detail}. "
        f"Vice: player {lineup.vice_captain}.",
    )


def recommend_wildcard(
    squad_state: SquadState,
    candidate_ids: list[int],
    positions: dict[int, str],
    clubs: dict[int, int],
    prices: dict[int, int],
    xpts_horizon: dict[int, float],
    transfer_rec: TransferRecommendation,
    config: AppConfig,
) -> ChipAdvice:
    if "wildcard" not in squad_state.chips_available:
        return ChipAdvice("wildcard", False, "Wildcard already used (or unavailable this half-season).")

    total_budget = squad_state.bank_tenths + sum(squad_state.sell_prices[p] for p in squad_state.current_squad)
    ideal = solve_unconstrained_best_squad(candidate_ids, positions, clubs, prices, xpts_horizon, total_budget)
    if not ideal.feasible:
        return ChipAdvice("wildcard", False, "Could not compute an unconstrained ideal squad from the current candidate pool.")

    banked_value = transfer_rec.banked_option.net_xpts
    gap = ideal.gross_xpts - banked_value
    games_played = squad_state.gameweek  # last completed gameweek == games of real data available

    if gap < config.chips.wildcard_gap_threshold:
        return ChipAdvice(
            "wildcard", False,
            f"Best achievable squad is only {gap:.1f} pts better than your banked-transfer squad over the horizon — "
            f"not enough to justify a wildcard (needs {config.chips.wildcard_gap_threshold:.1f}+).",
        )

    if games_played < config.chips.min_games_for_wildcard_confidence:
        return ChipAdvice(
            "wildcard", False,
            f"Gap looks large ({gap:.1f} pts) but is based on only {games_played} gameweek(s) of real season data — "
            f"too early to trust this magnitude. Recommend re-checking after "
            f"{config.chips.min_games_for_wildcard_confidence} gameweeks before committing a wildcard.",
        )

    return ChipAdvice(
        "wildcard", True,
        f"Gap of {gap:.1f} pts over the horizon, based on {games_played} gameweeks of real data — "
        f"clears both the value and data-maturity thresholds.",
    )


def recommend_free_hit(
    conn: sqlite3.Connection, squad_state: SquadState, positions: dict[int, str], clubs: dict[int, int],
    from_gw: int, horizon: int, config: AppConfig,
) -> tuple[ChipAdvice, dict[int, list[int]]]:
    if "freehit" not in squad_state.chips_available:
        return ChipAdvice("freehit", False, "Free Hit already used (or unavailable)."), {}

    team_ids = list({clubs[p] for p in squad_state.current_squad if p in clubs})
    blanks = detect_blank_gameweeks(conn, team_ids, from_gw, horizon)

    for gw, blank_team_ids in blanks.items():
        blank_team_set = set(blank_team_ids)
        affected_starters = [p for p in squad_state.starting_xi if clubs.get(p) in blank_team_set]
        if len(affected_starters) >= config.chips.free_hit_blank_threshold:
            return ChipAdvice(
                "freehit", True,
                f"GW{gw}: {len(affected_starters)} of your starting XI have no fixture (blank gameweek) — "
                f"a Free Hit would let you field a full XI just for that week without disrupting your real squad.",
                best_window_gw=gw,
            ), blanks

    return ChipAdvice("freehit", False, "No blank gameweek in the horizon affects enough of your starting XI to justify a Free Hit."), blanks


def recommend_bench_boost(
    conn: sqlite3.Connection, squad_state: SquadState, positions: dict[int, str], clubs: dict[int, int],
    scoring, weights, team_strength, from_gw: int, horizon: int, config: AppConfig,
) -> tuple[ChipAdvice, dict[int, list[int]]]:
    """Evaluated on the bench's own projected value in EACH gameweek of the
    horizon, not gated on a double gameweek existing — a double gameweek is
    one way a bench week can be strong, but a genuinely deep squad (e.g. built
    on a recent wildcard) can have a bench worth activating on a normal single-
    fixture week too. Gating this on "no double gameweek -> never recommend"
    was a real bug (thin bench weeks with a DGW would pass; a strong bench in
    an ordinary week never got a chance), not just an overly-blunt heuristic.
    """
    if "bboost" not in squad_state.chips_available:
        return ChipAdvice("bboost", False, "Bench Boost already used (or unavailable)."), {}

    from fpl_model.analysis.xpts import compute_player_xpts_gw

    team_ids = list({clubs[p] for p in squad_state.current_squad if p in clubs})
    doubles = detect_double_gameweeks(conn, team_ids, from_gw, horizon)

    best_gw, best_value = None, 0.0
    for gw in range(from_gw, from_gw + horizon):
        bench_value = 0.0
        for p in squad_state.bench:
            breakdown = compute_player_xpts_gw(conn, p, gw, scoring, weights, team_strength)
            if breakdown is not None:
                bench_value += breakdown.total
        if bench_value > best_value:
            best_gw, best_value = gw, bench_value

    if best_gw is not None and best_value >= config.chips.bench_boost_min_bench_value:
        is_double = best_gw in doubles and any(clubs.get(p) in set(doubles[best_gw]) for p in squad_state.bench)
        qualifier = "boosted by a double gameweek" if is_double else "strong on fixtures/form alone, no double gameweek needed"
        return ChipAdvice(
            "bboost", True,
            f"GW{best_gw}: your bench projects {best_value:.1f} combined pts ({qualifier}) — worth Bench Boosting.",
            best_window_gw=best_gw,
        ), doubles

    return ChipAdvice(
        "bboost", False,
        f"Best bench week in the horizon projects only {best_value:.1f} pts — below the "
        f"{config.chips.bench_boost_min_bench_value:.1f}pt threshold.",
    ), doubles


def recommend_triple_captain(
    conn: sqlite3.Connection,
    squad_state: SquadState,
    clubs: dict[int, int],
    normal_week_best_xpts: float,
    double_gameweeks: dict[int, list[int]],
    scoring,
    weights,
    team_strength,
    config: AppConfig,
) -> ChipAdvice:
    if "3xc" not in squad_state.chips_available:
        return ChipAdvice("3xc", False, "Triple Captain already used (or unavailable).")

    if not double_gameweeks:
        return ChipAdvice("3xc", False, "No double gameweeks in the horizon — Triple Captain is best saved for one.")

    from fpl_model.analysis.xpts import compute_player_xpts_gw

    # Recompute per-gameweek xPts at the ACTUAL double-gameweek's gameweek
    # number (compute_player_xpts_gw sums both fixtures automatically when
    # called there) rather than reusing next-gameweek's single-fixture values,
    # which wouldn't reflect a different future gameweek's double at all.
    best_gw, best_candidate_value = None, 0.0
    for gw, dgw_team_ids in double_gameweeks.items():
        dgw_team_set = set(dgw_team_ids)
        candidates = [p for p in squad_state.current_squad if clubs.get(p) in dgw_team_set]
        for p in candidates:
            breakdown = compute_player_xpts_gw(conn, p, gw, scoring, weights, team_strength)
            if breakdown is not None and breakdown.total > best_candidate_value:
                best_gw, best_candidate_value = gw, breakdown.total

    if best_gw is None:
        return ChipAdvice("3xc", False, "Double gameweek(s) found, but no xPts data available for players in those clubs.")

    uplift = best_candidate_value - normal_week_best_xpts
    if uplift >= config.chips.triple_captain_uplift_threshold:
        return ChipAdvice(
            "3xc", True,
            f"GW{best_gw}: best double-gameweek captain option projects {best_candidate_value:.1f} xPts, "
            f"{uplift:.1f} pts higher than a normal week's best captain pick — worth Triple Captaining.",
            best_window_gw=best_gw,
        )

    return ChipAdvice("3xc", False, "No double-gameweek captain option clears the uplift threshold over a normal week yet.")


def recommend_all(
    conn: sqlite3.Connection,
    squad_state: SquadState,
    candidate_ids: list[int],
    positions: dict[int, str],
    clubs: dict[int, int],
    prices: dict[int, int],
    xpts_horizon: dict[int, float],
    xpts_results: dict[int, XptsBreakdown],
    transfer_rec: TransferRecommendation,
    from_gw: int,
    config: AppConfig,
    scoring=None,
    weights=None,
    team_strength=None,
) -> ChipAdviceBundle:
    horizon = config.xpts_horizon_gws
    xpts_next_gw = {pid: xr.total for pid, xr in xpts_results.items()}
    normal_week_best_xpts = max(xpts_next_gw.values(), default=0.0)

    captain_advice = recommend_captain(squad_state, xpts_results, positions)
    wildcard_advice = recommend_wildcard(squad_state, candidate_ids, positions, clubs, prices, xpts_horizon, transfer_rec, config)
    free_hit_advice, blanks = recommend_free_hit(conn, squad_state, positions, clubs, from_gw, horizon, config)
    bench_boost_advice, doubles = recommend_bench_boost(conn, squad_state, positions, clubs, scoring, weights, team_strength, from_gw, horizon, config)
    triple_captain_advice = recommend_triple_captain(
        conn, squad_state, clubs, normal_week_best_xpts, doubles, scoring, weights, team_strength, config
    )

    return ChipAdviceBundle(
        captain=captain_advice,
        wildcard=wildcard_advice,
        free_hit=free_hit_advice,
        bench_boost=bench_boost_advice,
        triple_captain=triple_captain_advice,
        blank_gameweeks=blanks,
        double_gameweeks=doubles,
    )
