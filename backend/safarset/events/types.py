"""Typed payloads for every event type. The event log stores these (validated) as JSON."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioLoaded(_Base):
    scenario: dict                                  # full generated scenario (SIMULATED), so the log is self-contained


class TrainCancelled(_Base):
    vehicle_id: str
    reason: str = ""


class TrainDelayed(_Base):
    vehicle_id: str
    delay_min: int = Field(gt=0)


class RoadClosed(_Base):
    route_id: str | None = None
    description: str = Field(min_length=1)


class VacancyUpdate(_Base):                         # HHT-shaped: absolute vacancy for segments [from_seg, to_seg)
    pool_id: str
    from_seg: int = Field(ge=0)
    to_seg: int = Field(gt=0)
    vacancy: int = Field(ge=0)
    reported_by: str = ""


class NoshowsReported(_Base):                       # TTE reports no-shows: frees seats on segments [from_seg, to_seg)
    vehicle_id: str
    pool_id: str
    seats_freed: int = Field(gt=0)
    from_seg: int = Field(ge=0)
    to_seg: int = Field(gt=0)
    reported_by: str = ""


class LoadReport(_Base):                            # ETM/conductor-shaped
    vehicle_id: str
    pool_id: str
    level: Literal["NORMAL", "FULL", "OVERCROWDED"]
    count: int | None = Field(default=None, ge=0)
    reported_by: str = ""


class PassengerBoarded(_Base):
    allocation_id: int


class PassengerDisplaced(_Base):                    # a CONFIRMED group physically cannot board
    allocation_id: int
    reason: str = Field(min_length=3)


class PlanAllocation(_Base):
    group_id: str
    pool_id: str
    board_idx: int = Field(ge=0)
    alight_idx: int = Field(gt=0)
    score: float = 0.0
    reason: dict                                     # machine-readable: score breakdown, binding constraint, class step...


class PlanItem(_Base):
    kind: Literal["PLACED", "NEWLY_PLACED", "DISPLACED", "RESHUFFLED", "UNRESOLVED"]
    group_id: str
    detail: dict = Field(default_factory=dict)


class PlanProposed(_Base):
    """A full replacement of the pending tentative set: `allocations` is every TENTATIVE row the plan wants.
    Any earlier pending batch is superseded (its tentative rows released first). `release` lists extra TENTATIVE
    allocation ids to release (moves). CONFIRMED/BOARDED rows are never touched by a plan."""
    batch_id: str
    base_seq: int
    cause: str = "REPLAN"
    allocations: list[PlanAllocation]
    release: list[int] = Field(default_factory=list)
    items: list[PlanItem] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class BatchApproved(_Base):
    batch_id: str


class SmsSent(_Base):
    group_id: str
    channel: str
    lang: str
    message: str
    reason: str | None = None


class OperatorOverride(_Base):
    """ASSIGN: put the group on pool_id between board_idx and alight_idx (TENTATIVE, in the pending batch, needs approval).
    UNASSIGN: release its seat and hold it out of automatic planning. RESUME_AUTO: clear the hold. Reason is mandatory."""
    group_id: str
    action: Literal["ASSIGN", "UNASSIGN", "RESUME_AUTO"]
    reason: str
    pool_id: str | None = None
    board_idx: int | None = Field(default=None, ge=0)
    alight_idx: int | None = Field(default=None, gt=0)

    @field_validator("reason")
    @classmethod
    def _reason_required(cls, v: str) -> str:
        if len(v.strip()) < 5:
            raise ValueError("an operator override requires a reason (at least 5 characters)")
        return v.strip()


class WeightsChanged(_Base):
    weights: dict


class BufferChanged(_Base):
    mode: str
    buffer_pct: float = Field(ge=0, le=1)


class SimParamsChanged(_Base):
    params: dict


class CommandRejected(_Base):
    command_type: str
    error: str


EVENT_MODELS: dict[str, type[_Base]] = {
    "SCENARIO_LOADED": ScenarioLoaded, "TRAIN_CANCELLED": TrainCancelled, "TRAIN_DELAYED": TrainDelayed,
    "ROAD_CLOSED": RoadClosed, "VACANCY_UPDATE": VacancyUpdate, "NOSHOWS_REPORTED": NoshowsReported,
    "LOAD_REPORT": LoadReport, "PASSENGER_BOARDED": PassengerBoarded, "PASSENGER_DISPLACED": PassengerDisplaced,
    "PLAN_PROPOSED": PlanProposed, "BATCH_APPROVED": BatchApproved, "SMS_SENT": SmsSent,
    "OPERATOR_OVERRIDE": OperatorOverride, "WEIGHTS_CHANGED": WeightsChanged, "BUFFER_CHANGED": BufferChanged,
    "SIM_PARAMS_CHANGED": SimParamsChanged, "COMMAND_REJECTED": CommandRejected,
}
