"""Static FPL rules that don't change at runtime (squad legality).

Scoring values (clean sheets, defensive contribution) are deliberately NOT
hardcoded here — they're pulled live from bootstrap-static's game_config.scoring
each run (see data/ingest.py) so the model self-adjusts if FPL changes them.
"""

from __future__ import annotations

POSITIONS = ("GKP", "DEF", "MID", "FWD")

POSITION_REQUIREMENTS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}

STARTING_XI_BOUNDS = {
    "GKP": (1, 1),
    "DEF": (3, 5),
    "MID": (2, 5),
    "FWD": (1, 3),
}

SQUAD_SIZE = 15
STARTING_XI_SIZE = 11
MAX_PER_CLUB = 3

ELEMENT_TYPE_ID_TO_POSITION = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

STATUS_AVAILABLE = "a"
STATUS_INJURED = "i"
STATUS_DOUBTFUL = "d"
STATUS_SUSPENDED = "s"
STATUS_UNAVAILABLE = "u"
STATUS_NOT_AVAILABLE = "n"

# Seasons used for the multi-season prior in form.py/xpts.py — NOT the season
# currently being played (that's whatever bootstrap-static's live data
# reflects). Most-recent-first; RECENT_SEASON_WEIGHTS is aligned positionally
# and renormalized over whichever of these a given player actually has
# history for (a young player with 1 season just uses that season at full
# weight, not a zero-padded average). Single-season-only was the pre-existing
# design; a "true talent" prior — especially for something as game-to-game-
# noisy as set-piece/penalty consistency or DEFCON — is meaningfully more
# stable pulling from 2-3 seasons than 1 (see memory: fpl-model-project).
RECENT_SEASON_LABELS = ("2025/26", "2024/25", "2023/24")
RECENT_SEASON_WEIGHTS = (0.6, 0.3, 0.1)
LAST_SEASON_LABEL = RECENT_SEASON_LABELS[0]

# DEFCON specifically must NOT use the full RECENT_SEASON_LABELS — it's a
# newer FPL scoring category than the other stats. Verified directly against
# the ingested data before shipping this: every 2023/24 player_history_past
# row with 1000+ minutes has EXACTLY 0 defensive_contribution (178/178) —
# statistically impossible for real data, i.e. the stat wasn't tracked/
# backfilled that season, not that nobody made a tackle all year. 2024/25
# shows real variation (13/206 near-zero, plausible for pure attackers), so
# DEFCON tracking starts there. Blending in 2023/24 for DEFCON specifically
# would silently drag every veteran's prior toward a fake zero.
DEFCON_TRACKED_SEASON_LABELS = ("2025/26", "2024/25")
