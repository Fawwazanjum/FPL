from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from fpl_model.analysis.squad_state import SquadState
from fpl_model.config import AppConfig
from fpl_model.constants import ELEMENT_TYPE_ID_TO_POSITION
from fpl_model.report.schema import PlayerSnapshotOut, Report, ReportMetadata, SquadAssessment
from fpl_model.storage import repository


def _tenths_to_millions(tenths: int) -> float:
    return round(tenths / 10, 1)


def build_bare_squad_report(conn: sqlite3.Connection, config: AppConfig, squad_state: SquadState) -> Report:
    players: list[PlayerSnapshotOut] = []
    for player_id in squad_state.current_squad:
        snap = repository.get_player_snapshot(conn, player_id, squad_state.gameweek) or repository.get_latest_snapshot_for_player(
            conn, player_id
        )
        if snap is None:
            continue
        players.append(
            PlayerSnapshotOut(
                player_id=player_id,
                web_name=snap["web_name"],
                position=ELEMENT_TYPE_ID_TO_POSITION.get(snap["element_type"], "UNK"),
                team_id=snap["team_id"],
                now_cost_millions=_tenths_to_millions(snap["now_cost"]),
                purchase_price_millions=_tenths_to_millions(squad_state.purchase_prices.get(player_id, snap["now_cost"])),
                sell_price_millions=_tenths_to_millions(squad_state.sell_prices.get(player_id, snap["now_cost"])),
                selected_by_percent=snap["selected_by_percent"],
                total_points=snap["total_points"],
                event_points=snap["event_points"],
                form=snap["form"],
                status=snap["status"] or "a",
                news=snap["news"] or None,
                in_starting_xi=player_id in squad_state.starting_xi,
                is_captain=player_id == squad_state.captain_id,
                is_vice_captain=player_id == squad_state.vice_captain_id,
            )
        )

    metadata = ReportMetadata(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        gameweek=squad_state.gameweek,
        upcoming_gameweek=squad_state.upcoming_gameweek,
        team_id=squad_state.team_id,
        data_quality_flags=squad_state.data_quality_flags,
    )
    squad = SquadAssessment(
        bank_millions=_tenths_to_millions(squad_state.bank_tenths),
        squad_value_millions=_tenths_to_millions(squad_state.squad_value_tenths),
        free_transfers_available=squad_state.free_transfers_available,
        chips_available=squad_state.chips_available,
        chips_used=squad_state.chips_used,
        players=players,
    )
    return Report(metadata=metadata, squad=squad)


def write(report: Report, config: AppConfig) -> Path:
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    gw = report.metadata.gameweek
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    path = config.reports_dir / f"report_gw{gw}_{timestamp}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    latest_path = config.reports_dir / "latest.json"
    latest_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path
