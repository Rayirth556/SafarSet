# SafarSet API and WebSocket contract (Phase 6)

Run: `cd backend && uvicorn safarset.api.app:app --reload` (port 8000). Interactive docs: `/docs`. CORS is open.
Everything in the demo is SIMULATED unless a field says REAL. Times are minutes of day (`*_min`) with an `HH:MM` twin.

**Errors** always look like `{"detail": {"error": "<human message>", "kind": "<Kind>"}}`:
`409` refused by a rule (kinds `Rejected`, `StaleBatch`, `BufferRejected`, `CapacityRejected`, `NoScenario`, `TimelineDone`), `422` bad request
(`InvalidRequest` with a `fields` list, `InvalidScenario`, `InvalidWeights`), `404` unknown id (`NotFound`).

A `CapacityRejected` error says which vehicle, coach and segment is full in plain language (`No room on MTC 120 R1 (BUS-SPL-02), UR: A to B has 0 free seats and this group needs 1.`)
and adds `"detail": "blocked by database capacity constraint"` (the database, not just the planner, refused it).

Nothing is ever sent to a passenger until a batch is approved (`POST /api/batches/{id}/approve`).

## 1. Operator dashboard (`/api`)

| Method and path | Purpose |
|---|---|
| `GET /state` | clock, disruption `banner`, `kpis`, `pending_batch` summary, `sim_params`, `last_seq` |
| `GET /kpis` | `affected / tentative / confirmed / boarded / unresolved` as `{groups, heads}`, plus `displaced_awaiting_replacement`, `held_by_operator`, and `composition` = `{pnr_heads, ticketed_unreserved_heads, unreserved_estimate: {heads, estimated: true}}` (affected PNR holders, affected ticketed-unreserved passengers, and a separate **estimate** of unregistered walk-ons that is NOT part of `affected`) |
| `GET /capacity?role=ALLOCATION\|TRANSFER_LEG\|all` | per vehicle, per pool, per **segment**: `cap, confirmed, tentative, boarded, free`; `formula` (e.g. `"40 × 75% = 30"`), `buffer_pct`, `field_report {level,count}` (the "overcrowded" flag) |
| `GET /passengers?status=&dest=&q=&limit=&offset=` | table: `score`, `rank`, `score_breakdown`, `tier` (0, 1, 2), `tier_name` (`CRITICAL`, `HIGH`, `STANDARD`), `tier_reason`, `escalated`, `effective_score`, `state` (UNRESOLVED / TENTATIVE / CONFIRMED / BOARDED), `allocation`, `flags`, `displaced`, `held_by_operator` |
| `GET /passengers/{group_id}/why` | the "Why" panel: fresh `score` + `rank`, `tier`, `tier_name`, `tier_reason`, `escalated`, `escalation_reason`, `base_score`, `effective_score`, `ageing`, `factor_scores`, `factor_weights`, `priority_policy`, stored allocation `reason` (machine-readable, with `text`), `decision_text`, `unresolved` (cause + ranked `alternatives`), `history` |
| `GET /unresolved` | unresolved demand grouped by destination with `reason`, ranked `alternatives` (`LATE_ARRIVAL`, `MULTI_LEG`, `WAITLIST`), `blocking_groups` / `blocking_why` |
| `GET /batches/pending` | approval panel (null when none): `batch_id`, `cause`, `stale`, **`weights_out_of_date`** (the operator edited the weights after this plan was made and has not re-run), `diff` counts, `items` grouped by category |
| `GET /batches`, `GET /batches/{id}` | history and any batch |
| `POST /batches/{id}/approve` | approve (moves TENTATIVE to CONFIRMED and sends SMS). `409 StaleBatch` if capacity it uses changed: re-plan, never approve as-is |
| `POST /replan` `{fresh?, weights?}` | new pending batch. With `weights` = "adjust weights and re-run": plans from scratch, batch `cause` is `WEIGHTS_RERUN` |
| `GET /rules`, `PUT /rules` `{weights?, buffers?}` | weights (exact key set), buffers per mode, and `priority_policy`. A buffer below confirmed+boarded is `409 BufferRejected` and nothing changes |
| `GET /priority-policy` | complete validated passenger prioritisation policy (`config/priority_policy.json`) including tiers, weights, ageing, escalation thresholds, and companion validation rules |
| `GET /notifier` | which backends are live: phone mock (always), real SMS (only when enabled by `SAFARSET_SMS_*`), languages, Tamil review status |
| `GET /events?after=&limit=&hide_rejected=true&tail=false` | event log. `COMMAND_REJECTED` rows are hidden unless `hide_rejected=false`; `tail=true` returns the newest `limit` |
| `POST /groups/{group_id}/override` `{action: ASSIGN\|UNASSIGN\|RESUME_AUTO, reason, pool_id?, board_idx?, alight_idx?}` | operator override; **reason is mandatory** and logged |

