from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from fpl_model.config import ConfigError, load_config
from fpl_model.logging_setup import setup_logging

log = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a full FPL model update.")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--gw-override", type=int, default=None)
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--skip-understat", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    setup_logging(config.log_level, config.data_dir.parent / "logs")
    log.info("Loaded config from %s (team_id=%s)", args.config, config.team_id)

    from fpl_model.data.ingest import CriticalDataSourceError, run_full_refresh
    from fpl_model.storage.db import apply_schema, get_connection

    conn = get_connection(config.db_path)
    apply_schema(conn)

    try:
        run_full_refresh(
            config,
            conn,
            gw_override=args.gw_override,
            force_refresh=args.force_refresh,
            skip_understat=args.skip_understat,
        )
    except CriticalDataSourceError as exc:
        log.critical("Aborting: %s", exc)
        return 1

    from fpl_model.analysis import form as form_module
    from fpl_model.analysis import team_strength as team_strength_module
    from fpl_model.analysis import xpts as xpts_module
    from fpl_model.analysis.squad_state import compute_squad_state
    from fpl_model.analysis.value import compute_value
    from fpl_model.data.scoping import select_scoped_players
    from fpl_model.data.scoring_rules import load_scoring_rules
    from fpl_model.report.writer import build_analysis_section, build_bare_squad_report, write
    from fpl_model.storage import repository

    squad_state = compute_squad_state(conn, config)
    report = build_bare_squad_report(conn, config, squad_state)

    scoped_player_ids = list(select_scoped_players(conn, squad_state.current_squad))
    scoring = load_scoring_rules(config)
    team_strength = team_strength_module.compute_team_strength(conn)
    form_results = form_module.compute_all(conn, scoped_player_ids, scoring, config.form_weights)
    xpts_results = xpts_module.compute_all(
        conn, scoped_player_ids, squad_state.upcoming_gameweek, config, scoring, team_strength
    )
    xpts_horizon = {
        pid: xpts_module.compute_horizon_xpts(
            conn, pid, squad_state.upcoming_gameweek, config.xpts_horizon_gws, config.xpts_horizon_decay,
            scoring, config.form_weights, team_strength,
        )
        for pid in scoped_player_ids
    }
    value_results = compute_value(conn, scoped_player_ids, xpts_horizon, config)

    report.analysis = build_analysis_section(
        conn, form_results, xpts_results, xpts_horizon, team_strength, value_results,
        config.differential_ownership_threshold,
    )

    from fpl_model.constants import ELEMENT_TYPE_ID_TO_POSITION
    from fpl_model.optimizer import lineup_optimizer, transfer_optimizer
    from fpl_model.report.writer import build_lineup_out, build_transfer_recommendation_out

    candidate_ids = sorted(set(scoped_player_ids) | set(squad_state.current_squad))
    positions: dict[int, str] = {}
    clubs: dict[int, int] = {}
    prices: dict[int, int] = {}
    for pid in candidate_ids:
        snap = repository.get_latest_snapshot_for_player(conn, pid)
        if snap is None:
            continue
        positions[pid] = ELEMENT_TYPE_ID_TO_POSITION.get(snap["element_type"], "MID")
        clubs[pid] = snap["team_id"]
        prices[pid] = snap["now_cost"]

    transfer_rec = transfer_optimizer.recommend_transfers(
        squad_state, candidate_ids, positions, clubs, prices, xpts_horizon, config
    )
    report.transfer_recommendation = build_transfer_recommendation_out(conn, transfer_rec)

    xpts_next_gw = {pid: xr.total for pid, xr in xpts_results.items()}
    current_lineup_plan = lineup_optimizer.solve(squad_state.current_squad, positions, xpts_next_gw)
    report.current_lineup = build_lineup_out(conn, current_lineup_plan, xpts_next_gw, "current_squad")

    recommended_squad = (
        transfer_rec.hit_option.new_squad if transfer_rec.recommended == "hit" else transfer_rec.banked_option.new_squad
    )
    if recommended_squad and set(recommended_squad) != set(squad_state.current_squad):
        recommended_lineup_plan = lineup_optimizer.solve(recommended_squad, positions, xpts_next_gw)
    else:
        recommended_lineup_plan = current_lineup_plan
    report.recommended_lineup = build_lineup_out(conn, recommended_lineup_plan, xpts_next_gw, "recommended_squad")

    from fpl_model.optimizer import chips as chips_module
    from fpl_model.report.writer import build_chip_advice_out

    chip_bundle = chips_module.recommend_all(
        conn, squad_state, candidate_ids, positions, clubs, prices, xpts_horizon, xpts_results,
        transfer_rec, squad_state.upcoming_gameweek, config, scoring, config.form_weights, team_strength,
    )
    report.chip_advice = build_chip_advice_out(chip_bundle)

    path = write(report, config)
    repository.log_report(conn, report.metadata.generated_at, report.metadata.gameweek, str(path))
    log.info("Report written to %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
