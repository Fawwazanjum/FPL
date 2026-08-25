from fpl_model.analysis.squad_state import SquadState
from fpl_model.optimizer.transfer_optimizer import recommend_transfers, solve


def _base_squad_state(free_transfers=1, bank_tenths=250):
    squad = list(range(1, 16))
    sell_prices = {p: 50 for p in squad}
    return SquadState(
        team_id=1, gameweek=1, upcoming_gameweek=2, current_squad=squad, starting_xi=squad[:11],
        bench=squad[11:], captain_id=squad[0], vice_captain_id=squad[1], bank_tenths=bank_tenths,
        squad_value_tenths=750, free_transfers_available=free_transfers, chips_available=[], chips_used=[],
        purchase_prices=sell_prices, sell_prices=sell_prices,
    )


def _base_positions():
    positions = {}
    for p in (1, 2):
        positions[p] = "GKP"
    for p in (3, 4, 5, 6, 7):
        positions[p] = "DEF"
    for p in (8, 9, 10, 11, 12):
        positions[p] = "MID"
    for p in (13, 14, 15):
        positions[p] = "FWD"
    return positions


def _base_clubs(candidate_ids):
    return {p: p for p in candidate_ids}  # every player a unique club — never binds MAX_PER_CLUB


def test_banked_plan_takes_clear_single_upgrade_within_free_transfer():
    squad_state = _base_squad_state(free_transfers=1)
    positions = _base_positions()
    positions[100] = "MID"  # upgrade candidate for weak MID player 8
    candidate_ids = squad_state.current_squad + [100]
    clubs = _base_clubs(candidate_ids)
    prices = {100: 50}
    xpts = {p: 5.0 for p in squad_state.current_squad}
    xpts[8] = 2.0  # weak starter
    xpts[100] = 9.0  # clear upgrade, same price

    plan = solve(
        squad_state, candidate_ids, positions, clubs, prices, xpts,
        free_transfers=1, hit_cost=4, allow_hits=False, max_transfers=1,
    )
    assert plan.feasible
    assert plan.transfers_in == [100]
    assert plan.transfers_out == [8]
    assert plan.hits_taken == 0


def test_no_transfer_when_squad_already_optimal():
    squad_state = _base_squad_state(free_transfers=1)
    positions = _base_positions()
    candidate_ids = squad_state.current_squad
    clubs = _base_clubs(candidate_ids)
    prices = {}
    xpts = {p: 5.0 for p in squad_state.current_squad}

    plan = solve(
        squad_state, candidate_ids, positions, clubs, prices, xpts,
        free_transfers=1, hit_cost=4, allow_hits=False, max_transfers=1,
    )
    assert plan.transfers_made == 0


def test_recommends_hit_when_margin_clearly_exceeds_threshold():
    # Uses DEF (not MID) deliberately: the squad's 5 DEF are all valued above
    # the MID/FWD baseline, so all 5 always start (no bench-avoidance loophole
    # like there would be with only 2-3 needed out of 5) — this forces a real
    # transfer decision instead of a free "just bench the weak one" escape.
    squad_state = _base_squad_state(free_transfers=1)
    positions = _base_positions()
    positions[100] = "DEF"
    positions[101] = "DEF"
    candidate_ids = squad_state.current_squad + [100, 101]
    clubs = _base_clubs(candidate_ids)
    prices = {100: 50, 101: 50}
    xpts = {p: 5.0 for p in squad_state.current_squad}
    for p in (3, 4, 5, 6, 7):
        xpts[p] = 6.0  # all 5 DEF always start (6.0 > 5.0 MID/FWD baseline)
    xpts[100] = 15.0  # +9 upgrade over any current DEF
    xpts[101] = 15.0  # +9 upgrade over any current DEF

    from fpl_model.config import AppConfig

    config = AppConfig(team_id=1)
    rec = recommend_transfers(squad_state, candidate_ids, positions, clubs, prices, xpts, config)

    assert rec.recommended == "hit"
    assert rec.hit_option.hits_taken == 1
    assert set(rec.hit_option.transfers_in) == {100, 101}
    assert rec.margin >= config.optimizer.hit_margin_required


def test_recommends_bank_when_hit_margin_too_small():
    squad_state = _base_squad_state(free_transfers=1)
    positions = _base_positions()
    positions[100] = "DEF"
    positions[101] = "DEF"
    candidate_ids = squad_state.current_squad + [100, 101]
    clubs = _base_clubs(candidate_ids)
    prices = {100: 50, 101: 50}
    xpts = {p: 5.0 for p in squad_state.current_squad}
    for p in (3, 4, 5, 6, 7):
        xpts[p] = 6.0
    xpts[100] = 7.0  # +1 upgrade only
    xpts[101] = 7.0  # +1 upgrade only

    from fpl_model.config import AppConfig

    config = AppConfig(team_id=1)
    rec = recommend_transfers(squad_state, candidate_ids, positions, clubs, prices, xpts, config)

    assert rec.recommended == "bank"
    assert rec.banked_option.hits_taken == 0


def test_bench_outfield_upgrade_preferred_over_equal_bench_gk_upgrade():
    # With only 1 free transfer and two equally-sized bench upgrades on offer
    # (same price, same xPts gain), the optimizer should prefer upgrading a
    # bench outfield player over a bench GK — a backup GK almost never plays,
    # but a bench DEF/MID/FWD has real recurring rotation-in value.
    squad_state = _base_squad_state(free_transfers=1)
    positions = _base_positions()
    positions[100] = "GKP"  # bench-GK upgrade candidate
    positions[101] = "DEF"  # bench-DEF upgrade candidate
    candidate_ids = squad_state.current_squad + [100, 101]
    clubs = _base_clubs(candidate_ids)
    prices = {100: 50, 101: 50}

    xpts = {p: 5.0 for p in squad_state.current_squad}
    xpts[1] = 5.0   # starting GK, clearly better than player 2
    xpts[2] = 3.0   # bench GK (weak, stays benched)
    for p in (3, 4, 5):
        xpts[p] = 8.0  # 3 strong DEF, always start (DEF min=3)
    for p in (6, 7):
        xpts[p] = 3.0  # 2 weak DEF, below MID/FWD baseline -> stay benched
    xpts[100] = 13.0  # +10 over the weak bench GK
    xpts[101] = 13.0  # +10 over a weak bench DEF

    plan = solve(
        squad_state, candidate_ids, positions, clubs, prices, xpts,
        free_transfers=1, hit_cost=4, allow_hits=False, max_transfers=1,
    )
    assert plan.transfers_in == [101]


def test_budget_constraint_respected():
    squad_state = _base_squad_state(free_transfers=1, bank_tenths=0)  # no spare cash at all
    positions = _base_positions()
    positions[100] = "MID"
    candidate_ids = squad_state.current_squad + [100]
    clubs = _base_clubs(candidate_ids)
    prices = {100: 200}  # far too expensive given zero bank and a 50-tenths sell price
    xpts = {p: 5.0 for p in squad_state.current_squad}
    xpts[100] = 99.0  # would be picked if budget allowed it

    plan = solve(
        squad_state, candidate_ids, positions, clubs, prices, xpts,
        free_transfers=1, hit_cost=4, allow_hits=False, max_transfers=1,
    )
    assert 100 not in plan.new_squad
