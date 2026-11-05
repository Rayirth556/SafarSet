"""Request bodies."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReplanBody(_Body):
    fresh: bool = False
    weights: dict | None = None            # "adjust weights and re-run": plans from scratch, batch cause WEIGHTS_RERUN
    ts_sim: int | None = None


class ApproveBody(_Body):
    ts_sim: int | None = None


class RulesBody(_Body):
    weights: dict | None = None
    buffers: dict[str, float] | None = None
    ts_sim: int | None = None


class OverrideBody(_Body):
    action: Literal["ASSIGN", "UNASSIGN", "RESUME_AUTO"]
    reason: str
    pool_id: str | None = None
    board_idx: int | None = None
    alight_idx: int | None = None
    ts_sim: int | None = None


class BoardBody(_Body):
    allocation_id: int | None = None
    group_id: str | None = None
    ts_sim: int | None = None


class LoadReportBody(_Body):
    level: Literal["NORMAL", "FULL", "OVERCROWDED"]
    count: int | None = Field(default=None, ge=0)
    pool_id: str | None = None
    ts_sim: int | None = None


class VacancyBody(_Body):
    pool_id: str
    from_seg: int = Field(ge=0)
    to_seg: int = Field(gt=0)
    vacancy: int = Field(ge=0)
    ts_sim: int | None = None


class LoadScenarioBody(_Body):
    seed: int = 42
    n_passengers: int = Field(default=300, ge=1, le=5000)
    pct_senior: float = Field(default=0.12, ge=0, le=1)
    pct_groups: float = Field(default=0.35, ge=0, le=1)
    compliance_rate: float = Field(default=0.8, ge=0, le=1)
    walkon_rate: float = Field(default=0.3, ge=0, le=1)
    pct_unreserved: float = Field(default=0.25, ge=0, le=1)
    n_mtc_specials: int = Field(default=4, ge=0, le=40)
    n_intercity_specials: int = Field(default=2, ge=0, le=40)
    cancel_time: str = "14:00"
    exclude_trains: list[str] = []


class CancelBody(_Body):
    vehicle_id: str | None = None
    reason: str = "SIMULATED cancellation at origin"


class DelayBody(_Body):
    vehicle_id: str
    delay_min: int = Field(gt=0)


class CloseRoadBody(_Body):
    route_id: str
    description: str = "road closed"


class InjectOvercrowdBody(_Body):
    vehicle_id: str | None = None
    count: int | None = Field(default=None, ge=0)


class InjectVacanciesBody(_Body):
    vehicle_id: str | None = None
    pool_id: str | None = None
    seats: int | None = Field(default=None, gt=0)


InjectNoshowsBody = InjectVacanciesBody          # old name


class SimParamsBody(_Body):
    compliance_rate: float | None = Field(default=None, ge=0, le=1)
    walkon_rate: float | None = Field(default=None, ge=0, le=1)


class ClockBody(_Body):
    to_min: int = Field(ge=0, le=2880)
