"""Shared three-tier rate blending: last-season / this-season-to-date / recent-form,
used by both form.py (blended actual-points rate) and xpts.py (blended
attacking/bonus underlying-rate). Keeping this in one place means the "purple
patch vs blip" weighting logic is defined once, not reimplemented per metric.
"""

from __future__ import annotations

from dataclasses import dataclass

from fpl_model.config import FormWeights


@dataclass
class BlendResult:
    last_season_rate: float
    season_rate: float
    recent_rate: float
    recent_rate_adjusted: float
    blended_rate: float
    games_played: int
    weight_last: float


def shrink_toward_expected(recent_rate: float, expected_rate: float, recent_minutes: float, shrinkage_minutes: float) -> float:
    """Empirical-Bayes shrinkage: a small recent-minutes sample gets pulled toward
    the underlying-data-implied rate (blip); a large sample keeps its own rate
    (purple patch)."""
    if recent_minutes <= 0:
        return expected_rate
    shrink = recent_minutes / (recent_minutes + shrinkage_minutes)
    return expected_rate + shrink * (recent_rate - expected_rate)


def blend_rate(
    last_season_rate: float,
    season_rate: float,
    recent_rate_adjusted: float,
    games_played: int,
    weights: FormWeights,
) -> BlendResult:
    n = games_played
    w_last = min(1.0, max(weights.last_season_floor_weight, 1 - n / weights.prior_decay_games))
    w_remaining = 1 - w_last

    if n <= 6:
        w_season = w_remaining
        w_recent = 0.0
        recent_component = season_rate
    else:
        w_recent = w_remaining * weights.recent_vs_season_split_recent
        w_season = w_remaining * (1 - weights.recent_vs_season_split_recent)
        recent_component = recent_rate_adjusted

    blended = w_last * last_season_rate + w_season * season_rate + w_recent * recent_component

    return BlendResult(
        last_season_rate=last_season_rate,
        season_rate=season_rate,
        recent_rate=recent_rate_adjusted,
        recent_rate_adjusted=recent_rate_adjusted,
        blended_rate=blended,
        games_played=n,
        weight_last=w_last,
    )
