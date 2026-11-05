# Real data: sources and findings (Phase 1, retrieved 2026-11-05)

Everything in `data/real/` is REAL (or real-ish from secondary sources) unless a file says otherwise.
Simulated data lives in `data/simulated/` (Phase 2) and is labelled SIMULATED.

## 1. Bus routes and stops: community Chennai GTFS
- URL: https://raw.githubusercontent.com/ungalsoththu/ChennaiGTFS/main/data/chennai-unified-gtfs.zip (9.8 MB; MobilityDatabase mdb-3360).
- Publisher: "Ithu Ungal Soththu", feed_version 0.2.0, `feed_start_date`/`feed_end_date` are BLANK.
- Tables present: agency, calendar, calendar_dates, fare_attributes, fare_rules, feed_info, pathways, routes, shapes, stop_times, stops, transfers, trips.
- **It has real `stop_times`**: 1,389,081 rows; 1,360,443 MTC, 16,135 Southern Railway suburban, 12,503 CMRL.
- Agencies: MTC (4,611 routes / 47,047 trips), CMRL metro (28 / 625), Southern Railway "SRR" (763 routes / 763 trips).
- Checks I ran on the 47,047 MTC trips: every trip has stop_times; times never decrease; no stop repeats within a trip. I did NOT run the official GTFS validator, so the feed's known validation errors are not itemised here.

Data-quality caveats (important for the pitch and for Phase 2):
1. **Timings are templated, not observed.** `arrival_time == departure_time` at every stop of every MTC trip, and every trip of a route has the identical end-to-end duration (e.g. route 54: all 91 trips take 74 min). Treat as schedule-like estimates.
2. **No day or season variation**: 46,973 of 47,047 MTC trips use one service `MTC-Regular` (every day, 2024-2030). Only 74 use `MTC-HSC`.
3. Times can pass midnight (hours up to 25).
4. **Southern Railway data is suburban only** (MSB-TBM style lines). No long-distance trains. No Katpadi, Vellore, Jolarpettai or Walajah stops. Arakkonam Jn exists as a suburban stop.
5. **No intercity buses (TNSTC/SETC)** are in the feed.

Routes selected (flattened by `scripts/extract_bus_reference.py` into `data/real/reference/bus_*.csv`):

| route_id | name | serves | trips | stops | end-to-end |
|---|---|---|---|---|---|
| MTC-22836 | 54 Royapuram terminus to Poonamallee B.T | Poonamallee | 91 | 46 | 74 min |
| MTC-22798 | 101CT Royapuram to Poonamallee Depot | Poonamallee | 100 | 35 | 59 min |
| MTC-23210 | 101 R1 Thiruvottiyur to Poonamallee | Poonamallee | 119 | 55 | 84 min |
| MTC-22758 | 120 R1 Royapuram to Avadi | Avadi | 44 | 50 | 67 min |
| MTC-22244 | 150 R1 Royapuram to Avadi B.T | Avadi | 4 | 53 | 73 min |
| MTC-22780 | 597A R Poonamallee Terminus to Thiruvallur Terminal | Tiruvallur (transfer leg) | 95 | 33 | 43 min |

Boarding points near Chennai Central:
- Poonamallee routes pass "Mgr Central Or Rajiv Gandhi Government General Hospital" (0.16 km from the station).
- Avadi routes pass **Park Station** (0.32 km), not a stop named for Central.
- **No MTC route in the feed runs from the Central area directly to Tiruvallur.** Tiruvallur is reachable only as a two-leg journey (route 54/101CT to Poonamallee, then 597A R). This fits the "multi-leg alternative" feature.

## 2. Trains: NOT complete (owner input needed)
- `trains.json` holds 2 drafted trains (12607 Lalbagh Exp, 12639 Brindavan Exp), both `timings_verified: false`.
- 12607 times are from one Wikipedia table. For 12639 the sources conflict (Arakkonam arrival 08:33 vs 08:48; MAS departure 07:40 vs 07:50), so intermediate times are null.
- Official source would be NTES/IRCTC, which cannot be fetched statically. I did not scrape aggregator sites.
- Sites consulted via search summaries only: Wikipedia (Brindavan Express, Lal Bagh Express) and aggregator snippets (indiarailinfo, travelkhana, cleartrip).

## 3. Capacities: see `capacities.json`
- Rail coach capacities: secondary sources only (railmitra, erail, Wikipedia mirrors). Ranges reflect ICF vs LHB.
- Bus capacities: conflicting or missing. See file.

## 4. Intercity buses (Vellore/Katpadi)
- Search found TNSTC listed by booking aggregators (MakeMyTrip) for Chennai-Vellore plus many private operators. **SETC service to Vellore was not confirmed.** The CMBT Koyambedu to Vellore route appears served by TNSTC; no official timetable obtained.
- Also note: these buses depart from Koyambedu CMBT, not Chennai Central.

## 5. Station coordinates
- OSM via Nominatim: `reference/stations.json`. Katpadi, Walajah Road and Ambur are unresolved.
- Bus stop coordinates come from the GTFS `stops.txt`.

## 6. Mentioned only (not downloaded)
- OpenCity "Chennai MTC performance data" (yearly aggregates; pitch numbers only).
- `bigomega/chennai-mtc-ui` 2012-era route data.
- Inactive OSM Chennai bus-route project.
