from fpl_model.analysis.xpts import _suspension_risk_note
from fpl_model.storage import repository


def _gw_row(player_id, gw, minutes, yellow_cards=0):
    return {
        "player_id": player_id, "gameweek": gw, "minutes": minutes, "total_points": 2,
        "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 1,
        "bonus": 0, "bps": 10, "expected_goals": 0.0, "expected_assists": 0.0,
        "expected_goal_involvements": 0.0, "expected_goals_conceded": 1.0,
        "clearances_blocks_interceptions": 0, "tackles": 0, "recoveries": 0,
        "defensive_contribution": 0, "yellow_cards": yellow_cards, "red_cards": 0,
        "was_home": 1, "opponent_team": 2, "kickoff_time": "2026-08-23T13:00:00Z", "value": 50,
    }


def test_no_flag_when_nowhere_near_a_threshold(conn):
    rows = [_gw_row(1, gw, 90, yellow_cards=1) for gw in range(1, 3)]  # 2 total
    repository.upsert_player_gw_history(conn, rows)
    assert _suspension_risk_note(conn, 1) is None


def test_flags_one_card_away_from_first_threshold(conn):
    rows = [_gw_row(1, gw, 90, yellow_cards=1) for gw in range(1, 5)]  # 4 total, threshold is 5
    repository.upsert_player_gw_history(conn, rows)
    note = _suspension_risk_note(conn, 1)
    assert note is not None
    assert "4 yellow cards" in note
    assert "1-match" in note


def test_flags_one_card_away_from_second_threshold(conn):
    rows = [_gw_row(1, gw, 90, yellow_cards=1) for gw in range(1, 10)]  # 9 total, threshold is 10
    repository.upsert_player_gw_history(conn, rows)
    note = _suspension_risk_note(conn, 1)
    assert note is not None
    assert "9 yellow cards" in note
    assert "2-match" in note


def test_no_flag_just_past_a_threshold(conn):
    # Already served the ban (or hasn't yet, but isn't one card away either) —
    # 5 total isn't "one away from 5", it already crossed it.
    rows = [_gw_row(1, gw, 90, yellow_cards=1) for gw in range(1, 6)]  # 5 total
    repository.upsert_player_gw_history(conn, rows)
    assert _suspension_risk_note(conn, 1) is None
