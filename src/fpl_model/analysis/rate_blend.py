"""Shared three-tier rate blending: last-season / this-season-to-date / recent-form,
used by both form.py (blended actual-points rate) and xpts.py (blended
attacking/bonus underlying-rate). Keeping this in one place means the "purple
patch vs blip" weighting logic is defined once, not reimplemented per metric.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

from fpl_model.config import FormWeights
from fpl_model.constants import RECENT_SEASON_LABELS, RECENT_SEASON_WEIGHTS


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


def multi_season_prior_rate(
    history_past_seasons: dict[str, sqlite3.Row], rate_fn: Callable[[sqlite3.Row], float]
) -> float | None:
    """Combines up to 3 past seasons into a single weighted "prior" rate
    (RECENT_SEASON_WEIGHTS, most-recent-first), for use as the last_season_rate
    argument to blend_rate below — this is what turns the existing single-
    season prior into a multi-season one without changing blend_rate's own
    3-tier (prior/season/recent) shape or any of its callers' understanding
    of what "last_season_rate" means structurally.

    rate_fn extracts whatever per-90 (or per-season-total, caller's choice —
    e.g. minutes-share isn't per-90) quantity matters for that specific
    caller from one season's row; a season missing from history_past_seasons,
    or with 0 minutes, is simply skipped and the remaining seasons'
    weights are renormalized over each other — a player with only 1 season of
    data (new signing, young player) just uses that season at full weight,
    never zero-padded down by seasons that don't exist.

    Returns None (not 0.0) when there's no usable season at all, so callers
    can distinguish "no history — fall back to something else" from "history
    exists and the rate is genuinely zero.\""""
    weighted_sum = 0.0
    weight_total = 0.0
    for season, weight in zip(RECENT_SEASON_LABELS, RECENT_SEASON_WEIGHTS):
        row = history_past_seasons.get(season)
        if row is None or (row["minutes"] or 0) <= 0:
            continue
        weighted_sum += rate_fn(row) * weight
        weight_total += weight
    if weight_total <= 0:
        return None
    return weighted_sum / weight_total


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
