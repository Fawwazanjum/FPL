"""Live FPL scoring rules, pulled from bootstrap-static's game_config.scoring each
run rather than hardcoded, so the model self-adjusts if FPL changes point values.

Confirmed live structure (fetched 2026-08-25): game_config.scoring has
position-keyed dicts for goals_scored, clean_sheets, goals_conceded, and
defensive_contribution; assists/yellow_cards/red_cards/long_play/short_play are
flat (same for every position).

One exception: the DEFCON *threshold* (how many defensive actions are needed to
earn the point) is NOT exposed anywhere in the API. These are hardcoded from the
documented 2025/26 rule change, not derived — flagged clearly so a future season
rule change is easy to find and update.
"""

from __future__ import annotations

from dataclasses import dataclass

from fpl_model.config import AppConfig
from fpl_model.data.cache import TtlCache
from fpl_model.data.fpl_client import FplClient

# Not available from the API — documented FPL rule, not derived from live data.
DEFCON_THRESHOLD = {"GKP": None, "DEF": 10, "MID": 12, "FWD": 12}

_FALLBACK_GOALS_SCORED = {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}
_FALLBACK_CLEAN_SHEETS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
_FALLBACK_GOALS_CONCEDED = {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0}
_FALLBACK_DEFENSIVE_CONTRIBUTION = {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2}


@dataclass(frozen=True)
class ScoringRules:
    goals_scored: dict[str, int]
    assists: int
    clean_sheets: dict[str, int]
    goals_conceded: dict[str, int]
    defensive_contribution_points: dict[str, int]
    long_play: int
    short_play: int
    yellow_cards: int
    red_cards: int

    def attacking_points(self, position: str, expected_goals: float, expected_assists: float) -> float:
        return expected_goals * self.goals_scored.get(position, 0) + expected_assists * self.assists


def load_scoring_rules(config: AppConfig) -> ScoringRules:
    cache = TtlCache(config.cache_dir)
    client = FplClient(cache, config.cache_ttl_hours.model_dump(), force_refresh=False)
    bootstrap = client.get_bootstrap_static()
    scoring = bootstrap.get("game_config", {}).get("scoring", {})
    return ScoringRules(
        goals_scored=scoring.get("goals_scored", _FALLBACK_GOALS_SCORED),
        assists=scoring.get("assists", 3),
        clean_sheets=scoring.get("clean_sheets", _FALLBACK_CLEAN_SHEETS),
        goals_conceded=scoring.get("goals_conceded", _FALLBACK_GOALS_CONCEDED),
        defensive_contribution_points=scoring.get("defensive_contribution", _FALLBACK_DEFENSIVE_CONTRIBUTION),
        long_play=scoring.get("long_play", 2),
        short_play=scoring.get("short_play", 1),
        yellow_cards=scoring.get("yellow_cards", -1),
        red_cards=scoring.get("red_cards", -3),
    )
