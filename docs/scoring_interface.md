# Scoring interface (for the teammate writing the real scorer)

The allocator calls one function. Replace `backend/safarset/scoring/stub.py::score` with yours (same signature) and
nothing else changes.

```python
score(group: dict, ctx: ScoreContext) -> {"total": float, "breakdown": [(factor, points), ...]}
ScoreContext(now_min: int, weights: Mapping[str, float])
```

* `ctx.now_min`: scenario clock in minutes of day (the time of the planning run).
* `ctx.weights`: the operator-editable weights (`config/scoring_weights.json` -> `weights`, overridden by
  `WEIGHTS_CHANGED` events). The stub's keys are listed below; your scorer may use different keys, but then
  `scoring_weights.json` and the Rules UI must carry yours.
* Return `breakdown` as a list of `(factor_name, points)` pairs. The UI shows them verbatim in the "Why" panel, and the
  allocator stores them in each allocation's `reason` JSON. `total` should equal the sum for the chosen member/group.
* **Contract:** pure and deterministic; no ML; **ageing must stay linear and uncapped** in time waited (points =
  rate x time waited, no ceiling, no steps: this is what guarantees nobody is starved, and it is what makes stored scores
  safe for shed ordering, see "Shed order" below); tie-breaking is not your job (the allocator sorts by `total` descending, then `booking_time`, then `pnr`, then
  `group_id`).

## Group fields the stub reads

| Field | Type | Meaning |
|---|---|---|
| `size` | int | heads in the group |
| `reserved` | bool | holds a PNR (reserved) vs ticketed unreserved |
| `waiting_since` | int | scenario minutes at which the group began waiting |
| `attrs.ages` | list[int] | one age per member (the stub scores each member, then takes the max) |
| `attrs.max_age` | int | fallback if `ages` is missing |
| `attrs.disability` | bool | any member has a disability or medical need (group level) |
| `attrs.pregnant` | bool | any member is pregnant (group level) |
| `attrs.deadline_min` | int or null | hard arrival deadline, scenario minutes (null = none) |

Other fields exist on the group (`class`, `dest_place`, `requirements`, `booking_time`, `attrs.has_senior`,
`attrs.has_child_under_12`, `attrs.medical_need`, `attrs.language`, `attrs.phone`) but the stub does not read them.
`attrs` is a free-form JSON object: extra fields you need can be added to the generator and the scenario with no schema
migration.

## Stub weights (PLACEHOLDER values in `config/scoring_weights.json`)

`medical_disability`, `senior_60_plus`, `child_or_pregnant`, `hard_deadline`, `reserved_pnr`, `ageing_per_hour`.
The group rule is the highest-scoring member (placeholder).

## Shed order: why stored scores are enough

When capacity shrinks (vacancy cut, buffer change, cancellation) the reducer sheds holders lowest score first. It uses
the `score` stored on each allocation when it was planned, **not** a recomputed one, because:

1. Recomputing inside the reducer would make the event log depend on the scorer's code version: swapping in the real
   scorer would silently change how an old log replays, breaking the "replay rebuilds identical state" guarantee.
2. It is unnecessary for any scorer whose ageing is linear in time: for two groups, `score_a - score_b` does not depend
   on the clock, so their relative order never changes. A recompute would reproduce the stored order.

Limitation: if a future scorer makes ageing non-linear (a cap, a step), stored scores can order groups slightly
differently than a fresh score would. The planner (not the reducer) always scores fresh at planning time.
