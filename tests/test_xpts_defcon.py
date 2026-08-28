from fpl_model.analysis.xpts import _defcon_hit_rate
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


# _defcon_hit_rate now blends a last-season prior in exactly the same way
# attacking_rate/bonus_rate already did (see memory: fpl-model-project) —
# these tests pass last_season_row=None throughout, i.e. a player with no
# last-season history, which still shrinks this-season's rate toward 0 early
# on (the same behavior attacking_rate/bonus_rate already had for a brand-new
# player). That shrinkage is expected, not a bug — see
# test_last_season_defcon_prior_blends_in below for the case WITH a prior.


def test_defender_below_threshold_never_hits(conn):
    rows = [_gw_row(1, gw, 90, defensive_contribution=5) for gw in range(1, 4)]
    repository.upsert_player_gw_history(conn, rows)
    assert _defcon_hit_rate(conn, 1, "DEF", None, WEIGHTS) == 0.0


def test_defender_meets_threshold_every_game(conn):
    # n=3: w_last = 1 - 3/8 = 0.625, w_season = 0.375; last_rate=0 (no prior)
    # -> blended = 0.375 * 1.0 = 0.375, not 1.0 — shrunk toward the missing
    # prior rather than trusting 3 games at face value.
    rows = [_gw_row(1, gw, 90, defensive_contribution=10) for gw in range(1, 4)]
    repository.upsert_player_gw_history(conn, rows)
    assert abs(_defcon_hit_rate(conn, 1, "DEF", None, WEIGHTS) - 0.375) < 1e-9


def test_defender_mixed_hit_rate(conn):
    # n=4: w_last = 1 - 4/8 = 0.5, w_season = 0.5; season_rate = 0.5 (2/4 hit)
    # -> blended = 0.5 * 0.5 = 0.25
    rows = [
        _gw_row(1, 1, 90, defensive_contribution=10),
        _gw_row(1, 2, 90, defensive_contribution=3),
        _gw_row(1, 3, 90, defensive_contribution=12),
        _gw_row(1, 4, 90, defensive_contribution=1),
    ]
    repository.upsert_player_gw_history(conn, rows)
    assert abs(_defcon_hit_rate(conn, 1, "DEF", None, WEIGHTS) - 0.25) < 1e-9


def test_midfielder_uses_higher_threshold_than_defender(conn):
    # 10 meets the DEF threshold but not the MID/FWD threshold (12).
    # n=2: w_last = 1 - 2/8 = 0.75, w_season = 0.25.
    rows = [_gw_row(1, gw, 90, defensive_contribution=10) for gw in range(1, 3)]
    repository.upsert_player_gw_history(conn, rows)
    assert _defcon_hit_rate(conn, 1, "MID", None, WEIGHTS) == 0.0
    assert abs(_defcon_hit_rate(conn, 1, "DEF", None, WEIGHTS) - 0.25) < 1e-9


def test_goalkeeper_always_zero_defcon():
    from fpl_model.data.scoring_rules import DEFCON_THRESHOLD

    assert DEFCON_THRESHOLD["GKP"] is None


def test_unused_bench_minutes_excluded_from_rate(conn):
    # Only gw1 counts as a played row (gw2 is 0 minutes) -> n=1.
    # w_last = 1 - 1/8 = 0.875, w_season = 0.125, season_rate = 1.0 (1/1 hit)
    # -> blended = 0.125 * 1.0 = 0.125
    rows = [
        _gw_row(1, 1, 90, defensive_contribution=10),
        _gw_row(1, 2, 0, defensive_contribution=0),  # unused sub, shouldn't count as a "miss"
    ]
    repository.upsert_player_gw_history(conn, rows)
    assert abs(_defcon_hit_rate(conn, 1, "DEF", None, WEIGHTS) - 0.125) < 1e-9


def test_last_season_defcon_prior_blends_in(conn):
    # A player with no games yet this season but a strong last-season record
    # should show up as a decent DEFCON bet, not zero — this is exactly the
    # Elliot-Anderson-style case the old (unblended) implementation couldn't
    # represent at all before a ball was kicked this season.
    #
    # A season AVERAGE sitting exactly at the threshold must NOT claim 1.0
    # (100%) — that would assert the player cleared the bar in literally
    # every match, which an average alone can't prove (caught via a real
    # Ampadu example: his 2025/26 average was exactly at the MID threshold,
    # and the old formula displayed that as a 100% "hit-rate"). Capped at
    # 0.75 for exactly this reason — see _defcon_hit_rate's docstring.
    last_season_row = {"minutes": 3420, "defensive_contribution": 380}  # 10.0 DC/90 vs a DEF threshold of 10
    assert abs(_defcon_hit_rate(conn, 1, "DEF", last_season_row, WEIGHTS) - 0.75) < 1e-9

    # A weaker last-season record (half the threshold on average) should
    # proxy to well below the strong case above, not 0.
    last_season_row_weak = {"minutes": 3420, "defensive_contribution": 190}  # 5.0 DC/90 vs threshold 10
    assert abs(_defcon_hit_rate(conn, 1, "DEF", last_season_row_weak, WEIGHTS) - 0.375) < 1e-9
