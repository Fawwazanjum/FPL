"""Pydantic Report contract. Claude reads the written JSON to build the dashboard
artifact — this schema is the interface between the Python model and the agent.

Phase 1 only populates ReportMetadata + SquadAssessment. Later phases (form,
xpts, transfer/lineup/chip recommendations, differentials) extend this file
additively — existing fields are not renamed or removed once other code and
Claude's dashboard-building logic depend on them.
"""

from __future__ import annotations

from pydantic import BaseModel


class ReportMetadata(BaseModel):
    generated_at: str
    gameweek: int
    upcoming_gameweek: int
    team_id: int
    data_quality_flags: list[str] = []


class PlayerSnapshotOut(BaseModel):
    player_id: int
    web_name: str
    position: str
    team_id: int
    now_cost_millions: float
    purchase_price_millions: float
    sell_price_millions: float
    selected_by_percent: float | None
    total_points: int | None
    event_points: int | None
    form: float | None
    status: str
    news: str | None
    in_starting_xi: bool
    is_captain: bool
    is_vice_captain: bool


class SquadAssessment(BaseModel):
    bank_millions: float
    squad_value_millions: float
    free_transfers_available: int
    chips_available: list[str]
    chips_used: list[dict]
    players: list[PlayerSnapshotOut]


class PlayerFormOut(BaseModel):
    player_id: int
    web_name: str
    position: str
    form_score: float
    games_played: int
    last_season_rate: float
    season_rate: float
    recent_rate_adjusted: float
    used_position_fallback: bool


class PlayerXptsOut(BaseModel):
    player_id: int
    web_name: str
    position: str
    xpts_next_gw: float
    xpts_horizon: float
    opponent_team_id: int | None
    is_home: bool | None
    p_full_involvement: float
    reasoning: str


class TeamStrengthOut(BaseModel):
    team_id: int
    team_name: str
    actual_goals_for: int
    actual_goals_against: int
    attack_xg: float
    defense_xgc: float
    attack_overperformance: float
    defense_overperformance: float
    attack_index: float
    defense_index: float


class ValuePickOut(BaseModel):
    player_id: int
    web_name: str
    position: str
    now_cost_millions: float
    selected_by_percent: float
    xpts_horizon: float
    score: float


class AnalysisSection(BaseModel):
    form_by_player: dict[int, PlayerFormOut] = {}
    xpts_by_player: dict[int, PlayerXptsOut] = {}
    team_strength: list[TeamStrengthOut] = []
    top_differentials: dict[str, list[ValuePickOut]] = {}
    top_template_picks: dict[str, list[ValuePickOut]] = {}


class Report(BaseModel):
    metadata: ReportMetadata
    squad: SquadAssessment
    analysis: AnalysisSection | None = None
