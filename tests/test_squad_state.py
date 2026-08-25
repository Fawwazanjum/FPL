from fpl_model.analysis.squad_state import compute_free_transfers


def gw_row(gameweek, event_transfers=0):
    return {"gameweek": gameweek, "event_transfers": event_transfers}


def test_baseline_one_free_transfer_entering_gw2():
    history = [gw_row(1)]
    assert compute_free_transfers(history, [], upcoming_gw=2) == 1


def test_unused_transfer_rolls_over():
    history = [gw_row(1), gw_row(2, event_transfers=0)]
    assert compute_free_transfers(history, [], upcoming_gw=3) == 2


def test_used_transfer_does_not_roll_over():
    history = [gw_row(1), gw_row(2, event_transfers=1)]
    assert compute_free_transfers(history, [], upcoming_gw=3) == 1


def test_hit_does_not_go_negative():
    history = [gw_row(1), gw_row(2, event_transfers=3)]
    assert compute_free_transfers(history, [], upcoming_gw=3) == 1


def test_wildcard_gameweek_does_not_consume_bank():
    history = [gw_row(1), gw_row(2, event_transfers=8)]
    chips = [{"chip_name": "wildcard", "event": 2}]
    assert compute_free_transfers(history, chips, upcoming_gw=3) == 2


def test_free_transfers_cap_at_five():
    history = [gw_row(1)] + [gw_row(gw, event_transfers=0) for gw in range(2, 10)]
    assert compute_free_transfers(history, [], upcoming_gw=10) == 5
