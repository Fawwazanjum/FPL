from fpl_model.analysis.xpts import _detect_role_shift
from fpl_model.data.scoring_rules import ScoringRules
from fpl_model.storage import repository


def _row(player_id, gw, minutes, expected_goals, expected_assists, defensive_contribution):
    return {
        "player_id": player_id, "gameweek": gw, "minutes": minutes, "total_points": 2,
        "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 1,
        "bonus": 0, "bps": 10, "expected_goals": expected_goals, "expected_assists": expected_assists,
        "expected_goal_involvements": expected_goals + expected_assists, "expected_goals_conceded": 1.0,
        "clearances_blocks_interceptions": 0, "tackles": 0, "recoveries": 0,
        "defensive_contribution": defensive_contribution, "yellow_cards": 0, "red_cards": 0,
        "was_home": 1, "opponent_team": 2, "kickoff_time": "2026-08-23T13:00:00Z", "value": 50,
    }


def scoring():
    return ScoringRules(
        goals_scored={"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
        assists=3,
        clean_sheets={"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
        goals_conceded={"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
        defensive_contribution_points={"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
        long_play=2, short_play=1, yellow_cards=-1, red_cards=-3,
    )


def test_not_enough_games_returns_none(conn):
    repository.upsert_player_gw_history(conn, [_row(1, 1, 90, 0.5, 0.3, 3)])
    assert _detect_role_shift(conn, 1, "MID", scoring()) is None


def test_midfielder_pushed_deeper_is_flagged(conn):
    # Strong attacking early, then attacking output collapses while defensive actions rise
    rows = [_row(1, gw, 90, 0.6, 0.4, 2) for gw in range(1, 5)] + [_row(1, gw, 90, 0.05, 0.02, 8) for gw in range(5, 9)]
    repository.upsert_player_gw_history(conn, rows)
    result = _detect_role_shift(conn, 1, "MID", scoring())
    assert result is not None
    assert "deeper" in result


def test_defender_pushed_forward_is_flagged(conn):
    rows = [_row(1, gw, 90, 0.05, 0.02, 8) for gw in range(1, 5)] + [_row(1, gw, 90, 0.5, 0.4, 3) for gw in range(5, 9)]
    repository.upsert_player_gw_history(conn, rows)
    result = _detect_role_shift(conn, 1, "DEF", scoring())
    assert result is not None
    assert "advanced" in result


def test_stable_role_not_flagged(conn):
    rows = [_row(1, gw, 90, 0.3, 0.2, 4) for gw in range(1, 9)]
    repository.upsert_player_gw_history(conn, rows)
    assert _detect_role_shift(conn, 1, "MID", scoring()) is None
