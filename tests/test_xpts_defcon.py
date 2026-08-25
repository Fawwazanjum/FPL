from fpl_model.analysis.xpts import _defcon_hit_rate
from fpl_model.storage import repository


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


def test_defender_below_threshold_never_hits(conn):
    rows = [_gw_row(1, gw, 90, defensive_contribution=5) for gw in range(1, 4)]
    repository.upsert_player_gw_history(conn, rows)
    assert _defcon_hit_rate(conn, 1, "DEF") == 0.0


def test_defender_meets_threshold_every_game(conn):
    rows = [_gw_row(1, gw, 90, defensive_contribution=10) for gw in range(1, 4)]
    repository.upsert_player_gw_history(conn, rows)
    assert _defcon_hit_rate(conn, 1, "DEF") == 1.0


def test_defender_mixed_hit_rate(conn):
    rows = [
        _gw_row(1, 1, 90, defensive_contribution=10),
        _gw_row(1, 2, 90, defensive_contribution=3),
        _gw_row(1, 3, 90, defensive_contribution=12),
        _gw_row(1, 4, 90, defensive_contribution=1),
    ]
    repository.upsert_player_gw_history(conn, rows)
    assert _defcon_hit_rate(conn, 1, "DEF") == 0.5


def test_midfielder_uses_higher_threshold_than_defender(conn):
    # 10 meets the DEF threshold but not the MID/FWD threshold (12)
    rows = [_gw_row(1, gw, 90, defensive_contribution=10) for gw in range(1, 3)]
    repository.upsert_player_gw_history(conn, rows)
    assert _defcon_hit_rate(conn, 1, "MID") == 0.0
    assert _defcon_hit_rate(conn, 1, "DEF") == 1.0


def test_goalkeeper_always_zero_defcon():
    from fpl_model.data.scoring_rules import DEFCON_THRESHOLD

    assert DEFCON_THRESHOLD["GKP"] is None


def test_unused_bench_minutes_excluded_from_rate(conn):
    rows = [
        _gw_row(1, 1, 90, defensive_contribution=10),
        _gw_row(1, 2, 0, defensive_contribution=0),  # unused sub, shouldn't count as a "miss"
    ]
    repository.upsert_player_gw_history(conn, rows)
    assert _defcon_hit_rate(conn, 1, "DEF") == 1.0
