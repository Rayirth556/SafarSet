"""Throw-away feasibility estimator for generated scenarios (NOT the real allocator, which is Phase 4).

Crude first-fit by group size: any pool on any ALLOCATION vehicle that serves the destination, wheelchair filter,
segment-wise capacity decrement. Ignores class rules, scores and times. Used only to check that a scenario has a
realistic shortfall (some unresolved demand) and that the numbers are sane.
"""
import copy


def crude_unplaced(sc):
    vehicles = [v for v in sc["vehicles"] if v["role"] == "ALLOCATION"]
    cap = {p["pool_id"]: [s["cap"] for s in p["segments"]] for v in vehicles for p in v["pools"]}
    unplaced = {}
    placed_heads = 0
    for g in sorted(sc["groups"], key=lambda g: (-g["size"], g["group_id"])):
        done = False
        for v in sorted(vehicles, key=lambda v: v["depart_min"]):
            if g["requirements"]["wheelchair"] and not v["attrs"]["wheelchair_accessible"]:
                continue
            b = v["boarding"]["stop_seq"]
            j = next((j for j in range(b + 1, len(v["stops"])) if g["dest_place"] in v["stops"][j]["serves_places"]), None)
            if j is None:
                continue
            for p in v["pools"]:
                c = cap[p["pool_id"]]
                if min(c[b:j]) >= g["size"]:
                    for i in range(b, j):
                        c[i] -= g["size"]
                    placed_heads += g["size"]
                    done = True
                    break
            if done:
                break
        if not done:
            unplaced[g["dest_place"]] = unplaced.get(g["dest_place"], 0) + g["size"]
    return placed_heads, unplaced
