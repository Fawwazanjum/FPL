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

# Season used for last-season/history_past blending in form.py — NOT the season
# currently being played (that's whatever bootstrap-static's live data reflects).
LAST_SEASON_LABEL = "2025/26"
