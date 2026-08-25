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

    from fpl_model.analysis.squad_state import compute_squad_state
    from fpl_model.report.writer import build_bare_squad_report, write
    from fpl_model.storage import repository

    squad_state = compute_squad_state(conn, config)
    report = build_bare_squad_report(conn, config, squad_state)
    path = write(report, config)
    repository.log_report(conn, report.metadata.generated_at, report.metadata.gameweek, str(path))
    log.info("Report written to %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
