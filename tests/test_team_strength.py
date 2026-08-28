from fpl_model.analysis.team_strength import compute_team_strength
from fpl_model.storage import repository


def _team_snapshot(team_id, name):
    return {
        "team_id": team_id, "gameweek": 1, "name": name, "short_name": name[:3].upper(),
        "strength_overall_home": 1000, "strength_overall_away": 1000,
        "strength_attack_home": 1000, "strength_attack_away": 1000,
        "strength_defence_home": 1000, "strength_defence_away": 1000,
        "snapshot_date": "2026-08-25T00:00:00",
    }


def _player_snapshot(player_id, team_id, minutes, expected_goals, expected_goals_conceded):
    return {
        "player_id": player_id, "gameweek": 1, "snapshot_date": "2026-08-25T00:00:00",
        "web_name": f"P{player_id}", "team_id": team_id, "element_type": 4,
        "now_cost": 50, "selected_by_percent": 5.0, "total_points": 3, "event_points": 3,
        "form": 3.0, "points_per_game": 3.0, "bps": 10, "expected_goals": expected_goals,
        "expected_assists": 0.0, "expected_goal_involvements": expected_goals,
        "expected_goals_conceded": expected_goals_conceded, "ict_index": 5.0,
        "influence": 1.0, "creativity": 1.0, "threat": 1.0, "status": "a", "news": None,
        "chance_of_playing_this_round": None, "chance_of_playing_next_round": None,
        "transfers_in_event": 0, "transfers_out_event": 0, "minutes": minutes,
    }


def _fixture(fixture_id, gw, team_h, team_a, h_score, a_score):
    return {
        "fixture_id": fixture_id, "gameweek": gw, "kickoff_time": "2026-08-23T13:00:00Z",
        "team_h": team_h, "team_a": team_a, "team_h_difficulty": 3, "team_a_difficulty": 3,
        "team_h_score": h_score, "team_a_score": a_score, "finished": 1,
    }


def test_attack_overperformance_positive_when_scoring_more_than_xg(conn):
    repository.upsert_team_snapshots(conn, [_team_snapshot(1, "TeamA"), _team_snapshot(2, "TeamB")])
    # TeamA's players generated 1.0 xG combined but the team actually scored 3
    repository.upsert_player_snapshots(conn, [_player_snapshot(101, 1, 90, 1.0, 1.0), _player_snapshot(201, 2, 90, 1.0, 1.0)])
    repository.upsert_fixtures(conn, [_fixture(1, 1, 1, 2, 3, 0)])

    result = compute_team_strength(conn)
    assert result[1].attack_overperformance == 3 - 1.0
    assert result[1].actual_goals_for == 3


def test_defense_overperformance_positive_when_conceding_fewer_than_xgc(conn):
    repository.upsert_team_snapshots(conn, [_team_snapshot(1, "TeamA"), _team_snapshot(2, "TeamB")])
    # TeamA's defense "should" have conceded 2.5 xGC but actually conceded 0
    repository.upsert_player_snapshots(conn, [_player_snapshot(101, 1, 90, 0.0, 2.5), _player_snapshot(201, 2, 90, 0.0, 1.0)])
    repository.upsert_fixtures(conn, [_fixture(1, 1, 1, 2, 3, 0)])

    result = compute_team_strength(conn)
    assert result[1].defense_overperformance == 2.5 - 0
    assert result[1].actual_goals_against == 0


def test_attack_index_ranks_higher_xg_team_above_lower(conn):
    repository.upsert_team_snapshots(conn, [_team_snapshot(1, "Strong"), _team_snapshot(2, "Weak")])
    repository.upsert_player_snapshots(conn, [_player_snapshot(101, 1, 90, 3.0, 1.0), _player_snapshot(201, 2, 90, 0.2, 1.0)])
    repository.upsert_fixtures(conn, [_fixture(1, 1, 1, 2, 1, 1)])

    result = compute_team_strength(conn)
    assert result[1].attack_index > result[2].attack_index


