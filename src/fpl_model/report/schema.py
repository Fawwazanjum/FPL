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


class Report(BaseModel):
    metadata: ReportMetadata
    squad: SquadAssessment
