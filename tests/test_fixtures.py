from fpl_model.analysis.fixtures import detect_blank_gameweeks, detect_double_gameweeks, fixture_difficulty_for_horizon
from fpl_model.storage import repository


def _fixture(fixture_id, gw, team_h, team_a, h_diff=3, a_diff=3):
    return {
        "fixture_id": fixture_id, "gameweek": gw, "kickoff_time": "2026-09-01T13:00:00Z",
        "team_h": team_h, "team_a": team_a, "team_h_difficulty": h_diff, "team_a_difficulty": a_diff,
        "team_h_score": None, "team_a_score": None, "finished": 0,
    }


def test_detect_blank_gameweek_for_team_with_no_fixture(conn):
    # gw2: teams 1v2 play, team 3 has nothing scheduled
    repository.upsert_fixtures(conn, [_fixture(1, 2, 1, 2)])
    blanks = detect_blank_gameweeks(conn, [1, 2, 3], from_gw=2, horizon=1)
    assert blanks == {2: [3]}


def test_no_blank_when_all_teams_have_fixtures(conn):
    repository.upsert_fixtures(conn, [_fixture(1, 2, 1, 2), _fixture(2, 2, 3, 4)])
    blanks = detect_blank_gameweeks(conn, [1, 2, 3, 4], from_gw=2, horizon=1)
    assert blanks == {}


def test_detect_double_gameweek_for_team_with_two_fixtures(conn):
    repository.upsert_fixtures(conn, [_fixture(1, 2, 1, 2), _fixture(2, 2, 1, 3)])
    doubles = detect_double_gameweeks(conn, [1, 2, 3], from_gw=2, horizon=1)
    assert doubles == {2: [1]}


def test_fixture_difficulty_for_horizon_collects_across_gameweeks(conn):
    repository.upsert_fixtures(conn, [
        _fixture(1, 2, 1, 2, h_diff=4, a_diff=2),
        _fixture(2, 3, 3, 1, h_diff=2, a_diff=5),
    ])
    difficulties = fixture_difficulty_for_horizon(conn, team_id=1, from_gw=2, horizon=2)
    assert difficulties == [4, 5]  # team 1 was home in gw2 (diff 4) and away in gw3 (diff 5)
