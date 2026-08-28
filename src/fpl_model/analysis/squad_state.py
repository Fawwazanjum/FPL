from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from fpl_model.config import AppConfig
from fpl_model.data import purchase_price
from fpl_model.storage import repository

ALL_CHIP_NAMES = ("wildcard", "freehit", "bboost", "3xc")
NON_CONSUMING_CHIPS = ("wildcard", "freehit")
MAX_FREE_TRANSFERS = 5


@dataclass
class SquadState:
    team_id: int
    gameweek: int
    upcoming_gameweek: int
    current_squad: list[int]
    starting_xi: list[int]
    bench: list[int]
    captain_id: int | None
    vice_captain_id: int | None
    bank_tenths: int
    squad_value_tenths: int
    free_transfers_available: int
    chips_available: list[str]
    chips_used: list[dict]
    purchase_prices: dict[int, int]
    sell_prices: dict[int, int]
    data_quality_flags: list[str] = field(default_factory=list)


def compute_free_transfers(
    manager_history_rows: list[sqlite3.Row], chips_used_rows: list[sqlite3.Row], upcoming_gw: int
) -> int:
    chip_by_gw = {row["event"]: row["chip_name"] for row in chips_used_rows}
    ft = 1  # baseline: 1 free transfer entering GW2
    for row in manager_history_rows:
        gw = row["gameweek"]
        if gw < 2 or gw >= upcoming_gw:
            continue
        transfers_made = row["event_transfers"] or 0
        chip = chip_by_gw.get(gw)
        if chip not in NON_CONSUMING_CHIPS:
            ft = max(ft - transfers_made, 0)
        ft = min(ft + 1, MAX_FREE_TRANSFERS)
    return ft


def compute_squad_state(conn: sqlite3.Connection, config: AppConfig) -> SquadState:
    team_id = config.team_id
    flags: list[str] = []

    history_rows = repository.get_manager_history(conn, team_id)
    if not history_rows:
        raise ValueError(
            f"No manager_history found for team_id={team_id}. "
            "Ingestion must run successfully before squad state can be computed."
        )
    last_row = history_rows[-1]
    gw = last_row["gameweek"]
    upcoming_gw = gw + 1

    picks = repository.get_squad_for_gw(conn, team_id, gw)
    if not picks:
        flags.append(f"No picks found for GW{gw}; squad composition unavailable.")
        current_squad, starting_xi, bench = [], [], []
        captain_id = vice_captain_id = None
    else:
        current_squad = [p["player_id"] for p in picks]
        starting_xi = [p["player_id"] for p in picks if (p["multiplier"] or 0) > 0]
        bench = [p["player_id"] for p in picks if not (p["multiplier"] or 0) > 0]
        captain_id = next((p["player_id"] for p in picks if p["is_captain"]), None)
        vice_captain_id = next((p["player_id"] for p in picks if p["is_vice_captain"]), None)

        # Bridge for a real transfer the API hasn't surfaced yet (see
        # PendingTransfer's docstring in config.py) — swap the player in
        # place in whichever list(s) held the outgoing player, so squad
        # size/formation/captaincy slots stay exactly as they were.
        for pt in config.pending_transfers:
            if pt.player_out not in current_squad:
                flags.append(
                    f"pending_transfers: player {pt.player_out} not found in the current squad — "
                    "already applied, or the API has caught up; safe to remove from config."
                )
                continue
            current_squad = [pt.player_in if pid == pt.player_out else pid for pid in current_squad]
            starting_xi = [pt.player_in if pid == pt.player_out else pid for pid in starting_xi]
            bench = [pt.player_in if pid == pt.player_out else pid for pid in bench]
            if captain_id == pt.player_out:
                captain_id = pt.player_in
            if vice_captain_id == pt.player_out:
                vice_captain_id = pt.player_in

    chips_used_rows = repository.get_chips_used(conn, team_id)
    chips_used = [{"name": r["chip_name"], "event": r["event"]} for r in chips_used_rows]
    used_names = {r["chip_name"] for r in chips_used_rows}
    chips_available = [c for c in ALL_CHIP_NAMES if c not in used_names]

    free_transfers_available = compute_free_transfers(history_rows, chips_used_rows, upcoming_gw)

    bank_tenths = last_row["bank"] or 0
    squad_value_tenths = last_row["value"] or 0

    latest_snapshots = repository.get_latest_player_snapshots(conn)
    fallback_now_cost = {row["player_id"]: row["now_cost"] for row in latest_snapshots}

    purchase_prices, sell_prices = purchase_price.compute_squad_prices(
        conn, team_id, current_squad, config.purchase_price_overrides, fallback_now_cost
    )

    return SquadState(
        team_id=team_id,
        gameweek=gw,
        upcoming_gameweek=upcoming_gw,
        current_squad=current_squad,
        starting_xi=starting_xi,
        bench=bench,
        captain_id=captain_id,
        vice_captain_id=vice_captain_id,
        bank_tenths=bank_tenths,
        squad_value_tenths=squad_value_tenths,
        free_transfers_available=free_transfers_available,
        chips_available=chips_available,
        chips_used=chips_used,
        purchase_prices=purchase_prices,
        sell_prices=sell_prices,
        data_quality_flags=flags,
    )
