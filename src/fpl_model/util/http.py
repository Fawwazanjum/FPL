from __future__ import annotations

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class FplApiError(Exception):
    pass


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "fpl-model/0.1 (personal decision-support tool)"})
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_json(session: requests.Session, url: str, params: dict | None = None, timeout: float = 15.0) -> dict:
    try:
        resp = session.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FplApiError(f"GET {url} failed: {exc}") from exc
    try:
        return resp.json()
    except ValueError as exc:
        raise FplApiError(f"GET {url} returned non-JSON response: {exc}") from exc
