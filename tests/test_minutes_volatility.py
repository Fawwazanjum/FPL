from fpl_model.analysis.xpts import _minutes_stdev_this_season
from fpl_model.storage import repository


def _gw_row(player_id, gw, minutes):
    return {
        "player_id": player_id, "gameweek": gw, "minutes": minutes, "total_points": 2,
        "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 1,
        "bonus": 0, "bps": 10, "expected_goals": 0.0, "expected_assists": 0.0,
        "expected_goal_involvements": 0.0, "expected_goals_conceded": 1.0,
        "clearances_blocks_interceptions": 0, "tackles": 0, "recoveries": 0,
        "defensive_contribution": 0, "yellow_cards": 0, "red_cards": 0,
        "was_home": 1, "opponent_team": 2, "kickoff_time": "2026-08-23T13:00:00Z", "value": 50,
    }


def test_too_few_games_returns_zero_not_a_false_signal(conn):
    repository.upsert_player_gw_history(conn, [_gw_row(1, 1, 90)])
    stdev, n = _minutes_stdev_this_season(conn, 1)
    assert n == 1
    assert stdev == 0.0


def test_metronomic_starter_has_near_zero_stdev(conn):
    rows = [_gw_row(1, gw, 90) for gw in range(1, 6)]
    repository.upsert_player_gw_history(conn, rows)
    stdev, n = _minutes_stdev_this_season(conn, 1)
    assert n == 5
    assert stdev == 0.0


def test_consistent_impact_sub_has_low_stdev_despite_partial_minutes(conn):
    # Always exactly 20 minutes off the bench — low average share, but
    # perfectly predictable, which is a different thing from volatile.
    rows = [_gw_row(1, gw, 20) for gw in range(1, 6)]
    repository.upsert_player_gw_history(conn, rows)
    stdev, n = _minutes_stdev_this_season(conn, 1)
    assert stdev == 0.0


def test_boom_bust_rotation_player_has_high_stdev(conn):
    # Full 90 some weeks, an unused bench spot others — same rough AVERAGE
    # share a mid-tier rotation player might show, but genuinely unpredictable
    # week to week, which is exactly what this stat is meant to surface.
    rows = [_gw_row(1, gw, m) for gw, m in enumerate([90, 0, 90, 0, 90], start=1)]
    repository.upsert_player_gw_history(conn, rows)
    stdev, n = _minutes_stdev_this_season(conn, 1)
    assert n == 5
    assert stdev > 40.0  # near the theoretical max for an all-or-nothing 90/0 pattern
