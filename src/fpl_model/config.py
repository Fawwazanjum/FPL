from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class ConfigError(Exception):
    pass


class CacheTtlHours(BaseModel):
    bootstrap_static: float = 6.0
    fixtures: float = 12.0
    element_summary: float = 24.0
    entry: float = 6.0
    understat: float = 48.0
    league_standings: float = 6.0


class FormWeights(BaseModel):
    last_season_floor_weight: float = 0.15
    prior_decay_games: int = 8
    recent_vs_season_split_recent: float = 0.65
    recent_form_shrinkage_minutes: float = 400.0


class OptimizerConfig(BaseModel):
    max_transfers_considered: int = 5
    hit_cost: int = 4
    candidate_pool_per_position: int = 40
    # A hit is only ever recommended if it nets at least this many more points
    # (over the horizon, after the -4/-8/etc. is already subtracted) than
    # simply banking the transfer — a deliberate conservative bias, not a pure
    # breakeven optimizer. See memory: fpl-transfer-hit-conservatism.
    hit_margin_required: float = 2.0


class UnderstatConfig(BaseModel):
    enabled: bool = True


class PendingTransfer(BaseModel):
    player_out: int
    player_in: int


class ChipsConfig(BaseModel):
    # Wildcard: only recommended when BOTH the value gap and data-maturity
    # gates clear — a large gap computed from too few real gameweeks is not
    # trustworthy, however big it looks (see memory: fpl-model-project, the
    # GW2 wildcard discussion this was built to formalize).
    wildcard_gap_threshold: float = 15.0
    min_games_for_wildcard_confidence: int = 3
    # Free Hit: recommended when at least this many current starters have no
    # fixture in a gameweek.
    free_hit_blank_threshold: int = 4
    # Triple Captain: recommended when the best captain candidate's projected
    # haul in a double-gameweek exceeds a normal week's best by this margin.
    triple_captain_uplift_threshold: float = 4.0
    # Bench Boost: recommended when the bench's own combined starting-XI-
    # weighted value in a target gameweek clears this (usually needs a double
    # gameweek to be worthwhile at all).
    bench_boost_min_bench_value: float = 12.0


class AppConfig(BaseModel):
    team_id: int = Field(gt=0)
    data_dir: Path = Path("./data")
    reports_dir: Path = Path("./reports")
    cache_ttl_hours: CacheTtlHours = Field(default_factory=CacheTtlHours)
    form_weights: FormWeights = Field(default_factory=FormWeights)
    xpts_horizon_gws: int = 5
    xpts_horizon_decay: float = 0.75
    differential_ownership_threshold: float = 10.0
    differential_gamma: float = 1.5
    optimizer: OptimizerConfig = Field(default_factory=OptimizerConfig)
    understat: UnderstatConfig = Field(default_factory=UnderstatConfig)
    chips: ChipsConfig = Field(default_factory=ChipsConfig)
    purchase_price_overrides: dict[int, float] = Field(default_factory=dict)
    # FPL's own API only exposes locked-in picks and the transfers ledger
    # AFTER a gameweek's deadline passes — a transfer made this week for next
    # week's deadline is invisible to both endpoints until then. Declare it
    # here and squad_state.py applies it on top of whatever picks the API
    # currently reports, so the report doesn't silently go stale between a
    # real transfer and the deadline. Clear this list out once the gameweek
    # rolls over and the API catches up on its own — it's a manual bridge,
    # not a permanent record (the transfer already happened for real; this
    # config isn't what makes it happen).
    pending_transfers: list[PendingTransfer] = Field(default_factory=list)
    # Classic mini-league IDs to track rivals for — from the league's
    # standings URL: fantasy.premierleague.com/leagues/<id>/standings/c.
    # Public data (the standings page and every entry's picks are visible to
    # anyone via FPL's own site), fetched the same way this tool already
    # fetches your own team. See analysis/rivals.py.
    mini_league_ids: list[int] = Field(default_factory=list)
    news_overrides_path: Path = Path("./news_overrides.yaml")
    log_level: str = "INFO"

    @field_validator("data_dir", "reports_dir", "news_overrides_path", mode="before")
    @classmethod
    def _coerce_path(cls, v: object) -> object:
        return Path(v) if v is not None else v

    @property
    def db_path(self) -> Path:
        return self.data_dir / "fpl_model.db"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


def load_config(path: Path) -> AppConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"Config file not found: {path}. Copy config.example.yaml to config.yaml "
            "and fill in your team_id."
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse config YAML at {path}: {exc}") from exc

    base_dir = path.resolve().parent
    for key in ("data_dir", "reports_dir", "news_overrides_path"):
        if key in raw and raw[key] is not None and not Path(raw[key]).is_absolute():
            raw[key] = str(base_dir / raw[key])

    try:
        config = AppConfig.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"Invalid config at {path}: {exc}") from exc

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    return config
