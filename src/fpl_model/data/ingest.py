from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field

from fpl_model.config import AppConfig
from fpl_model.data.cache import TtlCache
from fpl_model.data.fpl_client import FplClient, current_or_next_event, last_finished_event_id
from fpl_model.storage import repository
from fpl_model.util.http import FplApiError

log = logging.getLogger(__name__)


class CriticalDataSourceError(Exception):
    """Raised when a load-bearing data source (bootstrap-static, fixtures, or the
    user's own entry data) can't be fetched — the whole run should abort."""


@dataclass
class IngestReport:
    gameweek: int | None = None
    data_quality_flags: list[str] = field(default_factory=list)


def _today_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def run_full_refresh(
    config: AppConfig,
    conn: sqlite3.Connection,
    gw_override: int | None = None,
    force_refresh: bool = False,
    skip_understat: bool = False,
) -> IngestReport:
    report = IngestReport()
    cache = TtlCache(config.cache_dir)
    ttl_hours = config.cache_ttl_hours.model_dump()
    client = FplClient(cache, ttl_hours, force_refresh=force_refresh)

    try:
        bootstrap = client.get_bootstrap_static()
    except FplApiError as exc:
        raise CriticalDataSourceError(f"Failed to fetch bootstrap-static: {exc}") from exc

    try:
        fixtures = client.get_fixtures()
    except FplApiError as exc:
        raise CriticalDataSourceError(f"Failed to fetch fixtures: {exc}") from exc

    try:
        entry = client.get_entry(config.team_id)
    except FplApiError as exc:
        raise CriticalDataSourceError(
            f"Failed to fetch entry data for team_id={config.team_id} "
            f"(check the team_id in your config): {exc}"
        ) from exc

    try:
        entry_history = client.get_entry_history(config.team_id)
    except FplApiError as exc:
        raise CriticalDataSourceError(f"Failed to fetch entry history for team_id={config.team_id}: {exc}") from exc

    if gw_override is not None:
        gw = gw_override
    else:
        current_event = current_or_next_event(bootstrap)
        gw = last_finished_event_id(bootstrap)
        if gw is None and current_event is not None:
            gw = current_event["id"]
    report.gameweek = gw

    snapshot_date = _today_iso()
    _ingest_teams(conn, bootstrap, gw, snapshot_date)
    _ingest_players(conn, bootstrap, gw, snapshot_date)
    _ingest_fixtures(conn, fixtures)
    _ingest_manager_history(conn, config.team_id, entry_history)
    _ingest_chips(conn, config.team_id, entry_history)

    if gw is not None:
        try:
            picks = client.get_entry_picks(config.team_id, gw)
            _ingest_picks(conn, config.team_id, gw, picks)
        except FplApiError as exc:
            report.data_quality_flags.append(f"Could not fetch picks for GW{gw}: {exc}")
            log.warning("Could not fetch picks for GW%s: %s", gw, exc)

    try:
        transfers = client.get_entry_transfers(config.team_id)
        _ingest_transfers(conn, config.team_id, transfers)
    except FplApiError as exc:
        report.data_quality_flags.append(f"Could not fetch transfer ledger: {exc}")
        log.warning("Could not fetch transfer ledger: %s", exc)

    if gw is not None:
        squad_player_ids = [row["player_id"] for row in repository.get_squad_for_gw(conn, config.team_id, gw)]
        _ingest_element_summaries(conn, client, squad_player_ids, report)

    if not skip_understat:
        pass  # Understat integration lands in Phase 5 (deliberately not built yet)

    return report


def _ingest_teams(conn: sqlite3.Connection, bootstrap: dict, gw: int | None, snapshot_date: str) -> None:
    rows = [
        {
            "team_id": t["id"],
            "gameweek": gw if gw is not None else 0,
            "name": t["name"],
            "short_name": t["short_name"],
            "strength_overall_home": t.get("strength_overall_home"),
            "strength_overall_away": t.get("strength_overall_away"),
            "strength_attack_home": t.get("strength_attack_home"),
            "strength_attack_away": t.get("strength_attack_away"),
            "strength_defence_home": t.get("strength_defence_home"),
            "strength_defence_away": t.get("strength_defence_away"),
            "snapshot_date": snapshot_date,
        }
        for t in bootstrap.get("teams", [])
    ]
    repository.upsert_team_snapshots(conn, rows)


def _ingest_players(conn: sqlite3.Connection, bootstrap: dict, gw: int | None, snapshot_date: str) -> None:
    rows = [
        {
            "player_id": e["id"],
            "gameweek": gw if gw is not None else 0,
            "snapshot_date": snapshot_date,
            "web_name": e.get("web_name"),
            "team_id": e.get("team"),
            "element_type": e.get("element_type"),
            "now_cost": e.get("now_cost"),
            "selected_by_percent": _to_float(e.get("selected_by_percent")),
            "total_points": e.get("total_points"),
            "event_points": e.get("event_points"),
            "form": _to_float(e.get("form")),
            "points_per_game": _to_float(e.get("points_per_game")),
            "bps": e.get("bps"),
            "expected_goals": _to_float(e.get("expected_goals")),
            "expected_assists": _to_float(e.get("expected_assists")),
            "expected_goal_involvements": _to_float(e.get("expected_goal_involvements")),
            "expected_goals_conceded": _to_float(e.get("expected_goals_conceded")),
            "ict_index": _to_float(e.get("ict_index")),
            "influence": _to_float(e.get("influence")),
            "creativity": _to_float(e.get("creativity")),
            "threat": _to_float(e.get("threat")),
            "status": e.get("status"),
            "news": e.get("news"),
            "chance_of_playing_this_round": e.get("chance_of_playing_this_round"),
            "chance_of_playing_next_round": e.get("chance_of_playing_next_round"),
            "transfers_in_event": e.get("transfers_in_event"),
            "transfers_out_event": e.get("transfers_out_event"),
            "minutes": e.get("minutes"),
        }
        for e in bootstrap.get("elements", [])
    ]
    repository.upsert_player_snapshots(conn, rows)


