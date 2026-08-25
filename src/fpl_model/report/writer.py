from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from fpl_model.analysis.form import FormResult
from fpl_model.analysis.squad_state import SquadState
from fpl_model.analysis.team_strength import TeamStrengthResult
from fpl_model.analysis.value import ValueResult
from fpl_model.analysis.xpts import XptsBreakdown
from fpl_model.config import AppConfig
from fpl_model.constants import ELEMENT_TYPE_ID_TO_POSITION
from fpl_model.optimizer.lineup_optimizer import LineupPlan
from fpl_model.optimizer.transfer_optimizer import TransferPlan, TransferRecommendation
from fpl_model.report.schema import (
    AnalysisSection,
    LineupOut,
    LineupPlayerOut,
    PlayerFormOut,
    PlayerSnapshotOut,
    PlayerXptsOut,
    Report,
    ReportMetadata,
    SquadAssessment,
    TeamStrengthOut,
    TransferMoveOut,
    TransferOptionOut,
    TransferRecommendationOut,
    ValuePickOut,
)
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


def build_analysis_section(
    conn: sqlite3.Connection,
    form_results: dict[int, FormResult],
    xpts_results: dict[int, XptsBreakdown],
    xpts_horizon: dict[int, float],
    team_strength: dict[int, TeamStrengthResult],
    value_results: dict[int, ValueResult],
    differential_ownership_threshold: float,
) -> AnalysisSection:
    from fpl_model.analysis.value import top_differentials, top_template_picks
    from fpl_model.constants import POSITIONS

    web_names: dict[int, str] = {}
    for pid in set(form_results) | set(xpts_results) | set(value_results):
        snap = repository.get_latest_snapshot_for_player(conn, pid)
        web_names[pid] = snap["web_name"] if snap else str(pid)

    form_out = {
        pid: PlayerFormOut(
            player_id=pid,
            web_name=web_names.get(pid, str(pid)),
            position=fr.position,
            form_score=round(fr.form_score, 3),
            games_played=fr.games_played,
            last_season_rate=round(fr.last_season_rate, 3),
            season_rate=round(fr.season_rate, 3),
            recent_rate_adjusted=round(fr.recent_rate_adjusted, 3),
            used_position_fallback=fr.used_position_fallback,
        )
        for pid, fr in form_results.items()
    }

    xpts_out = {
        pid: PlayerXptsOut(
            player_id=pid,
            web_name=web_names.get(pid, str(pid)),
            position=form_results[pid].position if pid in form_results else "MID",
            xpts_next_gw=round(xr.total, 3),
            xpts_horizon=round(xpts_horizon.get(pid, xr.total), 3),
            opponent_team_id=xr.opponent_team_id,
            is_home=xr.is_home,
            p_full_involvement=round(xr.p_full_involvement, 3),
            reasoning=xr.reasoning,
        )
        for pid, xr in xpts_results.items()
    }

    team_names = {row["team_id"]: row["name"] for row in repository.get_latest_team_snapshots(conn)}
    team_strength_out = [
        TeamStrengthOut(
            team_id=ts.team_id,
            team_name=team_names.get(ts.team_id, str(ts.team_id)),
            games_played=ts.games_played,
            actual_goals_for=ts.actual_goals_for,
            actual_goals_against=ts.actual_goals_against,
            attack_xg=round(ts.attack_xg, 2),
            defense_xgc=round(ts.defense_xgc, 2),
            attack_overperformance=round(ts.attack_overperformance, 2),
            defense_overperformance=round(ts.defense_overperformance, 2),
            attack_index=round(ts.attack_index, 2),
            defense_index=round(ts.defense_index, 2),
        )
        for ts in team_strength.values()
    ]

    def _to_pick(v: ValueResult, score: float) -> ValuePickOut:
        return ValuePickOut(
            player_id=v.player_id,
            web_name=v.web_name,
            position=v.position,
            now_cost_millions=v.now_cost_millions,
            selected_by_percent=v.selected_by_percent,
            xpts_horizon=v.xpts_horizon,
            score=score,
        )

    top_diff = {
        pos: [_to_pick(v, v.differential_score) for v in top_differentials(value_results, pos, differential_ownership_threshold)]
        for pos in POSITIONS
    }
    top_template = {
        pos: [_to_pick(v, v.template_score) for v in top_template_picks(value_results, pos)] for pos in POSITIONS
    }

    return AnalysisSection(
        form_by_player=form_out,
        xpts_by_player=xpts_out,
        team_strength=team_strength_out,
        top_differentials=top_diff,
        top_template_picks=top_template,
    )


def _player_move(conn: sqlite3.Connection, player_id: int) -> TransferMoveOut:
    snap = repository.get_latest_snapshot_for_player(conn, player_id)
    return TransferMoveOut(
        player_id=player_id,
        web_name=snap["web_name"] if snap else str(player_id),
        position=ELEMENT_TYPE_ID_TO_POSITION.get(snap["element_type"], "UNK") if snap else "UNK",
        price_millions=_tenths_to_millions(snap["now_cost"]) if snap else 0.0,
    )


def _build_transfer_option_out(conn: sqlite3.Connection, plan: TransferPlan) -> TransferOptionOut:
    return TransferOptionOut(
        transfers_in=[_player_move(conn, p) for p in plan.transfers_in],
        transfers_out=[_player_move(conn, p) for p in plan.transfers_out],
        transfers_made=plan.transfers_made,
        hits_taken=plan.hits_taken,
        hit_cost_applied=plan.hit_cost_applied,
        gross_xpts=round(plan.gross_xpts, 2),
        net_xpts=round(plan.net_xpts, 2),
        budget_remaining_millions=_tenths_to_millions(plan.budget_remaining_tenths),
        feasible=plan.feasible,
    )


def build_transfer_recommendation_out(conn: sqlite3.Connection, rec: TransferRecommendation) -> TransferRecommendationOut:
    return TransferRecommendationOut(
        recommended=rec.recommended,
        margin=round(rec.margin, 2),
        reasoning=rec.reasoning,
        banked_option=_build_transfer_option_out(conn, rec.banked_option),
        hit_option=_build_transfer_option_out(conn, rec.hit_option),
    )


def build_lineup_out(
    conn: sqlite3.Connection, plan: LineupPlan, xpts_next_gw: dict[int, float], based_on: str
) -> LineupOut:
    def _lineup_player(player_id: int) -> LineupPlayerOut:
        snap = repository.get_latest_snapshot_for_player(conn, player_id)
        return LineupPlayerOut(
            player_id=player_id,
            web_name=snap["web_name"] if snap else str(player_id),
            position=ELEMENT_TYPE_ID_TO_POSITION.get(snap["element_type"], "UNK") if snap else "UNK",
            xpts_next_gw=round(xpts_next_gw.get(player_id, 0.0), 2),
        )

    return LineupOut(
        starting_xi=[_lineup_player(p) for p in plan.starting_xi],
        bench_order=[_lineup_player(p) for p in plan.bench_order],
        captain=_lineup_player(plan.captain) if plan.captain is not None else None,
        vice_captain=_lineup_player(plan.vice_captain) if plan.vice_captain is not None else None,
        projected_points=round(plan.projected_points, 2),
        based_on=based_on,
    )


def write(report: Report, config: AppConfig) -> Path:
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    gw = report.metadata.gameweek
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    path = config.reports_dir / f"report_gw{gw}_{timestamp}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    latest_path = config.reports_dir / "latest.json"
    latest_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path
