"""The prioritisation interface. A teammate's real scorer must have this signature; nothing else changes.

    score(group, ctx) -> {"total": float, "breakdown": [(factor, points), ...]}

`group` is a plain dict (one row of the `groups` table, attrs expanded; see docs/scoring_interface.md for the exact
fields the stub reads). `ctx` carries the clock and the operator-editable weights.

Contract the allocator relies on:
  * pure and deterministic: same (group, ctx) -> same result, no I/O, no randomness;
  * no ML;
  * ageing must stay LINEAR and UNCAPPED in time waited: nobody is starved, and the relative order of two groups never
    changes as the clock advances (so stored scores stay valid when ordering shed victims; see docs/scoring_interface.md);
  * tie-breaking is NOT the scorer's job: the allocator applies (booking_time, pnr, group_id).
"""
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, TypedDict


class ScoreResult(TypedDict):
    total: float
    breakdown: list  # [(factor_name: str, points: float), ...]; JSON-friendly


@dataclass(frozen=True)
class ScoreContext:
    now_min: int                                   # scenario clock, minutes of day
    weights: Mapping[str, float] = field(default_factory=dict)


class Scorer(Protocol):
    def __call__(self, group: Mapping[str, Any], ctx: ScoreContext) -> ScoreResult: ...