**Batch `cause`:** an event type (`TRAIN_CANCELLED`, `LOAD_REPORT`, ...), `WEIGHTS_RERUN`, `MANUAL_REPLAN`, `OPERATOR_OVERRIDE`.

**Diff categories** (`diff[cat] = {groups, heads}` and `items[cat]`): `DISPLACED`, `NEWLY_PLACED`, `RESHUFFLED`, `PLACED` (unchanged), `UNRESOLVED`.
Item `detail` flags for the UI:
* `DISPLACED`: `replaced` (does this plan give a new seat), `cause`, **`old_sms_still_held: true`** (the passenger still holds the old confirmation until a new batch is approved: warn the operator), `operator_override`.
* `RESHUFFLED`: `forced` (true = imposed by a capacity change, false = chosen by the bounded reshuffle), `moved_from`.
* `UNRESOLVED`: `reason`, `alternatives`, and when the stability rule is the blocker: `blocking_groups`, `blocking_why` (`NO_ALTERNATIVE_WITHIN_TOLERANCE` or `MOVES_AS_MANY_HEADS_AS_PLACED`), `blocking_moved_heads`, `blocking_placed_heads`.

## 2. Field view (`/api/field`, conductor / TTE on a phone)
`GET /vehicles`, `GET /vehicles/{id}/manifest` (expected passengers, `can_board`),
`POST /vehicles/{id}/board` `{allocation_id | group_id}` (only CONFIRMED can board),
`POST /vehicles/{id}/load-report` `{level: NORMAL|FULL|OVERCROWDED, count?}` (stands in for the ETM; no count = treated as exactly full),
`POST /vehicles/{id}/vacancy` `{pool_id, from_seg, to_seg, vacancy}` (second-chart vacancies: stands in for the TTE hand-held terminal; the railway prepares its final chart about 30 min before departure, true no-shows are known only around departure).
A FULL/OVERCROWDED report displaces confirmed groups that have no physical room and triggers a re-plan.

## 3. Passenger phone mock
`GET /api/phone/{pnr_or_group_id}/messages`; live stream `WS /ws/phone/{pnr_or_group_id}`:
first `{"type":"history","found":bool,"messages":[...]}`, then `{"type":"sms","group_id","channel","lang","message","reason"}`.
Each message also has `kind` (`NEW`, `CHANGED`, `DISPLACED_UNPLACED`; null on logs written before this field existed) and `sent_at` / `sent_at_min` (the simulation clock when it was sent); the `sms` push carries the same fields.
Each message names the vehicle, where to board, the times, the destination, the group size and the **reason**, in the group's language
(`en` / `ta`; the Tamil is a draft that needs native review). Samples: `docs/messages.md`. `detail` has `chars`, `encoding`, `segments`.
The phone mock shows only `PHONE_MOCK` messages; real SMS (optional, behind a flag) is a separate `SMS_HTTP` record.

## 4. Demo controls (`/sim`, not part of the product)
`POST /load-scenario` `{seed, n_passengers, pct_senior, pct_groups, compliance_rate, walkon_rate, ...}`,
`POST /cancel-train`, `POST /delay-train`, `POST /close-road`, `POST /inject-overcrowd`, `POST /deploy-bus` (the depot sends an extra special on the overcrowded bus's route: event `VEHICLE_DEPLOYED`, which carries the whole vehicle spec; a re-plan follows; a vehicle id can be deployed once), `POST /inject-vacancies` (second-chart vacancies; `/inject-noshows` is the deprecated old name),
`GET|PUT /params` (compliance and walk-on sliders), `POST /clock` (logged as a `CLOCK_SET` event), `POST /depart/{vehicle_id}` (plan -> observe -> re-plan using the sliders: confirmed groups that ignore their allocation
rush the earliest-departing vehicle toward their destination and add to its load; allocated groups board in priority order while there is room; the load
report counts everyone present and OVERCROWDED displaces whoever is refused; rushers become BOARDED with `boarded_on_own` set),
`GET /timeline`, `POST /timeline/next`, `POST /timeline/reset` (play the scripted demo one step at a time; each step has a display `label`, for example "Second-chart vacancies reported on a train"; steps are found by `type`, not by position).
An end-to-end script that plays all of it and checks the state at every step: `python scripts/run_demo.py`.

## 5. Live stream `WS /ws`
On connect: `{"type":"snapshot","loaded","last_seq","clock","banner","kpis","pending_batch","sim_params"}`.
After every change, in this order: one `{"type":"event","seq","event"}` per new event (seq is contiguous: a gap means refetch),
then `{"type":"kpis","kpis","clock","last_seq"}`, then `{"type":"invalidate","topics":[...],"last_seq"}`.
Topics: `banner capacity passengers unresolved batch kpis field rules phone sim all`; refetch the matching REST endpoints.
`COMMAND_REJECTED` events carry `"rejected": true` so the UI can hide them. Other messages: `{"type":"reset", ...snapshot}`
(a new scenario was loaded), `{"type":"clock"}`. Client may send `{"type":"ping"}` (reply `pong`) or `{"type":"snapshot"}`.
