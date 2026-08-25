from fpl_model.optimizer.lineup_optimizer import solve


def _positions():
    positions = {1: "GKP", 2: "GKP"}
    for p in (3, 4, 5, 6, 7):
        positions[p] = "DEF"
    for p in (8, 9, 10, 11, 12):
        positions[p] = "MID"
    for p in (13, 14, 15):
        positions[p] = "FWD"
    return positions


def test_starting_xi_respects_formation_bounds_and_size():
    positions = _positions()
    xpts = {1: 5.0, 2: 3.0}
    xpts.update({p: 1.0 for p in (3, 4, 5, 6, 7)})  # weak defenders
    xpts.update({p: 8.0 for p in (8, 9, 10, 11, 12)})  # strong midfielders
    xpts.update({p: 8.0 for p in (13, 14, 15)})  # strong forwards

    plan = solve(list(range(1, 16)), positions, xpts)

    assert plan.feasible
    assert len(plan.starting_xi) == 11
    def_count = sum(1 for p in plan.starting_xi if positions[p] == "DEF")
    assert def_count == 3  # minimum allowed — weak defenders squeezed out for strong MID/FWD
    assert 1 in plan.starting_xi  # the better GKP (5.0) starts over the weaker one (3.0)
    assert 2 not in plan.starting_xi


def test_captain_is_highest_xpts_starter():
    positions = _positions()
    xpts = {1: 5.0, 2: 3.0}
    xpts.update({p: 2.0 for p in (3, 4, 5, 6, 7)})
    xpts.update({p: 4.0 for p in (8, 9, 10, 11)})
    xpts[12] = 9.0  # standout starter
    xpts.update({p: 3.0 for p in (13, 14, 15)})

    plan = solve(list(range(1, 16)), positions, xpts)

    assert plan.captain == 12
    assert plan.vice_captain is not None
    assert plan.vice_captain != plan.captain
    assert plan.vice_captain in plan.starting_xi


def test_vice_captain_is_second_highest_scorer_not_arbitrary():
    positions = _positions()
    xpts = {1: 5.0, 2: 3.0}
    xpts.update({p: 2.0 for p in (3, 4, 5, 6, 7)})
    xpts[8] = 9.0   # captain
    xpts[9] = 7.0   # should be vice — second highest among starters
    xpts.update({p: 4.0 for p in (10, 11, 12)})
    xpts.update({p: 3.0 for p in (13, 14, 15)})

    plan = solve(list(range(1, 16)), positions, xpts)

    assert plan.captain == 8
    assert plan.vice_captain == 9


def test_bench_order_sorted_by_xpts_descending():
    positions = _positions()
    xpts = {1: 5.0, 2: 3.0}
    xpts.update({p: 1.0 for p in (3, 4, 5, 6, 7)})
    xpts.update({p: 8.0 for p in (8, 9, 10, 11, 12)})
    xpts.update({p: 8.0 for p in (13, 14, 15)})

    plan = solve(list(range(1, 16)), positions, xpts)

    bench_values = [xpts[p] for p in plan.bench_order]
    assert bench_values == sorted(bench_values, reverse=True)
    assert set(plan.bench_order) | set(plan.starting_xi) == set(range(1, 16))