def test_single_game_index_is_heavily_shrunk_toward_neutral(conn):
    # One extreme early-season performance (huge xG gap after 1 game) should NOT
    # produce a near-full-magnitude z-score — this is the bug that let one wild
    # GW1 result badly distort clean-sheet-probability/xPts for many gameweeks.
    repository.upsert_team_snapshots(conn, [_team_snapshot(1, "Strong"), _team_snapshot(2, "Weak")])
    repository.upsert_player_snapshots(conn, [_player_snapshot(101, 1, 90, 5.0, 1.0), _player_snapshot(201, 2, 90, 0.1, 1.0)])
    repository.upsert_fixtures(conn, [_fixture(1, 1, 1, 2, 1, 1)])

    result = compute_team_strength(conn)
    assert result[1].games_played == 1
    raw_z = 1.0  # symmetric 2-team z-score is always +/-1
    expected_shrunk = raw_z * (1 / (1 + 8))
    assert abs(result[1].attack_index - expected_shrunk) < 1e-9
    assert abs(result[1].attack_index) < 0.2  # heavily damped, not near +/-1


def test_more_games_played_trusts_the_index_more(conn):
    repository.upsert_team_snapshots(conn, [_team_snapshot(1, "Strong"), _team_snapshot(2, "Weak")])
    repository.upsert_player_snapshots(conn, [_player_snapshot(101, 1, 90, 5.0, 1.0), _player_snapshot(201, 2, 90, 0.1, 1.0)])
    # 8 finished fixtures between the same two teams -> games_played=8 each
    repository.upsert_fixtures(conn, [_fixture(i, i, 1, 2, 1, 1) for i in range(1, 9)])

    result = compute_team_strength(conn)
    assert result[1].games_played == 8
    assert abs(result[1].attack_index - 0.5) < 1e-9  # shrink = 8/(8+8) = 0.5


def test_strength_of_schedule_discounts_attack_after_facing_weak_defense(conn):
    # Team A's attack faced only WeakDef (high xGC). StrongDef is a separate
    # team purely to give the league-wide defense z-score something to spread
    # over — it never plays A.
    repository.upsert_team_snapshots(
        conn, [_team_snapshot(1, "A"), _team_snapshot(2, "WeakDef"), _team_snapshot(3, "StrongDef")]
    )
    repository.upsert_player_snapshots(conn, [
        _player_snapshot(101, 1, 90, 1.5, 1.0),
        _player_snapshot(201, 2, 90, 1.0, 3.0),  # weak defense: high xGC
        _player_snapshot(301, 3, 90, 1.0, 0.2),  # strong defense: low xGC
    ])
    repository.upsert_fixtures(conn, [
        _fixture(1, 1, 1, 2, 2, 1),  # A vs WeakDef
        _fixture(2, 1, 2, 3, 1, 1),  # WeakDef vs StrongDef — doesn't involve A
    ])

    result = compute_team_strength(conn)
    assert result[1].attack_sos_adjustment < 0


def test_strength_of_schedule_credits_attack_after_facing_strong_defense(conn):
    # Same shape as above, but A's only fixture is against the STRONG defense
    # this time — the sign of the adjustment should flip.
    repository.upsert_team_snapshots(
        conn, [_team_snapshot(1, "A"), _team_snapshot(2, "WeakDef"), _team_snapshot(3, "StrongDef")]
    )
    repository.upsert_player_snapshots(conn, [
        _player_snapshot(101, 1, 90, 1.5, 1.0),
        _player_snapshot(201, 2, 90, 1.0, 3.0),
        _player_snapshot(301, 3, 90, 1.0, 0.2),
    ])
    repository.upsert_fixtures(conn, [
        _fixture(1, 1, 1, 3, 1, 1),  # A vs StrongDef
        _fixture(2, 1, 2, 3, 1, 1),  # WeakDef vs StrongDef — doesn't involve A
    ])

    result = compute_team_strength(conn)
    assert result[1].attack_sos_adjustment > 0


def test_strength_of_schedule_credits_defense_after_facing_strong_attack(conn):
    # Team A's defense faced only StrongAtt (high xG). WeakAtt is a separate
    # team purely to give the attack z-score spread to work with.
    repository.upsert_team_snapshots(
        conn, [_team_snapshot(1, "A"), _team_snapshot(2, "StrongAtt"), _team_snapshot(3, "WeakAtt")]
    )
    repository.upsert_player_snapshots(conn, [
        _player_snapshot(101, 1, 90, 1.0, 1.0),
        _player_snapshot(201, 2, 90, 3.0, 1.0),  # strong attack: high xG
        _player_snapshot(301, 3, 90, 0.2, 1.0),  # weak attack: low xG
    ])
    repository.upsert_fixtures(conn, [
        _fixture(1, 1, 1, 2, 1, 1),  # A vs StrongAtt
        _fixture(2, 1, 2, 3, 1, 1),  # StrongAtt vs WeakAtt — doesn't involve A
    ])

    result = compute_team_strength(conn)
    assert result[1].defense_sos_adjustment > 0
