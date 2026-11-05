# SafarSet API and WebSocket contract (Phase 6)

Run: `cd backend && uvicorn safarset.api.app:app --reload` (port 8000). Interactive docs: `/docs`. CORS is open.
Everything in the demo is SIMULATED unless a field says REAL. Times are minutes of day (`*_min`) with an `HH:MM` twin.

**Errors** always look like `{"detail": {"error": "<human message>", "kind": "<Kind>"}}`:
`409` refused by a rule (kinds `Rejected`, `StaleBatch`, `BufferRejected`, `NoScenario`, `TimelineDone`), `422` bad request
(`InvalidRequest` with a `fields` list, `InvalidScenario`, `InvalidWeights`), `404` unknown id (`NotFound`).

Nothing is ever sent to a passenger until a batch is approved (`POST /api/batches/{id}/approve`).

## 1. Operator dashboard (`/api`)

| Method and path | Purpose |
|---|---|
| `GET /state` | clock, disruption `banner`, `kpis`, `pending_batch` summary, `sim_params`, `last_seq` |
| `GET /kpis` | `affected / tentative / confirmed / boarded / unresolved` as `{groups, heads}`, plus `displaced_awaiting_replacement`, `held_by_operator` |
| `GET /capacity?role=ALLOCATION\|TRANSFER_LEG\|all` | per vehicle, per pool, per **segment**: `cap, confirmed, tentative, boarded, free`; `formula` (e.g. `"40 × 75% = 30"`), `buffer_pct`, `field_report {level,count}` (the "overcrowded" flag) |
| `GET /passengers?status=&dest=&q=&limit=&offset=` | table: `score`, `rank`, `score_breakdown`, `state` (UNRESOLVED / TENTATIVE / CONFIRMED / BOARDED), `allocation`, `flags`, `displaced`, `held_by_operator` |
| `GET /passengers/{group_id}/why` | the "Why" panel: fresh `score` + `rank`, stored allocation `reason` (machine-readable, with `text`), `decision_text`, `unresolved` (cause + ranked `alternatives`), `history` |
| `GET /unresolved` | unresolved demand grouped by destination with `reason`, ranked `alternatives` (`LATE_ARRIVAL`, `MULTI_LEG`, `WAITLIST`), `blocking_groups` / `blocking_why` |
| `GET /batches/pending` | approval panel (null when none): `batch_id`, `cause`, `stale`, **`weights_out_of_date`** (the operator edited the weights after this plan was made and has not re-run), `diff` counts, `items` grouped by category |
| `GET /batches`, `GET /batches/{id}` | history and any batch |
| `POST /batches/{id}/approve` | approve (moves TENTATIVE to CONFIRMED and sends SMS). `409 StaleBatch` if capacity it uses changed: re-plan, never approve as-is |
| `POST /replan` `{fresh?, weights?}` | new pending batch. With `weights` = "adjust weights and re-run": plans from scratch, batch `cause` is `WEIGHTS_RERUN` |
| `GET /rules`, `PUT /rules` `{weights?, buffers?}` | weights (exact key set) and buffers per mode. A buffer below confirmed+boarded is `409 BufferRejected` and nothing changes |
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
`POST /vehicles/{id}/vacancy` `{pool_id, from_seg, to_seg, vacancy}` (stands in for the TTE hand-held terminal).
A FULL/OVERCROWDED report displaces confirmed groups that have no physical room and triggers a re-plan.

## 3. Passenger phone mock
`GET /api/phone/{pnr_or_group_id}/messages`; live stream `WS /ws/phone/{pnr_or_group_id}`:
first `{"type":"history","found":bool,"messages":[...]}`, then `{"type":"sms","group_id","channel","lang","message","reason"}`.
Each message names the vehicle, where to board, the times, the destination, the group size and the **reason**, in the group's language
(`en` / `ta`; the Tamil is a draft that needs native review). Samples: `docs/messages.md`. `detail` has `chars`, `encoding`, `segments`.
The phone mock shows only `PHONE_MOCK` messages; real SMS (optional, behind a flag) is a separate `SMS_HTTP` record.

## 4. Demo controls (`/sim`, not part of the product)
`POST /load-scenario` `{seed, n_passengers, pct_senior, pct_groups, compliance_rate, walkon_rate, ...}`,
`POST /cancel-train`, `POST /delay-train`, `POST /close-road`, `POST /inject-overcrowd`, `POST /inject-noshows`,
`GET|PUT /params` (compliance and walk-on sliders), `POST /clock` (logged as a `CLOCK_SET` event), `POST /depart/{vehicle_id}` (plan -> observe -> re-plan using the sliders: confirmed groups that ignore their allocation
rush the earliest-departing vehicle toward their destination and add to its load; allocated groups board in priority order while there is room; the load
report counts everyone present and OVERCROWDED displaces whoever is refused; rushers become BOARDED with `boarded_on_own` set),
`GET /timeline`, `POST /timeline/next`, `POST /timeline/reset` (play the scripted demo one step at a time).

## 5. Live stream `WS /ws`
On connect: `{"type":"snapshot","loaded","last_seq","clock","banner","kpis","pending_batch","sim_params"}`.
After every change, in this order: one `{"type":"event","seq","event"}` per new event (seq is contiguous: a gap means refetch),
then `{"type":"kpis","kpis","clock","last_seq"}`, then `{"type":"invalidate","topics":[...],"last_seq"}`.
Topics: `banner capacity passengers unresolved batch kpis field rules phone sim all`; refetch the matching REST endpoints.
`COMMAND_REJECTED` events carry `"rejected": true` so the UI can hide them. Other messages: `{"type":"reset", ...snapshot}`
(a new scenario was loaded), `{"type":"clock"}`. Client may send `{"type":"ping"}` (reply `pong`) or `{"type":"snapshot"}`.
