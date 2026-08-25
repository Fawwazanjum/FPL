"""Best-effort Understat integration. npxG (non-penalty xG) is a cleaner
attacking-quality signal than FPL's own expected_goals field, which includes
penalties and so is inflated by penalty-taker volume/luck rather than pure
open-play chance quality.

This is an optional enhancement layer — the system must fully work without
it (understat.com can block/rate-limit scrapers, or the site's HTML can
change and break the underlying library). Every entry point here is wrapped
in try/except and NEVER raises out of this module; callers get None on any
failure and the rest of the pipeline just proceeds without this data.
"""

from __future__ import annotations

import difflib
import logging
import re
import time
import unicodedata

log = logging.getLogger(__name__)

_capability_checked = False
_capability_available = False

NAME_MATCH_MIN_RATIO = 0.6


def _current_understat_season() -> int:
    now = time.localtime()
    # EPL seasons start ~August; before that, still the previous season's ID.
    return now.tm_year if now.tm_mon >= 7 else now.tm_year - 1


def is_available() -> bool:
    """Smoke-tests the Understat client once per process and caches the
    result — avoids repeatedly retrying a dead/blocked scraper every call."""
    global _capability_checked, _capability_available
    if _capability_checked:
        return _capability_available
    _capability_checked = True
    try:
        import understatapi

        client = understatapi.UnderstatClient()
        data = client.league(league="EPL").get_player_data(season=str(_current_understat_season()))
        _capability_available = bool(data)
    except Exception as exc:  # understatapi can raise almost anything (network, parsing, site changes)
        log.warning("Understat unavailable, continuing without it: %s", exc)
        _capability_available = False
    return _capability_available


def get_league_players(season: int | None = None) -> list[dict] | None:
    if not is_available():
        return None
    try:
        import understatapi

        client = understatapi.UnderstatClient()
        szn = season if season is not None else _current_understat_season()
        return client.league(league="EPL").get_player_data(season=str(szn))
    except Exception as exc:
        log.warning("Understat get_league_players failed: %s", exc)
        return None


def get_player_match_data(understat_player_id: str) -> list[dict] | None:
    if not is_available():
        return None
    try:
        import understatapi

        client = understatapi.UnderstatClient()
        return client.player(player=understat_player_id).get_match_data()
    except Exception as exc:
        log.warning("Understat get_player_match_data failed for %s: %s", understat_player_id, exc)
        return None


def _normalize(name: str) -> str:
    stripped = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    return re.sub(r"[^a-z ]", "", stripped.lower()).strip()


def map_fpl_to_understat(fpl_web_name: str, understat_players: list[dict]) -> tuple[str, float] | None:
    """Fuzzy-matches an FPL web_name (often an abbreviated surname, e.g.
    'B.Fernandes') against Understat's full player_name ('Bruno Fernandes').
    Tries an exact last-token substring match first (handles abbreviations
    cleanly); falls back to a fuzzy ratio, requiring NAME_MATCH_MIN_RATIO to
    avoid a confident-looking wrong match. Returns (understat_id, confidence)
    or None — low-confidence cases are skipped, not guessed, matching the
    plan's design (log and move on, never silently misattribute stats)."""
    fpl_tokens = re.split(r"[.\s]+", fpl_web_name.strip())
    fpl_surname = _normalize(fpl_tokens[-1]) if fpl_tokens else ""
    if not fpl_surname:
        return None

    substring_matches = [p for p in understat_players if fpl_surname in _normalize(p["player_name"])]
    if len(substring_matches) == 1:
        return substring_matches[0]["id"], 1.0

    normalized_fpl = _normalize(fpl_web_name)
    best_id, best_ratio = None, 0.0
    for p in understat_players:
        ratio = difflib.SequenceMatcher(None, normalized_fpl, _normalize(p["player_name"])).ratio()
        if ratio > best_ratio:
            best_id, best_ratio = p["id"], ratio

    if best_id is not None and best_ratio >= NAME_MATCH_MIN_RATIO:
        return best_id, best_ratio

    log.info("No confident Understat match for '%s' (best ratio %.2f)", fpl_web_name, best_ratio)
    return None
