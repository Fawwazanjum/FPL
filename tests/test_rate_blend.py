from fpl_model.analysis.rate_blend import blend_rate, shrink_toward_expected
from fpl_model.config import FormWeights


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
