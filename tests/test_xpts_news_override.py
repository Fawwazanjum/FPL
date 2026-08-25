from fpl_model.analysis.team_strength import TeamStrengthResult
from fpl_model.analysis.xpts import compute_player_xpts_gw
from fpl_model.config import FormWeights
from fpl_model.data.scoring_rules import ScoringRules
from fpl_model.report.news_overrides import NewsOverride
from fpl_model.storage import repository


def _snap(player_id, team_id):
    return {
        "player_id": player_id, "gameweek": 1, "snapshot_date": "2026-08-25T00:00:00",
        "web_name": f"P{player_id}", "team_id": team_id, "element_type": 3, "now_cost": 60,
        "selected_by_percent": 10.0, "total_points": 10, "event_points": 10, "form": 5.0,
        "points_per_game": 5.0, "bps": 20, "expected_goals": 0.6, "expected_assists": 0.3,
        "expected_goal_involvements": 0.9, "expected_goals_conceded": 1.0, "ict_index": 8.0,
        "influence": 5.0, "creativity": 5.0, "threat": 5.0, "status": "a", "news": None,
        "chance_of_playing_this_round": None, "chance_of_playing_next_round": None,
        "transfers_in_event": 0, "transfers_out_event": 0, "minutes": 90,
    }


def _gw_row(player_id, gw):
    return {
        "player_id": player_id, "gameweek": gw, "minutes": 90, "total_points": 5,
        "goals_scored": 0, "assists": 1, "clean_sheets": 0, "goals_conceded": 1, "bonus": 1, "bps": 20,
        "expected_goals": 0.6, "expected_assists": 0.3, "expected_goal_involvements": 0.9,
        "expected_goals_conceded": 1.0, "clearances_blocks_interceptions": 0, "tackles": 0, "recoveries": 0,
        "defensive_contribution": 0, "yellow_cards": 0, "red_cards": 0, "was_home": 1, "opponent_team": 2,
        "kickoff_time": "2026-08-23T13:00:00Z", "value": 60,
    }


def _fixture(team_h, team_a, gw=2):
    return {
        "fixture_id": 1, "gameweek": gw, "kickoff_time": "2026-09-01T13:00:00Z",
        "team_h": team_h, "team_a": team_a, "team_h_difficulty": 3, "team_a_difficulty": 3,
        "team_h_score": None, "team_a_score": None, "finished": 0,
    }


def _scoring():
    return ScoringRules(
        goals_scored={"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}, assists=3,
        clean_sheets={"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}, goals_conceded={"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
        defensive_contribution_points={"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
        long_play=2, short_play=1, yellow_cards=-1, red_cards=-3,
    )


def _neutral_team_strength(team_id):
    return TeamStrengthResult(
        team_id=team_id, games_played=3, actual_goals_for=4, actual_goals_against=4,
        attack_xg=4.0, defense_xgc=4.0, attack_overperformance=0.0, defense_overperformance=0.0,
        attack_index=0.0, defense_index=0.0,
    )


def _setup(conn):
    repository.upsert_player_snapshots(conn, [_snap(1, 1)])
    repository.upsert_player_gw_history(conn, [_gw_row(1, gw) for gw in range(1, 4)])
    repository.upsert_fixtures(conn, [_fixture(1, 2)])
    team_strength = {1: _neutral_team_strength(1), 2: _neutral_team_strength(2)}
    return _scoring(), FormWeights(), team_strength


def test_status_out_zeroes_total_xpts(conn):
    scoring, weights, team_strength = _setup(conn)
    baseline = compute_player_xpts_gw(conn, 1, 2, scoring, weights, team_strength)
    assert baseline.total > 0

    override = NewsOverride(player_id=1, status="out", note="Hamstring injury")
    result = compute_player_xpts_gw(conn, 1, 2, scoring, weights, team_strength, override)
    assert result.total == 0.0
    assert "ruled out" in result.reasoning.lower()


def test_chance_of_playing_override_scales_p_available(conn):
    scoring, weights, team_strength = _setup(conn)
    baseline = compute_player_xpts_gw(conn, 1, 2, scoring, weights, team_strength)  # chance=None -> p_available=1.0
    override = NewsOverride(player_id=1, chance_of_playing_override=25)
    result = compute_player_xpts_gw(conn, 1, 2, scoring, weights, team_strength, override)
    # baseline's p_full_involvement == minutes_factor (since p_available=1.0 there);
    # override sets p_available=0.25, so p_full should be exactly a quarter of baseline's.
    assert abs(result.p_full_involvement - 0.25 * baseline.p_full_involvement) < 1e-9
    assert result.total < baseline.total


def test_more_attacking_role_direction_increases_attacking_output(conn):
    scoring, weights, team_strength = _setup(conn)
    baseline = compute_player_xpts_gw(conn, 1, 2, scoring, weights, team_strength)
    override = NewsOverride(player_id=1, role_note="Pushed into an advanced role", role_direction="more_attacking")
    boosted = compute_player_xpts_gw(conn, 1, 2, scoring, weights, team_strength, override)
    assert boosted.attacking_pts > baseline.attacking_pts
    assert "NEWS: Pushed into an advanced role" in boosted.reasoning


def test_more_defensive_role_direction_decreases_attacking_output(conn):
    scoring, weights, team_strength = _setup(conn)
    baseline = compute_player_xpts_gw(conn, 1, 2, scoring, weights, team_strength)
    override = NewsOverride(player_id=1, role_direction="more_defensive")
    reduced = compute_player_xpts_gw(conn, 1, 2, scoring, weights, team_strength, override)
    assert reduced.attacking_pts < baseline.attacking_pts


def test_doubtful_without_explicit_chance_uses_default(conn):
    scoring, weights, team_strength = _setup(conn)
    override = NewsOverride(player_id=1, status="doubtful", note="Managing a knock")
    result = compute_player_xpts_gw(conn, 1, 2, scoring, weights, team_strength, override)
    baseline = compute_player_xpts_gw(conn, 1, 2, scoring, weights, team_strength)
    assert 0 < result.total < baseline.total
    assert "doubtful" in result.reasoning.lower()
