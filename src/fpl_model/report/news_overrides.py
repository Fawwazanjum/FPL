"""Loads the manual news-overrides overlay (see news_overrides.example.yaml
for the schema). This file is Claude-maintained — filled in from web-searched
team news before each report run — and is read here purely as data; acquiring
the news itself is explicitly out of scope for this codebase.

Absent file = empty overlay, not an error: this is an optional layer on top
of the FPL API's own status/chance_of_playing fields and the stat-based
role-shift detector, not a requirement for the pipeline to run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

VALID_STATUSES = {"out", "doubtful", "available"}
VALID_ROLE_DIRECTIONS = {"more_attacking", "more_defensive"}


@dataclass
class NewsOverride:
    player_id: int
    status: str | None = None
    chance_of_playing_override: int | None = None
    role_note: str | None = None
    role_direction: str | None = None
    set_piece_note: str | None = None
    note: str | None = None
    source: str | None = None


def load_news_overrides(path: Path) -> dict[int, NewsOverride]:
    path = Path(path)
    if not path.exists():
        return {}

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        log.warning("Could not parse news overrides at %s, proceeding without them: %s", path, exc)
        return {}

    players_raw = raw.get("players") or {}
    if not isinstance(players_raw, dict):
        log.warning("news overrides 'players' key is not a mapping, proceeding without them")
        return {}

    overrides: dict[int, NewsOverride] = {}
    for key, data in players_raw.items():
        try:
            player_id = int(key)
        except (TypeError, ValueError):
            log.warning("Skipping news override with non-integer player id: %r", key)
            continue
        if not isinstance(data, dict):
            log.warning("Skipping malformed news override for player %s (not a mapping)", player_id)
            continue

        status = data.get("status")
        if status is not None and status not in VALID_STATUSES:
            log.warning("Skipping invalid status %r for player %s (expected one of %s)", status, player_id, VALID_STATUSES)
            status = None

        role_direction = data.get("role_direction")
        if role_direction is not None and role_direction not in VALID_ROLE_DIRECTIONS:
            log.warning(
                "Skipping invalid role_direction %r for player %s (expected one of %s)",
                role_direction, player_id, VALID_ROLE_DIRECTIONS,
            )
            role_direction = None

        overrides[player_id] = NewsOverride(
            player_id=player_id,
            status=status,
            chance_of_playing_override=data.get("chance_of_playing_override"),
            role_note=data.get("role_note"),
            role_direction=role_direction,
            set_piece_note=data.get("set_piece_note"),
            note=data.get("note"),
            source=data.get("source"),
        )

    return overrides
