"""Given a fixed 15-man squad, picks the legal starting XI + captain/vice that
maximizes next-gameweek xPts (captaincy uses single-GW xPts, not the transfer
horizon — the captain doubles whatever happens this week specifically).
"""

from __future__ import annotations

from dataclasses import dataclass

import pulp

from fpl_model.constants import STARTING_XI_BOUNDS


@dataclass
class LineupPlan:
    starting_xi: list[int]
    bench_order: list[int]
    captain: int | None
    vice_captain: int | None
    projected_points: float
    feasible: bool = True


def solve(squad: list[int], positions: dict[int, str], xpts_next_gw: dict[int, float]) -> LineupPlan:
    prob = pulp.LpProblem("fpl_lineup", pulp.LpMaximize)
    y = {p: pulp.LpVariable(f"y_{p}", cat="Binary") for p in squad}
    c = {p: pulp.LpVariable(f"c_{p}", cat="Binary") for p in squad}
    v = {p: pulp.LpVariable(f"v_{p}", cat="Binary") for p in squad}

    prob += pulp.lpSum(y.values()) == 11

    for pos, (lo, hi) in STARTING_XI_BOUNDS.items():
        pos_sum = pulp.lpSum(y[p] for p in squad if positions.get(p) == pos)
        prob += pos_sum >= lo
        prob += pos_sum <= hi

    for p in squad:
        prob += c[p] <= y[p]
        prob += v[p] <= y[p]
        prob += c[p] + v[p] <= 1
    prob += pulp.lpSum(c.values()) == 1
    prob += pulp.lpSum(v.values()) == 1

    # Vice-captain gets no real points bonus under normal circumstances (only
    # relevant if the captain doesn't play), so without some tie-breaking
    # weight the solver picks arbitrarily among all starters — a small epsilon
    # (far too small to ever change the XI/captain decision) makes it
    # deterministically pick the second-highest scorer, which is what a vice
    # captain pick should actually mean.
    vice_tiebreak_epsilon = 1e-4
    prob += (
        pulp.lpSum(xpts_next_gw.get(p, 0.0) * y[p] for p in squad)
        + pulp.lpSum(xpts_next_gw.get(p, 0.0) * c[p] for p in squad)
        + vice_tiebreak_epsilon * pulp.lpSum(xpts_next_gw.get(p, 0.0) * v[p] for p in squad)
    )

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[status] != "Optimal":
        return LineupPlan([], [], None, None, 0.0, feasible=False)

    starting_xi = [p for p in squad if y[p].value() and y[p].value() > 0.5]
    captain = next((p for p in squad if c[p].value() and c[p].value() > 0.5), None)
    vice_captain = next((p for p in squad if v[p].value() and v[p].value() > 0.5), None)
    bench = sorted((p for p in squad if p not in starting_xi), key=lambda p: xpts_next_gw.get(p, 0.0), reverse=True)

    projected = sum(xpts_next_gw.get(p, 0.0) for p in starting_xi)
    if captain is not None:
        projected += xpts_next_gw.get(captain, 0.0)

    return LineupPlan(
        starting_xi=starting_xi, bench_order=bench, captain=captain, vice_captain=vice_captain,
        projected_points=projected,
    )
