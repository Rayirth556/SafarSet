# SafarSet

Backend for **SafarSet**, a hackathon project for *PS2: The Stranded Network: Dynamic Travel Recovery & Passenger Coordination*
(Hack the Constraint, SRMIST Chennai). When a long-distance train is cancelled at Chennai Central, SafarSet groups the
stranded passengers, re-accommodates them on alternate trains and then buses within the capacity that really exists, explains every
decision, and keeps re-planning as the situation changes. **An operator approves every plan before any SMS is sent.**

> **Everything you see in a demo is SIMULATED** unless a field says `REAL`. See [Real vs simulated](#real-vs-simulated).

## What it does

| Requirement | How |
|---|---|
| Group passengers by destination, boarding point, needs and time limits | A group (family or party) is never split; compatibility checks destination, boarding stop, hard deadline, wheelchair access and ticket class |
| Re-route after cancellations, delays, closures | Events (`TRAIN_CANCELLED`, `TRAIN_DELAYED`, `ROAD_CLOSED`, field reports) trigger a re-plan that is proposed, never applied silently |
| Capacity-aware allocation, **no over-allocation** | Capacity is per vehicle **segment** (a seat used A to B is free again for B to D). The **database** rejects any write that would oversell: `CHECK (used <= cap)` plus triggers that update every segment of a journey or none |
| Transparent, inspectable priorities | Rule-based score with a visible breakdown, deterministic tie-breaks, ageing so nobody starves; every allocation stores a machine-readable reason |
| Alternatives for people who cannot be placed | Ranked suggestions: late arrival (misses a deadline), two-leg journeys (for example MTC to Koyambedu then an intercity bus), and a waitlist position |
| Disruption dashboard | Affected / tentative / confirmed / boarded / unresolved, per-segment capacity with the buffer formula, unresolved demand by destination, re-plan diff |

**Closing the loop.** Chennai passengers board without tickets and rush the first vehicle, so a plan alone is not enough. Unreserved coaches and buses
are only allocated up to `nominal x buffer%`; conductors' load reports and second-chart vacancies are just more events; an overcrowded report displaces
whoever has no physical room and the plan is rebuilt (plan, observe, re-plan).

## Quick start

Needs Python 3.12 or newer (developed on 3.14) and a terminal. Commands work in PowerShell and bash.

```
pip install -r requirements.txt
python -m pytest -q                       # the whole suite (about a minute); any single test is aborted after 60 s
python scripts/run_demo.py                # plays the scripted demo against a real server it starts for you, checks every step
```

Run the API yourself:

```
cd backend
uvicorn safarset.api.app:app --reload     # http://127.0.0.1:8000  (interactive docs at /docs)
```

then, from another terminal (or use `/docs`):

```
curl -X POST localhost:8000/sim/load-scenario -H "content-type: application/json" -d '{"seed": 42}'
curl -X POST localhost:8000/sim/cancel-train           # proposes a plan; nothing is sent yet
curl localhost:8000/api/batches/pending                # the approval panel: diff categories and counts
curl -X POST localhost:8000/api/batches/B1/approve     # confirms the plan and sends the SMS (phone mock)
curl -X POST localhost:8000/sim/inject-overcrowd       # a conductor reports the first bus overcrowded
curl -X POST localhost:8000/sim/inject-vacancies       # second-chart vacancies appear on a train
curl localhost:8000/api/batches/pending                # the re-plan
```

`python scripts/run_demo.py --url http://127.0.0.1:8000` runs the demo against a server that is already up;
`--inprocess` needs no server; `--seed`, `--passengers` and `--json report.json` are also available. The exit code is 0 only if every check passes.

### Frontend (React)

Needs Node 20 or newer. One command starts the backend (:8000) and the Vite dev server (:5173, proxying `/api`, `/ws` and `/sim/*`):

```
python scripts/dev.py            # open http://localhost:5173  (add --load to load the seed-42 scenario)
```

Or by hand: `cd backend && uvicorn safarset.api.app:app` and, in `frontend/`, `npm install && npm run dev`.
Checks: `cd frontend && npm test && npx tsc -b && npm run build`. Design reference images: `frontend/design/` (visual reference only; sample data is outdated).

### The scripted demo

`GET /sim/timeline` lists it; `POST /sim/timeline/next` plays one step at a time (or `run_demo.py` plays all of them):

1. **Train cancelled at origin** (14:00). A plan is proposed automatically.
2. **Plan proposed for approval.** Unresolved demand is shown with ranked alternatives.
3. **Operator approves the plan.** Confirmed groups get an SMS (English or Tamil) with the journey and a short reason.
4. **Conductor reports a bus overcrowded.** Confirmed groups with no physical room are displaced; a re-plan is proposed. The operator is warned that they still hold the old SMS.
5. **Second-chart vacancies reported on a train.** The railway's final chart (prepared about 30 min before departure) shows berths now vacant.
6. **Re-plan proposed for approval.** Confirmed passengers stay frozen; the diff shows DISPLACED / NEWLY PLACED / RESHUFFLED with counts.
7. **Operator approves the re-plan.** Only changed groups are messaged.

Extra demo controls under `/sim/*` (not part of the product): load scenario (seed), cancel / delay a train, close a road, inject an overcrowding
report or second-chart vacancies, compliance and walk-on sliders, `POST /sim/depart/{vehicle}` (plan, observe, re-plan using the sliders: passengers
who ignore their allocation rush the earliest vehicle toward their destination), clock control.

## Real vs simulated

| Item | Status |
|---|---|
| Bus routes, stops and timings of the six MTC routes used (and a Koyambedu leg) | **REAL** structure from the community Chennai GTFS feed (mdb-3360). Its timings are templated per route, not observed |
| Train 12607 Lalbagh Express | **REAL, UNVERIFIED**: times from one public source; coach mix assumed. Not checked against NTES |
| Train 12639 Brindavan Express | **REAL, skipped**: sources conflict, times left empty |
| All other trains (the cancelled one and three alternates) | **SIMULATED**, modelled on Central-origin Arakkonam-line services |
| Per-coach seats (SL 72, 3A 64, CC 78, 2S 108), MTC 40 seated | Secondary public sources, not official documents |
| General coach 80, intercity bus 50 | **ESTIMATE** and **SIMULATED** (owner-approved) |
| Intercity buses to Vellore and Katpadi | **SIMULATED** (no real TNSTC/SETC data) |
| Passengers, groups, ages, destinations, deadlines, vacancies, phone numbers | **SIMULATED** from one seeded generator (phone numbers are deliberately invalid) |
| Conductor and TTE feeds | **SIMULATED** behind the same events a real integration would produce |
| Scenario shortage | **Tuned** for the demo. It is not a result and says nothing about real Chennai capacity |
| Tamil SMS text | **DRAFT**, needs a native speaker before any real use |

Provenance and data-quality findings: [data/real/SOURCES.md](data/real/SOURCES.md). Raw GTFS is not committed (git-ignored); the repo holds
small extracts. Licences: see [Data & licences](#data--licences).

## Data & licences

The **code** and the **data** in this repository have separate licences.

* **Data.** The bus extracts in `data/real/reference/` are derived from the community feed **UngalSoththu / ChennaiGTFS** and are offered under the
  **ODbL** with the attribution "UngalSoththu / ChennaiGTFS". Station coordinates are (c) OpenStreetMap contributors, ODbL. The MTC data inside the
  community feed was scraped with no stated terms, and **MTC's own terms are unverified**. Full statement, caveats and takedown note:
  [data/real/LICENSE.md](data/real/LICENSE.md). Redistributing these files, or a database derived from them, carries the ODbL attribution and share-alike duties.
* **Code.** The ODbL above does **not** cover the SafarSet source code. No code licence has been chosen yet, so by default all rights in the code are reserved by its authors.

## How it works

```
 sim feeds (ETM, TTE terminal)        operator UI / field view / phone mock
          \                                   |   REST + WebSocket
           v                                  v
        events (append-only log, the source of truth) ---> reducers ---> state tables (SQLite, DB-enforced invariants)
                                  ^                                            |
                                  |                                            v
                         Engine: apply event, re-plan  <---  allocator (score -> candidates -> segments) ---> plan batch (TENTATIVE)
                                                                                     | operator approves
                                                                                     v
                                                                  CONFIRMED + notifier (phone mock always, real SMS optional)
```

* **Append-only event log** is the source of truth and the audit trail; state is a projection written in the same transaction. Replaying the log into an empty
  database rebuilds identical state (tested, including clock moves). Refused commands are logged as `COMMAND_REJECTED` and hidden in the UI by default.
* **Database invariants**: `CHECK (used >= 0)`, `CHECK (used <= cap)`, triggers that keep `used` in step with allocations, legal status transitions,
  immutable allocation fields, one live allocation per group. The tests include a 3,000-step fuzz against an independent model.
* **Allocator** (`backend/safarset/domain/allocator.py`): groups are ordered by score; among candidates, arrivals within 15 min count as equal, then
  class step (same, upgrade, lower, unreserved), best fit, mode tier. Existing tentative placements are kept (stability); a **bounded reshuffle** may move a
  strictly lower-priority tentative group only if it is no worse off, within +15 min, and the move places strictly more people than it moves. Confirmed
  passengers move only if they physically cannot board.
* **Buffers** (`config/buffers.json`): reserved coaches use exact chart vacancy; unreserved coaches and buses are allocated up to `nominal x buffer%`.
  A buffer change never displaces a confirmed passenger.
* **Approval only**: a plan or re-plan is a pending batch; approval confirms it and sends the messages. A stale batch (capacity it relies on changed) can only be re-planned.
* **Notifier**: messages carry the new journey and a short reason (top priority factors, or a plain "why"), 2 SMS segments at most in English. Rule text is
  operator-only. The phone mock always works; real SMS is optional and off by default (see below).
* **Scoring is pluggable**: [docs/scoring_interface.md](docs/scoring_interface.md) lists the interface and the passenger fields the stub reads, for the real scorer.

## Configuration

| File or variable | What |
|---|---|
| `config/scoring_weights.json` | PLACEHOLDER weights for the stub scorer (operator-editable at runtime) |
| `config/buffers.json` | buffer % per mode (operator-editable at runtime) |
| `config/allocator.json` | check-in lead per mode (train 10, bus 30 min), walk speed, arrival tolerance (15), reshuffle limits. Read-only in the API |
| `config/class_rank.json` | class order for the upgrade / lower-class rule |
| `config/notifier.json` | `phone_mock_english_only` (show English only on the phone mock), `sms_allow_tamil` |
| `SAFARSET_PHONE_ENGLISH_ONLY`, `SAFARSET_SMS_ALLOW_TAMIL` | override the two switches (`1` / `0`) |
| `SAFARSET_SMS_ENABLED=1` plus `SAFARSET_SMS_URL`, `_API_KEY`, `_SENDER`, `_DLT_ENTITY_ID`, `_DLT_TEMPLATE_ID` | enable the optional real-SMS backend |

Real SMS to Indian numbers falls under TRAI DLT rules (registered sender, entity and templates), so it may not be usable in time. The backend never sends to
numbers that are not valid Indian mobiles (the demo numbers are not), never blocks approval when a gateway fails, and has only been tested against fakes.

## Repository layout

```
backend/safarset/   api/ (FastAPI, WebSocket)   domain/ (allocator, compat, diff, event loop)   events/ (types, reducers, apply, replay)
                    db/ (schema, invariants)    sim/ (generator, timeline, validation)          notify/ (templates en+ta, SMS backend)
                    scoring/ (interface + stub)
config/             editable rules                data/real/ and data/simulated/ (labelled)       docs/ (api.md, scoring_interface.md, messages.md)
scripts/            run_demo.py, generate_scenario.py, extract_bus_reference.py, render_sample_messages.py
tests/              pytest suite (rules, DB invariants, allocator, engine, API + WebSocket, notifier, demo)
```

Useful scripts: `python scripts/generate_scenario.py 42 300` writes a scenario JSON; `python scripts/render_sample_messages.py` regenerates `docs/messages.md`.

## API

REST under `/api` (operator, field, phone mock), demo controls under `/sim`, live stream `WS /ws`, per-phone stream `WS /ws/phone/{pnr}`.
Full contract for the React UIs: [docs/api.md](docs/api.md). Interactive docs at `/docs`.

## Known limitations

* The platform is a **single-process demo**: SQLite, one event loop, no authentication, no deployment setup. Real integrations with IRCTC/PRS/CRIS/MTC systems are out of scope.
* Only dispatched specials and alternate trains are allocatable; regular services appear as legs of multi-leg suggestions (which hold no seats).
* A reshuffle never unplaces anyone; a high-priority group can stay unresolved if its blocker cannot move without being worse off. The reason says which group blocks it.
* Passengers who ignore their plan and rush a vehicle are recorded as boarded there without a seat (the database cannot hold more people than capacity); the load report counts them.
* Rule weights are placeholders until the teammate's scorer is plugged in. Tamil needs review. Train timings need verified data (`data/real/trains.json` is swappable: set `verified: true` per train).

## Development

`python -m pytest -q` runs everything; `pytest-timeout` (60 s per test, set in `pyproject.toml`) makes a stuck WebSocket test fail instead of hanging. Work is committed at the end of every phase. The tests were also checked by mutation (breaking a constraint or rule on
purpose and confirming a test fails). Do not read the demo scenario's shortage as a finding: it is shaped to make the demo interesting.
