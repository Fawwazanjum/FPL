from fpl_model.data.purchase_price import compute_sell_price


def test_sell_price_no_profit_returns_current_price():
    assert compute_sell_price(purchase_tenths=55, now_cost_tenths=55) == 55


def test_sell_price_loss_passed_through_in_full():
    assert compute_sell_price(purchase_tenths=55, now_cost_tenths=50) == 50


def test_sell_price_profit_banks_half_rounded_down():
    # +0.5m profit (5 tenths) -> keep half rounded down = 2 tenths -> sell at purchase+2
    assert compute_sell_price(purchase_tenths=50, now_cost_tenths=55) == 52


def test_sell_price_profit_exact_half():
    # +0.4m profit (4 tenths) -> half = 2 tenths exactly
    assert compute_sell_price(purchase_tenths=50, now_cost_tenths=54) == 52


def test_sell_price_one_tenth_profit_rounds_down_to_zero_gain():
    # +0.1m profit (1 tenth) -> floor(1/2) = 0 -> no gain banked yet
    assert compute_sell_price(purchase_tenths=50, now_cost_tenths=51) == 50
