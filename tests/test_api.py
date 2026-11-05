"""HTTP + WebSocket contract tests for the four UI surfaces. Assertions check structure and rules, not how large the
(tuned) shortage is."""
import pytest
from fastapi.testclient import TestClient

from safarset.api.app import create_app


@pytest.fixture()
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def loaded(client):
    r = client.post("/sim/load-scenario", json={"seed": 42})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture()
def cancelled(loaded):
    r = loaded.post("/sim/cancel-train")
    assert r.status_code == 200 and r.json()["batch_id"] == "B1"
    return loaded


@pytest.fixture()
def approved(cancelled):
    assert cancelled.post("/api/batches/B1/approve").status_code == 200
    return cancelled


def get(c, url, **kw):
    r = c.get(url, **kw)
    assert r.status_code == 200, f"{url}: {r.status_code} {r.text}"
    return r.json()


def error(r, status, kind=None):
    assert r.status_code == status, r.text
    d = r.json()["detail"]
    assert d["error"]
    if kind:
        assert d["kind"] == kind
    return d


# ================================================================================================ basics
def test_everything_needs_a_scenario_first(client):
    assert client.get("/health").json() == {"ok": True, "scenario_loaded": False, "clients": 0}
    for url in ("/api/kpis", "/api/capacity", "/api/passengers", "/api/rules", "/api/field/vehicles"):
        error(client.get(url), 409, "NoScenario")
    error(client.post("/sim/cancel-train"), 409, "NoScenario")


def test_load_scenario_and_idle_dashboard(loaded):
    state = get(loaded, "/api/state")
    assert state["loaded"] and state["banner"]["active"] is False and state["clock"] == "14:00"
    k = get(loaded, "/api/kpis")
    assert k["affected"] == {"groups": 0, "heads": 0} and k["unresolved"]["heads"] == 0
    error(loaded.post("/sim/load-scenario", json={"seed": 1, "pct_senior": 7}), 422)           # request validation
    error(loaded.post("/sim/load-scenario", json={"seed": 1, "cancel_time": "16:00"}), 422, "InvalidScenario")


