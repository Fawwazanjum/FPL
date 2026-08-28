from fpl_model.analysis.rate_blend import blend_rate, multi_season_prior_rate, shrink_toward_expected
from fpl_model.config import FormWeights
from fpl_model.constants import RECENT_SEASON_LABELS, RECENT_SEASON_WEIGHTS


def weights(**overrides):
    return FormWeights(**overrides)


def test_zero_games_played_uses_last_season_rate_only():
    result = blend_rate(last_season_rate=5.0, season_rate=0.0, recent_rate_adjusted=0.0, games_played=0, weights=weights())
    assert result.weight_last == 1.0
    assert result.blended_rate == 5.0


def test_low_games_played_blends_last_and_season_only_no_recent_term():
    # n <= 6: recent term folds into season_rate (R == S at this point in a real season)
    result = blend_rate(last_season_rate=4.0, season_rate=6.0, recent_rate_adjusted=99.0, games_played=3, weights=weights())
    w_last = max(0.15, 1 - 3 / 8)
    expected = w_last * 4.0 + (1 - w_last) * 6.0
    assert abs(result.blended_rate - expected) < 1e-9


def test_high_games_played_uses_recent_component():
    result = blend_rate(last_season_rate=4.0, season_rate=5.0, recent_rate_adjusted=8.0, games_played=10, weights=weights())
    w_last = max(0.15, 1 - 10 / 8)  # floors at 0.15
    assert result.weight_last == 0.15
    w_remaining = 1 - 0.15
    w_recent = w_remaining * 0.65
    w_season = w_remaining * 0.35
    expected = 0.15 * 4.0 + w_season * 5.0 + w_recent * 8.0
    assert abs(result.blended_rate - expected) < 1e-9


def test_last_season_weight_never_drops_below_floor():
    result = blend_rate(last_season_rate=1.0, season_rate=1.0, recent_rate_adjusted=1.0, games_played=100, weights=weights())
    assert result.weight_last == 0.15


def test_shrink_toward_expected_no_minutes_returns_expected_rate():
    assert shrink_toward_expected(recent_rate=10.0, expected_rate=2.0, recent_minutes=0, shrinkage_minutes=400) == 2.0


def test_shrink_toward_expected_large_sample_stays_close_to_recent_rate():
    shrunk = shrink_toward_expected(recent_rate=10.0, expected_rate=2.0, recent_minutes=4000, shrinkage_minutes=400)
    assert shrunk > 8.5  # large minutes sample -> barely shrunk


def test_shrink_toward_expected_small_sample_pulls_toward_expected():
    shrunk = shrink_toward_expected(recent_rate=10.0, expected_rate=2.0, recent_minutes=40, shrinkage_minutes=400)
    assert shrunk < 3.0  # small sample -> mostly pulled to the underlying-data rate


def test_multi_season_prior_no_history_returns_none():
    assert multi_season_prior_rate({}, lambda row: row["minutes"]) is None


def test_multi_season_prior_single_season_uses_it_at_full_weight():
    seasons = {RECENT_SEASON_LABELS[0]: {"minutes": 3000, "value": 10.0}}
    result = multi_season_prior_rate(seasons, lambda row: row["value"])
    assert result == 10.0


def test_multi_season_prior_blends_multiple_seasons_by_recency_weight():
    seasons = {
        RECENT_SEASON_LABELS[0]: {"minutes": 3000, "value": 12.0},
        RECENT_SEASON_LABELS[1]: {"minutes": 3000, "value": 6.0},
    }
    result = multi_season_prior_rate(seasons, lambda row: row["value"])
    w0, w1 = RECENT_SEASON_WEIGHTS[0], RECENT_SEASON_WEIGHTS[1]
    expected = (12.0 * w0 + 6.0 * w1) / (w0 + w1)
    assert abs(result - expected) < 1e-9
    assert expected > 9.0  # closer to the more-recent season's value, not a flat average


def test_multi_season_prior_skips_a_zero_minute_season_and_renormalizes():
    # A season with 0 minutes (e.g. injured all year) shouldn't drag a real
    # rate toward 0 — it's excluded, not treated as a genuine 0 data point.
    seasons = {
        RECENT_SEASON_LABELS[0]: {"minutes": 3000, "value": 10.0},
        RECENT_SEASON_LABELS[1]: {"minutes": 0, "value": 0.0},
    }
    result = multi_season_prior_rate(seasons, lambda row: row["value"])
    assert result == 10.0
