from __future__ import annotations

import logging

from fpl_model.data.cache import TtlCache
from fpl_model.util.http import build_session, get_json

log = logging.getLogger(__name__)

BASE_URL = "https://fantasy.premierleague.com/api"


class FplClient:
    def __init__(self, cache: TtlCache, ttl_hours: dict[str, float], force_refresh: bool = False):
        self.session = build_session()
        self.cache = cache
        self.ttl_hours = ttl_hours
        self.force_refresh = force_refresh

    def _cached_get(self, endpoint: str, ttl_key: str, params: dict | None = None) -> dict:
        cache_key = self.cache.make_key(endpoint, params)
        if not self.force_refresh:
            cached = self.cache.get(cache_key, self.ttl_hours.get(ttl_key, 6.0))
            if cached is not None:
                return cached
        payload = get_json(self.session, f"{BASE_URL}{endpoint}", params=params)
        self.cache.set(cache_key, payload)
        return payload

    def get_bootstrap_static(self) -> dict:
        return self._cached_get("/bootstrap-static/", "bootstrap_static")

    def get_fixtures(self, event: int | None = None) -> list[dict]:
        params = {"event": event} if event is not None else None
        return self._cached_get("/fixtures/", "fixtures", params)

    def get_element_summary(self, player_id: int) -> dict:
        return self._cached_get(f"/element-summary/{player_id}/", "element_summary")

    def get_entry(self, team_id: int) -> dict:
        return self._cached_get(f"/entry/{team_id}/", "entry")

    def get_entry_history(self, team_id: int) -> dict:
        return self._cached_get(f"/entry/{team_id}/history/", "entry")

    def get_entry_picks(self, team_id: int, event: int) -> dict:
        return self._cached_get(f"/entry/{team_id}/event/{event}/picks/", "entry")

    def get_entry_transfers(self, team_id: int) -> list[dict]:
        return self._cached_get(f"/entry/{team_id}/transfers/", "entry")


def current_or_next_event(bootstrap: dict) -> dict | None:
    events = bootstrap.get("events", [])
    for ev in events:
        if ev.get("is_current"):
            return ev
    for ev in events:
        if ev.get("is_next"):
            return ev
    return None


def last_finished_event_id(bootstrap: dict) -> int | None:
    finished = [ev for ev in bootstrap.get("events", []) if ev.get("finished")]
    if not finished:
        return None
    return max(ev["id"] for ev in finished)
