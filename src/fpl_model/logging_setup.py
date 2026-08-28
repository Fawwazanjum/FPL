from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(log_level: str = "INFO", log_dir: Path | None = None) -> None:
    # Windows' console defaults sys.stdout to the system codepage (cp1252),
    # not UTF-8 — a league name or player name with an emoji or accented
    # character (real example: rival tracking pulling a league literally
    # named with a trophy emoji) then crashes the log call outright. Force
    # UTF-8 where the stream supports reconfiguring it; harmless no-op
    # elsewhere (e.g. a stream that's already UTF-8, or doesn't support it).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "fpl_model.log", encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