def test_cors_allows_the_react_dev_server(loaded):
    r = loaded.get("/api/kpis", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "*"


# ================================================================================================ operator dashboard
def test_disruption_banner_kpis_and_pending_batch(cancelled):
    state = get(cancelled, "/api/state")
    assert state["banner"]["active"] and "Train cancelled: TRAIN-SIM-CXL" in state["banner"]["title"]
    k = get(cancelled, "/api/kpis")
    assert k["affected"]["heads"] == 300 == k["tentative"]["heads"] + k["unresolved"]["heads"]
    assert k["confirmed"]["heads"] == 0 and k["boarded"]["heads"] == 0
    b = get(cancelled, "/api/batches/pending")
    assert b["batch_id"] == "B1" and b["status"] == "PROPOSED" and b["cause"] == "TRAIN_CANCELLED" and b["stale"] is False
    assert set(b["diff"]) == {"DISPLACED", "NEWLY_PLACED", "RESHUFFLED", "PLACED", "UNRESOLVED"}
    assert b["diff"]["NEWLY_PLACED"]["heads"] == k["tentative"]["heads"] and b["diff"]["UNRESOLVED"]["heads"] == k["unresolved"]["heads"]
    first = b["items"]["NEWLY_PLACED"][0]
    assert {"group_id", "pnr", "size", "class", "dest_name", "detail"} <= set(first)


def test_capacity_per_segment_with_buffer_formula_and_flags(cancelled):
    vehicles = get(cancelled, "/api/capacity")
    assert vehicles and all(v["role"] == "ALLOCATION" for v in vehicles)
    bus = next(v for v in vehicles if v["vehicle_id"] == "BUS-SPL-02")
    pool = bus["pools"][0]
    assert pool["formula"] == "40 × 75% = 30" and pool["buffer_pct"] == 0.75 and pool["nominal"] == 40
    seg = pool["segments"][0]
    assert {"from_stop", "to_stop", "cap", "confirmed", "tentative", "boarded", "free"} <= set(seg)
    assert seg["cap"] == seg["confirmed"] + seg["boarded"] + seg["tentative"] + seg["free"] and seg["free"] >= 0
    train = next(v for v in vehicles if v["mode"] == "TRAIN")
    assert any(p["kind"] == "RESERVED" and "exact vacancy" in p["formula"] for p in train["pools"])
    assert any(p["kind"] == "UNRESERVED" and "×" in p["formula"] for p in train["pools"])
    assert len(get(cancelled, "/api/capacity?role=all")) > len(vehicles)
    error(cancelled.get("/api/capacity?role=nonsense"), 422)


def test_passenger_table_and_why_panel(cancelled):
    page = get(cancelled, "/api/passengers?limit=20")
    assert page["total"] == 233 and len(page["items"]) == 20
    ranks = [p["rank"] for p in page["items"]]
    assert ranks == sorted(ranks) and ranks[0] == 1                                  # sorted by priority
    p = page["items"][0]
    assert p["score"] == sum(pts for _, pts in p["score_breakdown"]) and p["state"] in ("TENTATIVE", "UNRESOLVED")
    assert get(cancelled, "/api/passengers?status=TENTATIVE")["total"] == len([x for x in get(cancelled, "/api/passengers")["items"] if x["state"] == "TENTATIVE"])
    assert get(cancelled, "/api/passengers?dest=AVADI")["total"] > 0
    assert all(i["dest_place"] == "AVADI" for i in get(cancelled, "/api/passengers?dest=AVADI")["items"])
    tentative = next(i for i in get(cancelled, "/api/passengers?status=TENTATIVE")["items"])
    why = get(cancelled, f"/api/passengers/{tentative['group_id']}/why")
    assert why["state"] == "TENTATIVE" and why["rank"] == tentative["rank"] and why["of"] == 233
    assert why["score"]["breakdown"] and why["reason"]["chosen"]["vehicle_id"] and why["decision_text"].startswith("Priority rank")
    assert why["history"][0]["status"] == "TENTATIVE"
    un = next(i for i in get(cancelled, "/api/passengers?status=UNRESOLVED")["items"])
    why = get(cancelled, f"/api/passengers/{un['group_id']}/why")
    assert why["unresolved"]["reason"]["primary_cause"] and why["unresolved"]["alternatives"][-1]["type"] == "WAITLIST"
    error(cancelled.get("/api/passengers/NOPE/why"), 404, "NotFound")


def test_unresolved_demand_grouped_by_destination_with_ranked_alternatives(cancelled):
    groups = get(cancelled, "/api/unresolved")
    assert sum(g["heads"] for g in groups) == get(cancelled, "/api/kpis")["unresolved"]["heads"]
    assert [g["dest_place"] for g in groups] == sorted(g["dest_place"] for g in groups)
    for g in groups:
        assert g["heads"] == sum(i["size"] for i in g["items"])
        for item in g["items"]:
            assert item["reason"]["text"] and [a["rank"] for a in item["alternatives"]] == list(range(1, len(item["alternatives"]) + 1))
            assert item["alternatives"][-1]["type"] == "WAITLIST"


def test_approval_confirms_notifies_and_cannot_repeat(cancelled):
    pending = get(cancelled, "/api/batches/pending")
    r = cancelled.post("/api/batches/B1/approve")
    body = r.json()
    assert r.status_code == 200 and body["confirmed_groups"] == pending["allocations"]["tentative"]["groups"] == body["notified_groups"]
    k = get(cancelled, "/api/kpis")
    assert k["tentative"]["heads"] == 0 and k["confirmed"]["heads"] == pending["allocations"]["tentative"]["heads"]
    assert get(cancelled, "/api/batches/pending") is None
    d = error(cancelled.post("/api/batches/B1/approve"), 409)
    assert "not pending" in d["error"]
    error(cancelled.post("/api/batches/NOPE/approve"), 409)
    assert [b["status"] for b in get(cancelled, "/api/batches")] == ["APPROVED"]


def test_rules_view_and_editing(approved):
    rules = get(approved, "/api/rules")
    assert set(rules["weights"]) == {"medical_disability", "senior_60_plus", "child_or_pregnant", "hard_deadline", "reserved_pnr", "ageing_per_hour"}
    assert rules["buffers"]["MTC_BUS"]["example"] == "40 × 75% = 30" and rules["class_rank"] == ["UR", "2S", "SL", "CC", "3A", "2A", "1A"]
    assert rules["config"]["min_checkin_min"] == {"TRAIN": 10, "BUS": 30} and rules["editable"]["config"] is False
    # weights: exact keys required
    error(approved.put("/api/rules", json={"weights": {"senior_60_plus": 1}}), 422, "InvalidWeights")
    new = dict(rules["weights"], senior_60_plus=77)
    assert approved.put("/api/rules", json={"weights": new}).json()["weights"]["senior_60_plus"] == 77
    assert get(approved, "/api/rules")["weights_version"] == 1 and get(approved, "/api/rules")["weights_source"] == "operator"
    # buffers: never below confirmed + boarded (owner rule 7) -> 409 with a message, nothing changed
    busy = max((p for v in get(approved, "/api/capacity") for p in v["pools"] if p["buffer_mode"] == "MTC_BUS"),
               key=lambda p: max(s["confirmed"] for s in p["segments"]))
    firm = max(s["confirmed"] for s in busy["segments"])
    assert firm > 0
    d = error(approved.put("/api/rules", json={"buffers": {"MTC_BUS": round((firm - 1) / 40, 3)}}), 409, "BufferRejected")
    assert "never displaced by a settings change" in d["error"]
    assert get(approved, "/api/rules")["buffers"]["MTC_BUS"]["buffer_pct"] == 0.75
    assert approved.put("/api/rules", json={"buffers": {"MTC_BUS": 0.9}}).json()["buffers"]["MTC_BUS"]["example"] == "40 × 90% = 36"
    error(approved.put("/api/rules", json={"buffers": {"NO_SUCH_MODE": 0.5}}), 409)


def test_adjust_weights_and_rerun_creates_a_labelled_batch(cancelled):
    w = get(cancelled, "/api/rules")["weights"]
    r = cancelled.post("/api/replan", json={"weights": dict(w, senior_60_plus=5000)}).json()
    assert r["cause"] == "WEIGHTS_RERUN"
    b = get(cancelled, "/api/batches/pending")
    assert b["batch_id"] == r["batch_id"] and b["cause"] == "WEIGHTS_RERUN"
    assert get(cancelled, f"/api/batches/B1")["status"] == "SUPERSEDED"
    error(cancelled.post("/api/replan", json={"weights": {"x": 1}}), 422, "InvalidWeights")
    plain = cancelled.post("/api/replan", json={}).json()
    assert plain["cause"] == "MANUAL_REPLAN" and get(cancelled, "/api/batches/pending")["cause"] == "MANUAL_REPLAN"


def test_event_log_hides_rejected_commands_by_default(approved):
    error(approved.put("/api/rules", json={"buffers": {"NO_SUCH_MODE": 0.5}}), 409)
    shown = get(approved, "/api/events?limit=2000")
    assert shown["hide_rejected"] is True and "COMMAND_REJECTED" not in {e["type"] for e in shown["events"]}
    everything = get(approved, "/api/events?hide_rejected=false&limit=2000")
    assert "COMMAND_REJECTED" in {e["type"] for e in everything["events"]}
    assert all(e["rejected"] == (e["type"] == "COMMAND_REJECTED") for e in everything["events"])
    first = shown["events"][0]
    assert first["type"] == "SCENARIO_LOADED" and first["payload"]["scenario"]["groups"] == 233        # summarised, not 1 MB
    assert [e["seq"] for e in get(approved, "/api/events?after=3&limit=2")["events"]] == [e["seq"] for e in shown["events"] if e["seq"] > 3][:2]
    latest = get(approved, "/api/events?hide_rejected=false&tail=true&limit=3")["events"]          # the newest three, oldest first
    assert [e["seq"] for e in latest] == [e["seq"] for e in everything["events"]][-3:] and latest[-1]["type"] == "COMMAND_REJECTED"


def test_operator_override_needs_a_reason_and_shows_in_the_plan(approved):
    confirmed = next(i for i in get(approved, "/api/passengers?status=CONFIRMED")["items"])
    gid = confirmed["group_id"]
    error(approved.post(f"/api/groups/{gid}/override", json={"action": "UNASSIGN", "reason": " "}), 409)
    r = approved.post(f"/api/groups/{gid}/override", json={"action": "UNASSIGN", "reason": "operator removed the group from this vehicle"})
    assert r.status_code == 200
    b = get(approved, "/api/batches/pending")
    item = next(i for i in b["items"]["DISPLACED"] if i["group_id"] == gid)
    assert item["detail"]["old_sms_still_held"] is True and item["detail"]["cause"] == "OPERATOR_OVERRIDE"
    why = get(approved, f"/api/passengers/{gid}/why")
    assert why["held_by_operator"]["why"].startswith("operator removed") and why["state"] == "UNRESOLVED"
    assert get(approved, "/api/kpis")["held_by_operator"]["groups"] == 1
    assert approved.post(f"/api/groups/{gid}/override", json={"action": "RESUME_AUTO", "reason": "back to automatic planning"}).status_code == 200
    error(approved.post(f"/api/groups/NOPE/override", json={"action": "UNASSIGN", "reason": "does not exist"}), 409)


# ================================================================================================ field view
def test_field_view_manifest_boarding_and_load_report(approved):
    vehicles = get(approved, "/api/field/vehicles")
    assert vehicles and {"vehicle_id", "depart", "pools", "boarding_note"} <= set(vehicles[0])
    vid = next(v["vehicle_id"] for v in vehicles if v["vehicle_id"].startswith("BUS-SPL") and get(approved, f"/api/field/vehicles/{v['vehicle_id']}/manifest")["expected_heads"] > 0)
    m = get(approved, f"/api/field/vehicles/{vid}/manifest")
    assert m["boarded_heads"] == 0 and all(p["can_board"] for p in m["passengers"])
    one = m["passengers"][0]
    r = approved.post(f"/api/field/vehicles/{vid}/board", json={"allocation_id": one["allocation_id"]})
    assert r.status_code == 200
    m = get(approved, f"/api/field/vehicles/{vid}/manifest")
    assert m["boarded_heads"] == one["size"] and m["passengers"][0]["status"] == "BOARDED"
    error(approved.post(f"/api/field/vehicles/{vid}/board", json={"allocation_id": one["allocation_id"]}), 409)       # already boarded
    error(approved.post(f"/api/field/vehicles/{vid}/board", json={}), 422)
    error(approved.post("/api/field/vehicles/NOPE/board", json={"allocation_id": 1}), 404)
    # conductor reports the bus overcrowded (no count: treated as exactly full) -> unboarded confirmed groups are displaced
    r = approved.post(f"/api/field/vehicles/{vid}/load-report", json={"level": "OVERCROWDED"}).json()
    assert r["pool_id"].endswith(":UR")
    cap = next(v for v in get(approved, "/api/capacity") if v["vehicle_id"] == vid)["pools"][0]
    assert cap["field_report"]["level"] == "OVERCROWDED"
    m = get(approved, f"/api/field/vehicles/{vid}/manifest")
    assert all(p["status"] == "BOARDED" for p in m["passengers"])                                                    # only boarded remain
    b = get(approved, "/api/batches/pending")
    assert b is None or b["cause"] == "LOAD_REPORT"
    error(approved.post(f"/api/field/vehicles/{vid}/load-report", json={"level": "PANIC"}), 422)


def test_tte_vacancy_update(approved):
    v = next(v for v in get(approved, "/api/capacity") if v["mode"] == "TRAIN" and any(p["kind"] == "RESERVED" for p in v["pools"]))
    pool = next(p for p in v["pools"] if p["kind"] == "RESERVED")
    r = approved.post(f"/api/field/vehicles/{v['vehicle_id']}/vacancy", json={"pool_id": pool["pool_id"], "from_seg": 0, "to_seg": 1, "vacancy": pool["segments"][0]["cap"] + 1})
    assert r.status_code == 200
    seg = next(p for vv in get(approved, "/api/capacity") for p in vv["pools"] if p["pool_id"] == pool["pool_id"])["segments"][0]
    assert seg["cap"] == pool["segments"][0]["cap"] + 1
    error(approved.post(f"/api/field/vehicles/{v['vehicle_id']}/vacancy", json={"pool_id": pool["pool_id"], "from_seg": 0, "to_seg": 1, "vacancy": 10 ** 6}), 409)


# ================================================================================================ phone mock
def test_phone_mock_receives_messages_only_after_approval(cancelled):
    pnr = next(i["pnr"] for i in get(cancelled, "/api/passengers?status=TENTATIVE")["items"] if i["pnr"])
    assert get(cancelled, f"/api/phone/{pnr}/messages")["messages"] == []                  # proposed, not approved: nothing sent
    cancelled.post("/api/batches/B1/approve")
    msgs = get(cancelled, f"/api/phone/{pnr}/messages")
    assert len(msgs["messages"]) == 1 and msgs["pnr"] == pnr
    m = msgs["messages"][0]
    assert "Reason:" in m["message"] or "காரணம்:" in m["message"]
    assert m["channel"] == "PHONE_MOCK" and m["reason"]
    group = next(i for i in get(cancelled, "/api/passengers")["items"] if i["pnr"] == pnr)["group_id"]
    assert get(cancelled, f"/api/phone/{group}/messages")["messages"] == msgs["messages"]  # addressable by group id too
    error(cancelled.get("/api/phone/NOPE/messages"), 404, "NotFound")


# ================================================================================================ demo controls
def test_sim_delay_close_road_overcrowd_noshows_and_params(approved):
    r = approved.post("/sim/delay-train", json={"vehicle_id": "TRAIN-SIM-ALT-2", "delay_min": 45}).json()
    assert "seq" in r
    assert "Delay: TRAIN-SIM-ALT-2 +45 min" in [i["text"] for i in get(approved, "/api/state")["banner"]["items"]]
    assert next(v for v in get(approved, "/api/capacity") if v["vehicle_id"] == "TRAIN-SIM-ALT-2")["delay_min"] == 45
    approved.post("/sim/close-road", json={"route_id": "MTC-23213", "description": "waterlogging"})
    assert any("Road closure: waterlogging" in i["text"] for i in get(approved, "/api/state")["banner"]["items"])
    r = approved.post("/sim/inject-overcrowd").json()                                         # scripted defaults
    assert "LOAD_REPORT" in [e["type"] for e in get(approved, "/api/events?tail=true&limit=6")["events"]]
    r = approved.post("/sim/inject-noshows", json={"vehicle_id": "TRAIN-SIM-ALT-1", "seats": 3}).json()
    assert "seq" in r
    error(approved.post("/sim/inject-noshows", json={"vehicle_id": "BUS-SPL-01"}), 422)       # a bus has no reserved pool
    assert get(approved, "/sim/params") == {"compliance_rate": 0.8, "walkon_rate": 0.3}
    assert approved.put("/sim/params", json={"compliance_rate": 0.5}).json() == {"compliance_rate": 0.5, "walkon_rate": 0.3}
    error(approved.put("/sim/params", json={"walkon_rate": 3}), 422)
    assert approved.post("/sim/clock", json={"to_min": 905}).json()["clock"] == "15:05"
    assert get(approved, "/api/state")["clock"] == "15:05"


def depart_everything(c, compliance, walkon):
    """Approve the first plan, set the sliders, then depart every allocatable vehicle in departure order."""
    c.post("/sim/load-scenario", json={"seed": 42})
    c.post("/sim/cancel-train")
    c.post("/api/batches/B1/approve")
    c.put("/sim/params", json={"compliance_rate": compliance, "walkon_rate": walkon})
    out = {}
    for v in sorted(get(c, "/api/field/vehicles"), key=lambda v: (v["depart"], v["vehicle_id"])):
        out[v["vehicle_id"]] = c.post(f"/sim/depart/{v['vehicle_id']}").json()
    return out


def overload(out):
    return {vid: r["load_report"]["count"] - r["load_report"]["nominal"] for vid, r in out.items() if r["load_report"]}


def test_full_compliance_and_no_walkons_never_overcrowds_and_nobody_vanishes(client):
    out = depart_everything(client, 1.0, 0.0)
    assert all(r["load_report"]["level"] != "OVERCROWDED" for r in out.values() if r["load_report"])
    assert all(r["rusher_groups"] == [] and r["refused_groups"] == [] for r in out.values())
    k = get(client, "/api/kpis")
    assert k["tentative"]["heads"] + k["confirmed"]["heads"] + k["boarded"]["heads"] + k["unresolved"]["heads"] == k["affected"]["heads"] == 300
    assert k["boarded"]["heads"] > 0


def test_compliance_slider_at_70_percent_overcrowds_vehicles_through_rushers(client):
    """Ignorers board the earliest-departing vehicle toward their destination and add to its load: with walk-ons switched
    off, the rushers alone push some vehicle past its seats, and the field report flags it."""
    out = depart_everything(client, 0.7, 0.0)
    crowded = {vid: r for vid, r in out.items() if r["load_report"] and r["load_report"]["level"] == "OVERCROWDED"}
    assert crowded, "70% compliance must produce at least one OVERCROWDED-worthy load"
    for vid, r in crowded.items():
        lr = r["load_report"]
        assert lr["rushers_heads"] > 0 and lr["count"] == lr["committed"] + lr["rushers_heads"] + lr["allocated_heads"] > lr["nominal"]
        pool = next(p for v in get(client, "/api/capacity") if v["vehicle_id"] == vid for p in v["pools"] if p["pool_id"] == lr["pool_id"])
        assert pool["field_report"]["level"] == "OVERCROWDED" and pool["field_report"]["count"] == lr["count"]


def test_compliance_and_walkons_compare_against_perfect_compliance_with_the_same_walkons(client):
    default_walkons = overload(depart_everything(client, 1.0, 0.3))
    ignoring = overload(depart_everything(client, 0.7, 0.3))
    assert any(v > 0 for v in ignoring.values())                                         # OVERCROWDED-worthy at 70%
    assert any(ignoring[vid] > default_walkons[vid] for vid in ignoring)                  # the ignorers add to some vehicle's load


def test_ignorers_never_vanish_they_board_somewhere_and_free_their_old_seat(client):
    out = depart_everything(client, 0.7, 0.0)
    rushers = {g: vid for vid, r in out.items() for g in r["rusher_groups"]}
    assert rushers
    assert len(rushers) == sum(len(r["rusher_groups"]) for r in out.values())            # nobody boards twice
    for gid, vid in list(rushers.items())[:15]:
        why = get(client, f"/api/passengers/{gid}/why")
        assert why["state"] == "BOARDED" and why["boarded_on_own"] == vid and why["allocation"] is None
        released = [h for h in why["history"] if h["status"] == "RELEASED"]
        assert released and released[-1]["status_reason"]["cause"] == "SELF_BOARDED" and released[-1]["status_reason"]["vehicle_id"] == vid
    k = get(client, "/api/kpis")
    assert k["tentative"]["heads"] + k["confirmed"]["heads"] + k["boarded"]["heads"] + k["unresolved"]["heads"] == k["affected"]["heads"] == 300
    error(client.post("/sim/depart/NOPE"), 404)


def test_rushed_vehicles_displace_the_groups_refused_at_the_door_and_replan_them(client):
    out = depart_everything(client, 0.7, 0.3)
    refused = [(vid, g) for vid, r in out.items() for g in r["refused_groups"]]
    assert refused
    for vid, gid in refused[:10]:
        why = get(client, f"/api/passengers/{gid}/why")
        assert why["state"] != "CONFIRMED" and any(h["status"] == "DISPLACED" for h in why["history"]) or why["state"] in ("TENTATIVE", "BOARDED")


def test_scripted_timeline_can_be_played_step_by_step_and_reset(loaded):
    t = get(loaded, "/sim/timeline")
    assert t["total"] == 7 and t["next_step"] == 0 and [s["type"] for s in t["steps"]][0] == "TRAIN_CANCELLED"
    played = []
    for n in range(7):
        r = loaded.post("/sim/timeline/next")
        assert r.status_code == 200, r.text
        played.append(r.json()["played"]["type"])
        assert get(loaded, "/api/state")["clock"] == t["steps"][n]["at"]
    assert played == [s["type"] for s in t["steps"]]
    assert get(loaded, "/api/batches/pending") is None and get(loaded, "/api/kpis")["confirmed"]["heads"] > 0
    error(loaded.post("/sim/timeline/next"), 409, "TimelineDone")
    assert loaded.post("/sim/timeline/reset").json() == {"next_step": 0}
    assert get(loaded, "/api/kpis")["affected"]["heads"] == 0


# ================================================================================================ WebSocket
def drain(ws, until_type="invalidate"):
    msgs = []
    while True:
        m = ws.receive_json()
        msgs.append(m)
        if m["type"] == until_type:
            return msgs


def test_websocket_pushes_snapshot_then_events_kpis_and_invalidate_hints(loaded):
    with loaded.websocket_connect("/ws") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot" and snap["loaded"] and snap["kpis"]["affected"]["heads"] == 0 and snap["pending_batch"] is None
        last = snap["last_seq"]
        loaded.post("/sim/cancel-train")
        msgs = drain(ws)
        types = [m["type"] for m in msgs]
        assert types[-2:] == ["kpis", "invalidate"] and set(types[:-2]) == {"event"}
        seqs = [m["seq"] for m in msgs if m["type"] == "event"]
        assert seqs == list(range(last + 1, last + 1 + len(seqs)))                          # contiguous: clients can detect gaps
        assert [m["event"]["type"] for m in msgs if m["type"] == "event"] == ["TRAIN_CANCELLED", "PLAN_PROPOSED"]
        kp = msgs[-2]
        assert kp["kpis"]["affected"]["heads"] == 300 and kp["last_seq"] == seqs[-1]
        topics = msgs[-1]["topics"]
        assert {"banner", "capacity", "passengers", "unresolved", "batch", "kpis"} <= set(topics) and msgs[-1]["last_seq"] == seqs[-1]
        # ping / on-demand snapshot
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong", "last_seq": seqs[-1]}
        ws.send_json({"type": "snapshot"})
        assert ws.receive_json()["pending_batch"]["batch_id"] == "B1"


def test_websocket_rejections_are_flagged_so_the_ui_can_hide_them(approved):
    with approved.websocket_connect("/ws") as ws:
        ws.receive_json()
        error(approved.put("/api/rules", json={"buffers": {"NO_SUCH_MODE": 0.5}}), 409)
        ev = ws.receive_json()
        assert ev["type"] == "event" and ev["event"]["type"] == "COMMAND_REJECTED" and ev["event"]["rejected"] is True


def test_websocket_announces_a_scenario_reset(loaded):
    with loaded.websocket_connect("/ws") as ws:
        ws.receive_json()
        loaded.post("/sim/load-scenario", json={"seed": 7, "n_passengers": 60})
        m = ws.receive_json()
        assert m["type"] == "reset" and m["kpis"]["affected"]["heads"] == 0 and m["loaded"]


def test_phone_websocket_delivers_only_that_passengers_sms(cancelled):
    tentative = [i for i in get(cancelled, "/api/passengers?status=TENTATIVE")["items"] if i["pnr"]]
    mine, other = tentative[0]["pnr"], tentative[1]["pnr"]
    with cancelled.websocket_connect(f"/ws/phone/{mine}") as phone, cancelled.websocket_connect(f"/ws/phone/{other}") as other_phone:
        assert phone.receive_json() == {"type": "history", "found": True, "group_id": tentative[0]["group_id"], "pnr": mine, "messages": []}
        other_phone.receive_json()
        cancelled.post("/api/batches/B1/approve")
        sms = phone.receive_json()
        assert sms["type"] == "sms" and sms["group_id"] == tentative[0]["group_id"] and ("Reason:" in sms["message"] or "காரணம்:" in sms["message"]) and sms["channel"] == "PHONE_MOCK"
        sms2 = other_phone.receive_json()
        assert sms2["group_id"] == tentative[1]["group_id"] and sms2["message"] != sms["message"]
    with cancelled.websocket_connect(f"/ws/phone/{mine}") as late:
        h = late.receive_json()                                                             # a phone that connects later sees its history
        assert h["type"] == "history" and len(h["messages"]) == 1
    with cancelled.websocket_connect("/ws/phone/UNKNOWN") as ghost:
        assert ghost.receive_json()["found"] is False


# ================================================================================================ replay with clock changes
def test_replay_gives_identical_state_when_the_clock_was_moved(client):
    from safarset.db.conn import new_db
    from safarset.db.invariants import state_dump
    from safarset.domain.loop import Engine
    from safarset.events.apply import replay
    client.post("/sim/load-scenario", json={"seed": 42})
    client.post("/sim/clock", json={"to_min": 850})
    for _ in range(3):                                                    # cancel, plan, approve (each step moves the clock)
        assert client.post("/sim/timeline/next").status_code == 200
    client.post("/sim/clock", json={"to_min": 880})
    client.post("/sim/inject-overcrowd")
    client.post("/sim/clock", json={"to_min": 900})                       # a clock move with no event after it
    st = client.app.state.safar
    assert [e["type"] for e in get(client, "/api/events?hide_rejected=false&limit=2000")["events"] if e["type"] == "CLOCK_SET"]
    fresh = new_db()
    replay(st.conn, fresh)
    assert state_dump(fresh) == state_dump(st.conn)
    restored = Engine.restore(fresh)
    assert restored.clock == st.engine.clock == 900                         # the clock itself survives a rebuild from the log


def test_clock_moves_are_logged_events_with_scenario_time(loaded):
    loaded.post("/sim/clock", json={"to_min": 905})
    ev = get(loaded, "/api/events?tail=true&limit=1")["events"][-1]
    assert ev["type"] == "CLOCK_SET" and ev["payload"] == {"to_min": 905} and ev["ts_sim"] == 905 and ev["actor"] == "sim"


# ================================================================================================ weights out of date
def test_editing_weights_without_a_rerun_marks_the_pending_plan_out_of_date(cancelled):
    w = get(cancelled, "/api/rules")["weights"]
    assert get(cancelled, "/api/batches/pending")["weights_out_of_date"] is False
    cancelled.put("/api/rules", json={"weights": dict(w)})                                 # identical weights: nothing to re-run
    assert get(cancelled, "/api/batches/pending")["weights_out_of_date"] is False
    with cancelled.websocket_connect("/ws") as ws:
        ws.receive_json()
        cancelled.put("/api/rules", json={"weights": dict(w, senior_60_plus=99)})
        msgs = drain(ws)
        assert {"rules", "batch"} <= set(msgs[-1]["topics"])                                # the UI is told to refetch the batch
        assert get(cancelled, "/api/batches/pending")["weights_out_of_date"] is True
        ws.send_json({"type": "snapshot"})
        assert ws.receive_json()["pending_batch"]["weights_out_of_date"] is True
    assert get(cancelled, "/api/state")["pending_batch"]["weights_out_of_date"] is True
    cancelled.post("/api/replan", json={"weights": dict(w, senior_60_plus=99)})
    assert get(cancelled, "/api/batches/pending")["weights_out_of_date"] is False         # re-run with the new weights
    cancelled.put("/api/rules", json={"weights": dict(w, senior_60_plus=5)})
    assert get(cancelled, "/api/batches/pending")["weights_out_of_date"] is True
    cancelled.post("/api/replan", json={})                                                  # a plain re-plan also uses the current weights
    assert get(cancelled, "/api/batches/pending")["weights_out_of_date"] is False
    cancelled.put("/api/rules", json={"weights": dict(w, senior_60_plus=6)})
    cancelled.post(f"/api/batches/{get(cancelled, '/api/batches/pending')['batch_id']}/approve")
    assert get(cancelled, "/api/batches")[-1]["status"] == "APPROVED"