def _ingest_fixtures(conn: sqlite3.Connection, fixtures: list[dict]) -> None:
    rows = [
        {
            "fixture_id": f["id"],
            "gameweek": f.get("event"),
            "kickoff_time": f.get("kickoff_time"),
            "team_h": f["team_h"],
            "team_a": f["team_a"],
            "team_h_difficulty": f.get("team_h_difficulty"),
            "team_a_difficulty": f.get("team_a_difficulty"),
            "team_h_score": f.get("team_h_score"),
            "team_a_score": f.get("team_a_score"),
            "finished": 1 if f.get("finished") else 0,
        }
        for f in fixtures
    ]
    repository.upsert_fixtures(conn, rows)


def _ingest_manager_history(conn: sqlite3.Connection, team_id: int, entry_history: dict) -> None:
    rows = [
        {
            "team_id": team_id,
            "gameweek": gw_row["event"],
            "points": gw_row.get("points"),
            "total_points": gw_row.get("total_points"),
            "rank": gw_row.get("rank"),
            "overall_rank": gw_row.get("overall_rank"),
            "bank": gw_row.get("bank"),
            "value": gw_row.get("value"),
            "event_transfers": gw_row.get("event_transfers"),
            "event_transfers_cost": gw_row.get("event_transfers_cost"),
            "points_on_bench": gw_row.get("points_on_bench"),
        }
        for gw_row in entry_history.get("current", [])
    ]
    repository.upsert_manager_history(conn, rows)


def _ingest_chips(conn: sqlite3.Connection, team_id: int, entry_history: dict) -> None:
    rows = [
        {"team_id": team_id, "chip_name": c["name"], "event": c["event"]}
        for c in entry_history.get("chips", [])
    ]
    repository.upsert_chips_used(conn, rows)


def _ingest_picks(conn: sqlite3.Connection, team_id: int, gw: int, picks: dict) -> None:
    rows = [
        {
            "team_id": team_id,
            "gameweek": gw,
            "player_id": p["element"],
            "squad_position": p.get("position"),
            "multiplier": p.get("multiplier"),
            "is_captain": 1 if p.get("is_captain") else 0,
            "is_vice_captain": 1 if p.get("is_vice_captain") else 0,
        }
        for p in picks.get("picks", [])
    ]
    repository.upsert_manager_picks(conn, rows)


def _ingest_transfers(conn: sqlite3.Connection, team_id: int, transfers: list[dict]) -> None:
    rows = [
        {
            "team_id": team_id,
            "event": t["event"],
            "time": t.get("time"),
            "element_in": t["element_in"],
            "element_in_cost": t.get("element_in_cost"),
            "element_out": t["element_out"],
            "element_out_cost": t.get("element_out_cost"),
        }
        for t in transfers
    ]
    repository.upsert_manager_transfers(conn, rows)


def _ingest_element_summaries(
    conn: sqlite3.Connection, client: FplClient, player_ids: list[int], report: IngestReport
) -> None:
    from fpl_model.constants import LAST_SEASON_LABEL

    for player_id in player_ids:
        try:
            summary = client.get_element_summary(player_id)
        except FplApiError as exc:
            msg = f"element-summary failed for player {player_id}: {exc}"
            report.data_quality_flags.append(msg)
            log.warning(msg)
            continue

        gw_rows = [
            {
                "player_id": player_id,
                "gameweek": h["round"],
                "minutes": h.get("minutes"),
                "total_points": h.get("total_points"),
                "goals_scored": h.get("goals_scored"),
                "assists": h.get("assists"),
                "clean_sheets": h.get("clean_sheets"),
                "goals_conceded": h.get("goals_conceded"),
                "bonus": h.get("bonus"),
                "bps": h.get("bps"),
                "expected_goals": _to_float(h.get("expected_goals")),
                "expected_assists": _to_float(h.get("expected_assists")),
                "expected_goal_involvements": _to_float(h.get("expected_goal_involvements")),
                "expected_goals_conceded": _to_float(h.get("expected_goals_conceded")),
                "clearances_blocks_interceptions": h.get("clearances_blocks_interceptions"),
                "tackles": h.get("tackles"),
                "recoveries": h.get("recoveries"),
                "defensive_contribution": h.get("defensive_contribution"),
                "yellow_cards": h.get("yellow_cards"),
                "red_cards": h.get("red_cards"),
                "was_home": 1 if h.get("was_home") else 0,
                "opponent_team": h.get("opponent_team"),
                "kickoff_time": h.get("kickoff_time"),
                "value": h.get("value"),
            }
            for h in summary.get("history", [])
        ]
        repository.upsert_player_gw_history(conn, gw_rows)

        past_rows = [
            {
                "player_id": player_id,
                "season_name": p["season_name"],
                "total_points": p.get("total_points"),
                "minutes": p.get("minutes"),
                "goals_scored": p.get("goals_scored"),
                "assists": p.get("assists"),
                "clean_sheets": p.get("clean_sheets"),
                "bps": p.get("bps"),
            }
            for p in summary.get("history_past", [])
            if p.get("season_name") == LAST_SEASON_LABEL
        ]
        repository.upsert_player_history_past(conn, past_rows)


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
