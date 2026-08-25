"""Reconstructs squad purchase/sell prices from public data.

All monetary values are handled in FPL's native units: tenths of a million
(e.g. now_cost=55 means £5.5m) — matching the API directly avoids float
rounding bugs in the profit-taking calculation below.
"""

from __future__ import annotations

import logging
import sqlite3

from fpl_model.storage import repository

log = logging.getLogger(__name__)


def compute_sell_price(purchase_tenths: int, now_cost_tenths: int) -> int:
    """FPL's real profit-taking rule: full loss passed through, 50% of profit
    banked, rounded down to the nearest £0.1m (i.e. nearest 1 tenth-unit pair)."""
    profit = now_cost_tenths - purchase_tenths
    if profit <= 0:
        return now_cost_tenths
    return purchase_tenths + profit // 2


def estimate_initial_purchase_prices(
    conn: sqlite3.Connection,
    player_ids: list[int],
    overrides_millions: dict[int, float],
    fallback_now_cost: dict[int, int],
) -> dict[int, int]:
    prices: dict[int, int] = {}
    for player_id in player_ids:
        if player_id in overrides_millions:
            prices[player_id] = round(overrides_millions[player_id] * 10)
            continue
        row = repository.get_player_gw_history_first_appearance(conn, player_id)
        if row is not None and row["value"] is not None:
            prices[player_id] = row["value"]
        else:
            log.warning(
                "No element-summary price history for player %s; falling back to current now_cost "
                "(sell-price estimate will be inexact until history accumulates)",
                player_id,
            )
            prices[player_id] = fallback_now_cost.get(player_id, 0)
    return prices


def apply_transfer_ledger(
    prices: dict[int, int], transfer_records: list[sqlite3.Row]
) -> dict[int, int]:
    updated = dict(prices)
    for record in transfer_records:
        player_in = record["element_in"]
        cost_in = record["element_in_cost"]
        if player_in in updated and cost_in is not None:
            updated[player_in] = cost_in
    return updated


def compute_squad_prices(
    conn: sqlite3.Connection,
    team_id: int,
    player_ids: list[int],
    overrides_millions: dict[int, float],
    fallback_now_cost: dict[int, int],
) -> tuple[dict[int, int], dict[int, int]]:
    """Returns (purchase_price_tenths, sell_price_tenths) keyed by player_id."""
    purchase = estimate_initial_purchase_prices(conn, player_ids, overrides_millions, fallback_now_cost)
    transfer_records = repository.get_manager_transfers(conn, team_id)
    purchase = apply_transfer_ledger(purchase, transfer_records)
    sell = {
        pid: compute_sell_price(purchase[pid], fallback_now_cost.get(pid, purchase[pid]))
        for pid in player_ids
    }
    return purchase, sell
