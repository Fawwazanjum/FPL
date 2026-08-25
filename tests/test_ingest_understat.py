from fpl_model.data.ingest import IngestReport, _ingest_understat
from fpl_model.storage import repository


def _snap(player_id, web_name):
    return {
        "player_id": player_id, "gameweek": 1, "snapshot_date": "2026-08-25T00:00:00",
        "web_name": web_name, "team_id": 1, "element_type": 4, "now_cost": 50,
        "selected_by_percent": 5.0, "total_points": 3, "event_points": 3, "form": 3.0,
        "points_per_game": 3.0, "bps": 10, "expected_goals": 0.5, "expected_assists": 0.1,
        "expected_goal_involvements": 0.6, "expected_goals_conceded": 1.0, "ict_index": 5.0,
        "influence": 1.0, "creativity": 1.0, "threat": 1.0, "status": "a", "news": None,
        "chance_of_playing_this_round": None, "chance_of_playing_next_round": None,
        "transfers_in_event": 0, "transfers_out_event": 0, "minutes": 90,
    }


def test_skips_entirely_when_understat_unavailable(conn, monkeypatch):
    import fpl_model.data.understat_client as uc

    monkeypatch.setattr(uc, "is_available", lambda: False)
    report = IngestReport()

    _ingest_understat(conn, [1], report)

    assert any("unavailable" in flag.lower() for flag in report.data_quality_flags)
    assert repository.get_understat_mapping(conn, 1) is None


def test_flags_when_league_data_fetch_fails(conn, monkeypatch):
    import fpl_model.data.understat_client as uc

    monkeypatch.setattr(uc, "is_available", lambda: True)
    monkeypatch.setattr(uc, "get_league_players", lambda: None)
    report = IngestReport()

    _ingest_understat(conn, [1], report)

    assert any("league" in flag.lower() for flag in report.data_quality_flags)


def test_successful_mapping_and_history_stored(conn, monkeypatch):
    import fpl_model.data.understat_client as uc

    repository.upsert_player_snapshots(conn, [_snap(1, "Haaland")])

    monkeypatch.setattr(uc, "is_available", lambda: True)
    monkeypatch.setattr(uc, "get_league_players", lambda: [{"id": "999", "player_name": "Erling Haaland"}])
    monkeypatch.setattr(uc, "map_fpl_to_understat", lambda web_name, players: ("999", 1.0))
    monkeypatch.setattr(
        uc, "get_player_match_data",
        lambda understat_id: [{"date": "2026-08-23", "xG": "0.74", "xA": "0.02", "shots": "3", "key_passes": "1", "npxG": "0.74", "time": "90"}],
    )
    report = IngestReport()

    _ingest_understat(conn, [1], report)

    mapping = repository.get_understat_mapping(conn, 1)
    assert mapping["understat_id"] == "999"
    assert mapping["match_confidence"] == 1.0
    history = repository.get_understat_player_history(conn, "999")
    assert len(history) == 1
    assert history[0]["npxg"] == 0.74
    assert history[0]["minutes"] == 90


def test_failed_match_is_cached_and_not_retried(conn, monkeypatch):
    import fpl_model.data.understat_client as uc

    repository.upsert_player_snapshots(conn, [_snap(1, "Obscure Player")])
    repository.upsert_understat_player_map(conn, [{"fpl_player_id": 1, "understat_id": None, "match_confidence": 0.0}])

    monkeypatch.setattr(uc, "is_available", lambda: True)
    monkeypatch.setattr(uc, "get_league_players", lambda: [{"id": "1", "player_name": "Someone"}])

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("map_fpl_to_understat should not be called for an already-failed mapping")

    monkeypatch.setattr(uc, "map_fpl_to_understat", _fail_if_called)
    report = IngestReport()

    _ingest_understat(conn, [1], report)  # should not raise


def test_player_with_no_snapshot_is_skipped(conn, monkeypatch):
    import fpl_model.data.understat_client as uc

    monkeypatch.setattr(uc, "is_available", lambda: True)
    monkeypatch.setattr(uc, "get_league_players", lambda: [{"id": "1", "player_name": "Someone"}])
    report = IngestReport()

    _ingest_understat(conn, [999], report)  # no snapshot exists for player 999

    assert repository.get_understat_mapping(conn, 999) is None
