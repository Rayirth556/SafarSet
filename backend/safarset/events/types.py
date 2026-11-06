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
    """observed_at is the sim minute the source read the vacancy, not when the report arrived. Two sources can disagree about a
    segment (the chart and a TTE terminal); the reducer uses observed_at, never arrival order, to decide which claim stands.
    Without observed_at the claim is undated: it never overrides a dated one."""
    pool_id: str
    from_seg: int = Field(ge=0)
    to_seg: int = Field(gt=0)
    vacancy: int = Field(ge=0)
    observed_at: int | None = Field(default=None, ge=0, le=2880)
    reported_by: str = ""


class NoshowsReported(_Base):
    """Second-chart vacancies: berths the railway's final chart (prepared about 30 min before departure) now shows vacant,
    reported through the TTE hand-held terminal; frees seats on segments [from_seg, to_seg). The event type keeps its first
    name; true no-shows are only known around departure."""
    vehicle_id: str
    pool_id: str
    seats_freed: int = Field(gt=0)
    from_seg: int = Field(ge=0)
    to_seg: int = Field(gt=0)
    reported_by: str = ""


class VehicleDeployed(_Base):
    """The depot dispatches an extra vehicle that was not in the plan (for example another MTC special on the same route). The event
    carries the vehicle's whole spec (same shape as a scenario vehicle), so the log is self-contained and replay rebuilds it."""
    vehicle: dict
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
    status: Literal["SENT", "FAILED", "SKIPPED"] = "SENT"
    detail: dict | None = None                       # e.g. encoding / segments, or why a real SMS failed or was skipped


class ClockSet(_Base):                              # demo clock moves are logged so replay and restarts see the same clock
    to_min: int = Field(ge=0, le=2880)


class GroupSelfBoarded(_Base):                      # a confirmed group ignored its allocation and boarded another vehicle
    group_id: str
    vehicle_id: str
    reason: str = ""


class ConflictResolved(_Base):
    """The operator has read a field disagreement and accepts the value in force. The note is mandatory, like an override reason."""
    conflict_id: int = Field(ge=1)
    note: str

    @field_validator("note")
    @classmethod
    def _note_required(cls, v: str) -> str:
        if len(v.strip()) < 5:
            raise ValueError("marking a field conflict reviewed requires a note (at least 5 characters)")
        return v.strip()


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


class PassengerEscalated(_Base):
    group_id: str
    from_tier: int = Field(ge=0, le=2)
    to_tier: int = Field(ge=0, le=2)
    wait_min: int = Field(ge=0)
    reason: str = Field(min_length=1)


class CommandRejected(_Base):
    command_type: str
    error: str


EVENT_MODELS: dict[str, type[_Base]] = {
    "SCENARIO_LOADED": ScenarioLoaded, "TRAIN_CANCELLED": TrainCancelled, "TRAIN_DELAYED": TrainDelayed,
    "ROAD_CLOSED": RoadClosed, "VACANCY_UPDATE": VacancyUpdate, "NOSHOWS_REPORTED": NoshowsReported,
    "LOAD_REPORT": LoadReport, "PASSENGER_BOARDED": PassengerBoarded, "PASSENGER_DISPLACED": PassengerDisplaced,
    "PLAN_PROPOSED": PlanProposed, "BATCH_APPROVED": BatchApproved, "SMS_SENT": SmsSent, "VEHICLE_DEPLOYED": VehicleDeployed,
    "OPERATOR_OVERRIDE": OperatorOverride, "WEIGHTS_CHANGED": WeightsChanged, "BUFFER_CHANGED": BufferChanged,
    "SIM_PARAMS_CHANGED": SimParamsChanged, "COMMAND_REJECTED": CommandRejected, "CLOCK_SET": ClockSet,
    "GROUP_SELF_BOARDED": GroupSelfBoarded, "PASSENGER_ESCALATED": PassengerEscalated, "CONFLICT_RESOLVED": ConflictResolved,
}
