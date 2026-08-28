import math

from fpl_model.analysis.xpts import _defcon_rate_per90, _poisson_p_at_least
from fpl_model.config import FormWeights
from fpl_model.storage import repository

WEIGHTS = FormWeights()


def _gw_row(player_id, gw, minutes, defensive_contribution):
    return {
        "player_id": player_id, "gameweek": gw, "minutes": minutes, "total_points": 2,
        "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 1,
        "bonus": 0, "bps": 10, "expected_goals": 0.0, "expected_assists": 0.0,
        "expected_goal_involvements": 0.0, "expected_goals_conceded": 1.0,
        "clearances_blocks_interceptions": 0, "tackles": 0, "recoveries": 0,
        "defensive_contribution": defensive_contribution, "yellow_cards": 0, "red_cards": 0,
        "was_home": 1, "opponent_team": 2, "kickoff_time": "2026-08-23T13:00:00Z", "value": 50,
    }


# --- _defcon_rate_per90: blends a RAW per-90 rate (last season / this season
# / recent), the same kind of quantity throughout — this is the number meant
# to be read and compared directly between two players, and the thing the
# earlier "hit-rate" version got wrong was mixing a rate-derived proxy for
# last season with an actual measured frequency for this season under one
# label. No threshold logic lives here at all now.


def test_no_history_gives_zero_rate(conn):
    rate, n = _defcon_rate_per90(conn, 1, None, WEIGHTS)
    assert rate == 0.0
    assert n == 0


def test_this_season_rate_reflects_actual_actions_per_90(conn):
    # 3 games at 90 mins, 9 DC each -> 9.0 DC/90 if taken at face value; with
    # no last-season prior (n=3, w_last = 1 - 3/8 = 0.625) it's shrunk toward
    # 0, not trusted outright — same purple-patch discipline as attacking rate.
    rows = [_gw_row(1, gw, 90, defensive_contribution=9) for gw in range(1, 4)]
    repository.upsert_player_gw_history(conn, rows)
    rate, n = _defcon_rate_per90(conn, 1, None, WEIGHTS)
    assert n == 3
    assert 0.0 < rate < 9.0  # shrunk below face value, not zero and not untouched


def test_last_season_prior_carries_at_zero_games_this_season(conn):
    # A player with no minutes yet this season but a known last-season rate
    # should show that rate directly (n=0 -> w_last=1.0), not zero — this is
    # the Elliot-Anderson-style case: judge a known defensive workhorse by
    # their track record before a ball's been kicked this season.
    last_season_row = {"minutes": 3420, "defensive_contribution": 380}  # 10.0 DC/90
    rate, n = _defcon_rate_per90(conn, 1, last_season_row, WEIGHTS)
    assert n == 0
    assert abs(rate - 10.0) < 1e-9


def test_two_players_compare_directly_on_the_raw_rate(conn):
    # This is the actual point of the metric: given two players' history, the
    # returned numbers should be directly, transparently comparable — no
    # threshold, no hidden "hit-rate" abstraction in between.
    strong = {"minutes": 3420, "defensive_contribution": 456}  # 12.0 DC/90
    weak = {"minutes": 3420, "defensive_contribution": 190}  # 5.0 DC/90
    strong_rate, _ = _defcon_rate_per90(conn, 1, strong, WEIGHTS)
    weak_rate, _ = _defcon_rate_per90(conn, 2, weak, WEIGHTS)
    assert strong_rate > weak_rate
    assert abs(strong_rate - 12.0) < 1e-9
    assert abs(weak_rate - 5.0) < 1e-9


# --- _poisson_p_at_least: converts a single per-90 rate into P(hit the
# per-match threshold) — the one place that conversion happens now, instead
# of being smeared across a rate-proxy AND a real measured frequency.


def test_poisson_zero_rate_never_clears_bar():
    assert _poisson_p_at_least(0.0, 10) == 0.0


def test_poisson_matches_known_closed_form_for_k_equals_1():
    # P(X >= 1) = 1 - P(X = 0) = 1 - e^-mu, exactly, for any Poisson(mu).
    mu = 2.0
    expected = 1 - math.exp(-mu)
    assert abs(_poisson_p_at_least(mu, 1) - expected) < 1e-9


def test_poisson_probability_rises_with_rate():
    threshold = 12
    low = _poisson_p_at_least(6.0, threshold)
    at_bar = _poisson_p_at_least(12.0, threshold)
    high = _poisson_p_at_least(20.0, threshold)
    assert low < at_bar < high
    # A rate sitting exactly AT the threshold should land well short of
    # certainty (Poisson(12) still has real mass below 12) — this is the
    # direct fix for the bug that let an at-threshold average claim 100%.
    assert 0.3 < at_bar < 0.7
    assert high > 0.9
