from fpl_model.analysis.xpts import _minutes_reliability
from fpl_model.config import FormWeights
from fpl_model.constants import RECENT_SEASON_LABELS
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


def _history_past_seasons(*minutes_by_season):
    # history_past_seasons is now a dict keyed by season label, most-recent-
    # first per RECENT_SEASON_LABELS, matching multi_season_prior_rate's
    # expectations. Pass minutes for however many trailing seasons matter to
    # a given test (e.g. _history_past_seasons(3420) = just last season).
    return {
        RECENT_SEASON_LABELS[i]: {"minutes": m, "total_points": 100, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "bps": 0}
        for i, m in enumerate(minutes_by_season)
    }


def test_early_substitution_pulls_reliability_down(conn):
    # Started but subbed off after 20 minutes — this is the Mac Allister scenario
    repository.upsert_player_gw_history(conn, [_gw_row(1, 1, 20)])
    reliability, n = _minutes_reliability(conn, 1, {}, FormWeights())
    assert n == 1
    assert reliability < 0.5


def test_full_nailed_player_high_reliability(conn):
    repository.upsert_player_gw_history(conn, [_gw_row(1, gw, 90) for gw in range(1, 5)])
    reliability, n = _minutes_reliability(conn, 1, {}, FormWeights())
    assert reliability > 0.9


def test_no_last_season_data_falls_back_to_season_share_not_zero(conn):
    # A new signing with no last-season row but who's started every game so far
    # shouldn't be punished by a phantom "0 minutes last season" prior.
    repository.upsert_player_gw_history(conn, [_gw_row(1, 1, 90)])
    reliability, n = _minutes_reliability(conn, 1, {}, FormWeights())
    assert reliability > 0.9


def test_strong_last_season_minutes_carries_weight_at_zero_games_this_season(conn):
    reliability, n = _minutes_reliability(conn, 1, _history_past_seasons(38 * 90), FormWeights())
    assert n == 0
    assert reliability > 0.9


def test_multi_season_prior_softens_a_single_bad_rotation_year(conn):
    # Two strong nailed-on seasons and one rotation-squad year (the Mosquera
    # scenario) should read closer to "generally nailed" than a single-season
    # model would — that single bad year no longer solely anchors the prior.
    seasons = _history_past_seasons(38 * 90, 10 * 90, 38 * 90)  # last season down, two before it strong
    reliability, n = _minutes_reliability(conn, 1, seasons, FormWeights())
    assert n == 0
    # Single-season-only would have anchored on 10/38 ≈ 0.26; blending in the
    # two strong seasons pulls it up meaningfully above that.
    assert reliability > 0.5


def test_declining_trend_shows_up_in_recent_vs_season(conn):
    # Played full minutes early, then dropped out of the team recently —
    # exactly the "lost the pecking order" scenario the user described.
    rows = [_gw_row(1, gw, 90) for gw in range(1, 5)] + [_gw_row(1, gw, 0) for gw in range(5, 9)]
    repository.upsert_player_gw_history(conn, rows)
    reliability, n = _minutes_reliability(conn, 1, {}, FormWeights())
    assert n == 8
    assert reliability < 0.7  # recent run of zeros pulls it down from the early full-minutes stretch
