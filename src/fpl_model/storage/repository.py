from __future__ import annotations

import sqlite3
from typing import Any, Iterable


def _upsert_many(conn: sqlite3.Connection, table: str, columns: list[str], rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    placeholders = ", ".join(f":{c}" for c in columns)
    col_list = ", ".join(columns)
    sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"
    conn.executemany(sql, rows)
    conn.commit()


def upsert_team_snapshots(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    cols = [
        "team_id", "gameweek", "name", "short_name",
        "strength_overall_home", "strength_overall_away",
        "strength_attack_home", "strength_attack_away",
        "strength_defence_home", "strength_defence_away", "snapshot_date",
    ]
    _upsert_many(conn, "teams_snapshots", cols, rows)


def upsert_player_snapshots(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    cols = [
        "player_id", "gameweek", "snapshot_date", "web_name", "team_id", "element_type",
        "now_cost", "selected_by_percent", "total_points", "event_points", "form",
        "points_per_game", "bps", "expected_goals", "expected_assists",
        "expected_goal_involvements", "expected_goals_conceded", "ict_index",
        "influence", "creativity", "threat", "status", "news",
        "chance_of_playing_this_round", "chance_of_playing_next_round",
        "transfers_in_event", "transfers_out_event", "minutes",
    ]
    _upsert_many(conn, "player_snapshots", cols, rows)


def upsert_player_gw_history(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    cols = [
        "player_id", "gameweek", "minutes", "total_points", "goals_scored", "assists",
        "clean_sheets", "goals_conceded", "bonus", "bps", "expected_goals",
        "expected_assists", "expected_goal_involvements", "expected_goals_conceded",
        "clearances_blocks_interceptions", "tackles", "recoveries",
        "defensive_contribution", "yellow_cards", "red_cards",
        "was_home", "opponent_team", "kickoff_time", "value",
    ]
    _upsert_many(conn, "player_gw_history", cols, rows)


def upsert_player_history_past(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    cols = ["player_id", "season_name", "total_points", "minutes", "goals_scored", "assists", "clean_sheets", "bps"]
    _upsert_many(conn, "player_history_past", cols, rows)


def upsert_fixtures(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    cols = [
        "fixture_id", "gameweek", "kickoff_time", "team_h", "team_a",
        "team_h_difficulty", "team_a_difficulty", "team_h_score", "team_a_score", "finished",
    ]
    _upsert_many(conn, "fixtures", cols, rows)


def upsert_manager_history(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    cols = [
        "team_id", "gameweek", "points", "total_points", "rank", "overall_rank",
        "bank", "value", "event_transfers", "event_transfers_cost", "points_on_bench",
    ]
    _upsert_many(conn, "manager_history", cols, rows)


def upsert_manager_picks(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    cols = ["team_id", "gameweek", "player_id", "squad_position", "multiplier", "is_captain", "is_vice_captain"]
    _upsert_many(conn, "manager_picks", cols, rows)


def upsert_manager_transfers(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    cols = ["team_id", "event", "time", "element_in", "element_in_cost", "element_out", "element_out_cost"]
    _upsert_many(conn, "manager_transfers", cols, rows)


def upsert_chips_used(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    cols = ["team_id", "chip_name", "event"]
    _upsert_many(conn, "chips_used", cols, rows)


def upsert_understat_player_map(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    cols = ["fpl_player_id", "understat_id", "match_confidence"]
    _upsert_many(conn, "understat_player_map", cols, rows)


def upsert_understat_player_history(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    cols = ["understat_id", "date", "xg", "xa", "shots", "key_passes", "npxg", "minutes"]
    _upsert_many(conn, "understat_player_history", cols, rows)


def log_report(conn: sqlite3.Connection, generated_at: str, gameweek: int | None, file_path: str) -> None:
    conn.execute(
        "INSERT INTO reports_log (generated_at, gameweek, file_path) VALUES (?, ?, ?)",
        (generated_at, gameweek, file_path),
    )
    conn.commit()


def get_latest_manager_gameweek(conn: sqlite3.Connection, team_id: int) -> int | None:
    row = conn.execute(
        "SELECT MAX(gameweek) AS gw FROM manager_picks WHERE team_id = ?", (team_id,)
    ).fetchone()
    return row["gw"] if row and row["gw"] is not None else None


def get_squad_for_gw(conn: sqlite3.Connection, team_id: int, gameweek: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM manager_picks WHERE team_id = ? AND gameweek = ? ORDER BY squad_position",
        (team_id, gameweek),
    ).fetchall()


def get_manager_history(conn: sqlite3.Connection, team_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM manager_history WHERE team_id = ? ORDER BY gameweek", (team_id,)
    ).fetchall()


def get_manager_transfers(conn: sqlite3.Connection, team_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM manager_transfers WHERE team_id = ? ORDER BY event, time", (team_id,)
    ).fetchall()


def get_chips_used(conn: sqlite3.Connection, team_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM chips_used WHERE team_id = ?", (team_id,)).fetchall()


def get_player_snapshot(conn: sqlite3.Connection, player_id: int, gameweek: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM player_snapshots WHERE player_id = ? AND gameweek = ?", (player_id, gameweek)
    ).fetchone()


def get_latest_player_snapshots(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT ps.* FROM player_snapshots ps
        INNER JOIN (
            SELECT player_id, MAX(gameweek) AS max_gw FROM player_snapshots GROUP BY player_id
        ) latest ON ps.player_id = latest.player_id AND ps.gameweek = latest.max_gw
        """
    ).fetchall()


def get_latest_snapshot_for_player(conn: sqlite3.Connection, player_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM player_snapshots WHERE player_id = ? ORDER BY gameweek DESC LIMIT 1",
        (player_id,),
    ).fetchone()


def get_player_gw_history_first_appearance(conn: sqlite3.Connection, player_id: int) -> sqlite3.Row | None:
    """Earliest recorded element-summary row for this player (their team's first
    fixture with a history entry), regardless of minutes played — an unused bench
    player's price is just as real as a starter's, and we need it for purchase-price
    estimation even when they didn't feature."""
    return conn.execute(
        """
        SELECT * FROM player_gw_history
        WHERE player_id = ?
        ORDER BY gameweek ASC LIMIT 1
        """,
        (player_id,),
    ).fetchone()


def get_player_recent_gws(conn: sqlite3.Connection, player_id: int, n: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM player_gw_history WHERE player_id = ? ORDER BY gameweek DESC LIMIT ?",
        (player_id, n),
    ).fetchall()
