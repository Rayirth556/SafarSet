"""Phase 1: flatten selected MTC routes from the community Chennai GTFS feed into reference CSVs.

Source: https://github.com/ungalsoththu/ChennaiGTFS (MobilityDatabase mdb-3360), REAL data (community-built,
known validation errors; see data/real/SOURCES.md for the data-quality findings).

Usage: python -I scripts/extract_bus_reference.py <gtfs_dir> <out_dir>
"""
import collections
import csv
import json
import sys

# Routes chosen for the scenario (Chennai Central area -> near destinations, plus a Poonamallee->Tiruvallur transfer leg).
SELECTED = {
    "MTC-22836": "Poonamallee",   # 54       Royapuram terminus -> Poonamallee B.T
    "MTC-22798": "Poonamallee",   # 101CT    Royapuram -> Poonamallee Depot
    "MTC-23210": "Poonamallee",   # 101 R1   Thiruvottiyur -> Poonamallee
    "MTC-22758": "Avadi",         # 120 R1   Royapuram -> Avadi
    "MTC-22244": "Avadi",         # 150 R1   Royapuram -> Avadi B.T
    "MTC-22780": "Tiruvallur",    # 597A R   Poonamallee Terminus -> Thiruvallur Terminal (transfer leg)
    "MTC-23213": "Koyambedu",     # 101 CT7  Thiruvottriyur -> M.G.R.Koyambedu (leg 1 of MTC + TNSTC multi-leg)
}


def secs(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def hms(x):
    return f"{x // 3600:02d}:{x % 3600 // 60:02d}:{x % 60:02d}"


def rd(d, n):
    with open(f"{d}/{n}.txt", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main(gtfs_dir, out_dir):
    routes = {r["route_id"]: r for r in rd(gtfs_dir, "routes")}
    stops = {s["stop_id"]: s for s in rd(gtfs_dir, "stops")}
    trips = [t for t in rd(gtfs_dir, "trips") if t["route_id"] in SELECTED]
    trip_ids = {t["trip_id"] for t in trips}
    by_trip = collections.defaultdict(list)
    for r in rd(gtfs_dir, "stop_times"):
        if r["trip_id"] in trip_ids:
            by_trip[r["trip_id"]].append(r)
    for rows in by_trip.values():
        rows.sort(key=lambda r: int(r["stop_sequence"]))

    route_stops, trip_rows, used_stops = [], [], set()
    manifest = {}
    for rid in SELECTED:
        rtrips = [t for t in trips if t["route_id"] == rid]
        # Verify the route has ONE stop pattern and ONE offset template (so offsets can be stored once).
        templates = set()
        for t in rtrips:
            rows = by_trip[t["trip_id"]]
            t0 = secs(rows[0]["departure_time"])
            templates.add(tuple((r["stop_id"], secs(r["arrival_time"]) - t0, secs(r["departure_time"]) - t0) for r in rows))
        assert len(templates) == 1, f"{rid}: {len(templates)} distinct timing templates; cannot flatten to offsets"
        template = next(iter(templates))
        for seq, (sid, a, d) in enumerate(template, start=1):
            route_stops.append((rid, seq, sid, a, d))
            used_stops.add(sid)
        for t in sorted(rtrips, key=lambda t: secs(by_trip[t["trip_id"]][0]["departure_time"])):
            trip_rows.append((t["trip_id"], rid, t["service_id"], by_trip[t["trip_id"]][0]["departure_time"]))
        r = routes[rid]
        manifest[rid] = {"short_name": r["route_short_name"], "long_name": r["route_long_name"],
                         "serves": SELECTED[rid], "n_trips": len(rtrips), "n_stops": len(template),
                         "end_to_end_minutes": (template[-1][1]) / 60}

    write_csv(f"{out_dir}/bus_routes.csv",
              ["route_id", "short_name", "long_name", "serves_destination", "mode", "operator", "source"],
              [(rid, routes[rid]["route_short_name"], routes[rid]["route_long_name"], SELECTED[rid],
                "BUS", "MTC", "REAL:ChennaiGTFS(mdb-3360)") for rid in SELECTED])
    write_csv(f"{out_dir}/bus_stops.csv", ["stop_id", "stop_name", "lat", "lon", "source"],
              [(s, stops[s]["stop_name"], stops[s]["stop_lat"], stops[s]["stop_lon"], "REAL:ChennaiGTFS(mdb-3360)")
               for s in sorted(used_stops)])
    write_csv(f"{out_dir}/bus_route_stops.csv", ["route_id", "seq", "stop_id", "arr_offset_s", "dep_offset_s"], route_stops)
    write_csv(f"{out_dir}/bus_trips.csv", ["trip_id", "route_id", "service_id", "start_time"], trip_rows)
    with open(f"{out_dir}/bus_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(json.dumps(manifest, indent=2))
    print(f"routes={len(SELECTED)} stops={len(used_stops)} route_stops={len(route_stops)} trips={len(trip_rows)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
