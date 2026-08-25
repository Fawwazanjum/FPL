"""Squad transfer optimizer: single-shot ILP (PuLP + bundled CBC) over a
candidate pool (current squad + scoped top-owned/top-form players), respecting
FPL's legal-squad constraints and the real budget (sell prices, not current
prices, for currently-owned players).

Always solves TWO plans — "banked" (transfers capped at free transfers, no
hits ever) and "hit" (hits allowed up to max_transfers_considered) — and only
recommends taking a hit if it nets a clear margin over banking, per the user's
explicit preference: hits should be avoided unless clearly worth it, not taken
any time they're marginally net-positive.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pulp

from fpl_model.analysis.squad_state import SquadState
from fpl_model.config import AppConfig
from fpl_model.constants import MAX_PER_CLUB, POSITION_REQUIREMENTS, STARTING_XI_BOUNDS

log = logging.getLogger(__name__)

# A bench player's expected contribution isn't uniform across positions. Bench
# DEF/MID/FWD have real recurring value: over a multi-gameweek horizon a
# squad's 12th-15th players genuinely rotate into the starting XI as fixtures/
# form shift week to week (that's what lineup_optimizer re-solving every week
# for free is for) — not just injury cover.
#
# GKP is set lower than outfield but deliberately NOT near-zero: a second
# mid-price GK with a fixture schedule that complements your first-choice
# keeper (one tends to have the nicer fixture whenever the other doesn't) is a
# real, commonly-used FPL strategy, and its value is exactly this rotation
# potential, not backup insurance. This constant can't capture that properly
# though — whether GK #2 is a genuine rotation partner or just a backup
# depends on comparing that SPECIFIC pair's fixture schedules against each
# other, a pairwise interaction a linear objective over many independent
# candidates can't express (GK #2's value depends on which other GK you also
# own, not on GK #2 alone). Properly solving that needs per-pair fixture
# comparison logic — out of scope here; this flat constant is a middle-ground
# default, not a rotation-pair evaluator. If you're deliberately building a
# rotation pair, ask directly and the fixture data can be checked by hand.
BENCH_WEIGHT_BY_POSITION = {"GKP": 0.15, "DEF": 0.4, "MID": 0.4, "FWD": 0.4}
DEFAULT_BENCH_WEIGHT = 0.3


@dataclass
class TransferPlan:
    new_squad: list[int]
    transfers_in: list[int]
    transfers_out: list[int]
    transfers_made: int
    hits_taken: int
    hit_cost_applied: int
    gross_xpts: float
    net_xpts: float
    budget_remaining_tenths: int
    feasible: bool = True


@dataclass
class TransferRecommendation:
    recommended: str  # "bank" or "hit"
    banked_option: TransferPlan
    hit_option: TransferPlan
    margin: float
    reasoning: list[str] = field(default_factory=list)


def _price_used(squad_state: SquadState, prices: dict[int, int], player_id: int) -> int:
    if player_id in squad_state.sell_prices:
        return squad_state.sell_prices[player_id]
    return prices[player_id]


def solve(
    squad_state: SquadState,
    candidate_ids: list[int],
    positions: dict[int, str],
    clubs: dict[int, int],
    prices: dict[int, int],
    xpts_horizon: dict[int, float],
    free_transfers: int,
    hit_cost: int,
    allow_hits: bool,
    max_transfers: int,
) -> TransferPlan:
    candidate_ids = [p for p in candidate_ids if p in positions and p in clubs and (p in squad_state.sell_prices or p in prices)]
    missing_squad = [p for p in squad_state.current_squad if p not in candidate_ids]
    if missing_squad:
        raise ValueError(f"Current squad players missing from candidate pool (cannot be 'kept'): {missing_squad}")

    prob = pulp.LpProblem("fpl_transfer", pulp.LpMaximize)
    x = {p: pulp.LpVariable(f"x_{p}", cat="Binary") for p in candidate_ids}
    # Jointly decide the best starting XI within each candidate squad, so the
    # objective values starters at full xPts and bench players at a small
    # discount instead of treating all 15 slots as equally valuable.
    y = {p: pulp.LpVariable(f"y_{p}", cat="Binary") for p in candidate_ids}

    for pos, count in POSITION_REQUIREMENTS.items():
        prob += pulp.lpSum(x[p] for p in candidate_ids if positions[p] == pos) == count, f"pos_{pos}"

    for club in set(clubs.values()):
        prob += pulp.lpSum(x[p] for p in candidate_ids if clubs[p] == club) <= MAX_PER_CLUB, f"club_{club}"

    budget_available = squad_state.bank_tenths + sum(squad_state.sell_prices[p] for p in squad_state.current_squad)
    prob += pulp.lpSum(_price_used(squad_state, prices, p) * x[p] for p in candidate_ids) <= budget_available, "budget"

    for p in candidate_ids:
        prob += y[p] <= x[p], f"start_requires_squad_{p}"
    prob += pulp.lpSum(y.values()) == 11, "starting_xi_size"
    for pos, (lo, hi) in STARTING_XI_BOUNDS.items():
        pos_sum = pulp.lpSum(y[p] for p in candidate_ids if positions[p] == pos)
        prob += pos_sum >= lo, f"formation_min_{pos}"
        prob += pos_sum <= hi, f"formation_max_{pos}"

    transfers_in_expr = pulp.lpSum(x[p] for p in candidate_ids if p not in squad_state.current_squad)

    def _bench_weight(p: int) -> float:
        return BENCH_WEIGHT_BY_POSITION.get(positions[p], DEFAULT_BENCH_WEIGHT)

    squad_value = pulp.lpSum(
        xpts_horizon.get(p, 0.0) * (_bench_weight(p) * x[p] + (1 - _bench_weight(p)) * y[p]) for p in candidate_ids
    )

    h = None
    if allow_hits:
        h = pulp.LpVariable("hits", lowBound=0, cat="Integer")
        prob += h >= transfers_in_expr - free_transfers, "hit_definition"
        prob += transfers_in_expr <= max_transfers, "max_transfers"
        objective = squad_value - hit_cost * h
    else:
        prob += transfers_in_expr <= free_transfers, "max_transfers_no_hits"
        objective = squad_value

    prob += objective
    status = prob.solve(pulp.PULP_CBC_CMD(msg=0))

    if pulp.LpStatus[status] != "Optimal":
        log.error("Transfer ILP did not solve to optimality (status=%s)", pulp.LpStatus[status])
        return TransferPlan([], [], [], 0, 0, 0, 0.0, 0.0, budget_available, feasible=False)

    new_squad = [p for p in candidate_ids if x[p].value() and x[p].value() > 0.5]
    implied_starters = {p for p in candidate_ids if y[p].value() and y[p].value() > 0.5}
    transfers_in = [p for p in new_squad if p not in squad_state.current_squad]
    transfers_out = [p for p in squad_state.current_squad if p not in new_squad]
    hits_taken = int(round(h.value())) if h is not None and h.value() else 0
    hit_cost_applied = hits_taken * hit_cost
    # Same starting-XI-weighted value the objective actually optimized, so the
    # reported gross/net figures are internally consistent with the decision.
    gross_xpts = sum(
        xpts_horizon.get(p, 0.0) * (1.0 if p in implied_starters else _bench_weight(p)) for p in new_squad
    )
    net_xpts = gross_xpts - hit_cost_applied
    spent = sum(_price_used(squad_state, prices, p) for p in new_squad)

    return TransferPlan(
        new_squad=new_squad,
        transfers_in=transfers_in,
        transfers_out=transfers_out,
        transfers_made=len(transfers_in),
        hits_taken=hits_taken,
        hit_cost_applied=hit_cost_applied,
        gross_xpts=gross_xpts,
        net_xpts=net_xpts,
        budget_remaining_tenths=budget_available - spent,
    )


def solve_unconstrained_best_squad(
    candidate_ids: list[int],
    positions: dict[int, str],
    clubs: dict[int, int],
    prices: dict[int, int],
    xpts_horizon: dict[int, float],
    budget_tenths: int,
) -> TransferPlan:
    """Best possible 15 from scratch within a budget, ignoring the current squad
    entirely — used by chips.py (Phase 4) to evaluate wildcard/free-hit value."""
    prob = pulp.LpProblem("fpl_ideal_squad", pulp.LpMaximize)
    x = {p: pulp.LpVariable(f"x_{p}", cat="Binary") for p in candidate_ids}
    y = {p: pulp.LpVariable(f"y_{p}", cat="Binary") for p in candidate_ids}

    for pos, count in POSITION_REQUIREMENTS.items():
        prob += pulp.lpSum(x[p] for p in candidate_ids if positions[p] == pos) == count
    for club in set(clubs.values()):
        prob += pulp.lpSum(x[p] for p in candidate_ids if clubs[p] == club) <= MAX_PER_CLUB
    prob += pulp.lpSum(prices[p] * x[p] for p in candidate_ids) <= budget_tenths

    for p in candidate_ids:
        prob += y[p] <= x[p]
    prob += pulp.lpSum(y.values()) == 11
    for pos, (lo, hi) in STARTING_XI_BOUNDS.items():
        pos_sum = pulp.lpSum(y[p] for p in candidate_ids if positions[p] == pos)
        prob += pos_sum >= lo
        prob += pos_sum <= hi

    def _bench_weight(p: int) -> float:
        return BENCH_WEIGHT_BY_POSITION.get(positions[p], DEFAULT_BENCH_WEIGHT)

    prob += pulp.lpSum(
        xpts_horizon.get(p, 0.0) * (_bench_weight(p) * x[p] + (1 - _bench_weight(p)) * y[p]) for p in candidate_ids
    )

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[status] != "Optimal":
        return TransferPlan([], [], [], 0, 0, 0, 0.0, 0.0, budget_tenths, feasible=False)

    new_squad = [p for p in candidate_ids if x[p].value() and x[p].value() > 0.5]
    implied_starters = {p for p in candidate_ids if y[p].value() and y[p].value() > 0.5}
    gross_xpts = sum(xpts_horizon.get(p, 0.0) * (1.0 if p in implied_starters else _bench_weight(p)) for p in new_squad)
    spent = sum(prices[p] for p in new_squad)
    return TransferPlan(
        new_squad=new_squad, transfers_in=new_squad, transfers_out=[], transfers_made=len(new_squad),
        hits_taken=0, hit_cost_applied=0, gross_xpts=gross_xpts, net_xpts=gross_xpts,
        budget_remaining_tenths=budget_tenths - spent,
    )


def recommend_transfers(
    squad_state: SquadState,
    candidate_ids: list[int],
    positions: dict[int, str],
    clubs: dict[int, int],
    prices: dict[int, int],
    xpts_horizon: dict[int, float],
    config: AppConfig,
) -> TransferRecommendation:
    banked = solve(
        squad_state, candidate_ids, positions, clubs, prices, xpts_horizon,
        squad_state.free_transfers_available, config.optimizer.hit_cost,
        allow_hits=False, max_transfers=squad_state.free_transfers_available,
    )
    hit = solve(
        squad_state, candidate_ids, positions, clubs, prices, xpts_horizon,
        squad_state.free_transfers_available, config.optimizer.hit_cost,
        allow_hits=True, max_transfers=config.optimizer.max_transfers_considered,
    )

    margin = hit.net_xpts - banked.net_xpts
    reasoning = []

    if hit.hits_taken == 0:
        recommended = "bank"
        reasoning.append("Best move fits within free transfers — no hit needed.")
    elif margin >= config.optimizer.hit_margin_required:
        recommended = "hit"
        reasoning.append(
            f"Taking {hit.hits_taken} hit(s) (-{hit.hit_cost_applied}) nets {margin:.2f} more points over the "
            f"horizon than banking — clears the {config.optimizer.hit_margin_required:.1f}pt margin required."
        )
    else:
        recommended = "bank"
        reasoning.append(
            f"A hit would only net {margin:.2f} extra points over the horizon — below the "
            f"{config.optimizer.hit_margin_required:.1f}pt margin required, so banking is safer."
        )

    if banked.transfers_made == 0 and hit.hits_taken == 0:
        reasoning.append("Current squad already looks optimal within the candidate pool — no transfer recommended.")

    return TransferRecommendation(recommended=recommended, banked_option=banked, hit_option=hit, margin=margin, reasoning=reasoning)
