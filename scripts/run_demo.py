"""Play the full SafarSet demo timeline against the API and check the expected state at every step.

    python scripts/run_demo.py                      # starts its own server on a free port, plays the demo, stops it
    python scripts/run_demo.py --url http://127.0.0.1:8000     # use a server that is already running
    python scripts/run_demo.py --inprocess          # no server: drive the app in-process (what the tests do)
    options: --seed 42 --passengers 300 --json report.json --quiet

Everything is SIMULATED (see README). The script only uses the public HTTP API: /sim/* to drive the demo and /api/* to
look at the result, the same calls the React UIs make. Exit code 0 only if every check passes.
"""
import argparse
import json
import math
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Check:
    ok: bool
    text: str


@dataclass
class StepReport:
    step: int
    label: str
    at: str
    checks: list = field(default_factory=list)

    @property
    def ok(self):
        return all(c.ok for c in self.checks)


class Demo:
    def __init__(self, client, seed=42, passengers=300, out=print):
        self.c, self.seed, self.n_passengers, self.out = client, seed, passengers, out
        self.reports = []
        self.fail_fast_error = None

    # ------------------------------------------------------------------ http helpers
    def get(self, url, **params):
        r = self.c.get(url, params=params or None)
        if r.status_code != 200:
            raise RuntimeError(f"GET {url} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    def post(self, url, body=None):
        r = self.c.post(url, json=body if body is not None else {})
        if r.status_code != 200:
            raise RuntimeError(f"POST {url} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    # ------------------------------------------------------------------ observations
    def events(self):
        return self.get("/api/events", limit=2000, hide_rejected="false")["events"]

    def sms_events(self):
        return [e for e in self.events() if e["type"] == "SMS_SENT" and e["payload"]["channel"] == "PHONE_MOCK"]

    def passengers(self, status=None):
        return self.get("/api/passengers", limit=5000, **({"status": status} if status else {}))["items"]

    def confirmed(self):
        return {p["group_id"]: p for p in self.passengers("CONFIRMED")}

    def capacity(self):
        return {p["pool_id"]: p for v in self.get("/api/capacity") for p in v["pools"]}

    # ------------------------------------------------------------------ generic checks after every step
    def invariants(self, rep):
        evs = self.events()
        seqs = [e["seq"] for e in evs]
        rep.checks.append(Check(seqs == list(range(1, len(seqs) + 1)), f"event log is contiguous (seq 1..{len(seqs)})"))
        rep.checks.append(Check(self.get("/api/state")["last_seq"] == seqs[-1], "live stream position equals the last event"))
        bad = []
        for pool in self.capacity().values():
            for s in pool["segments"]:
                if s["free"] < 0 or s["cap"] != s["confirmed"] + s["boarded"] + s["tentative"] + s["free"]:
                    bad.append((pool["pool_id"], s["seg_idx"]))
            if pool["kind"] == "UNRESERVED":
                allowed = math.floor(pool["nominal"] * pool["buffer_pct"] + 1e-9)
                if any(s["cap"] > allowed for s in pool["segments"]):
                    bad.append((pool["pool_id"], "cap above floor(nominal x buffer)"))
            else:
                if any(s["cap"] > pool["nominal"] for s in pool["segments"]):
                    bad.append((pool["pool_id"], "vacancy above nominal"))
        rep.checks.append(Check(not bad, "no over-allocation on any vehicle segment (and buffers respected)" + (f": {bad[:3]}" if bad else "")))
        k = self.get("/api/kpis")
        parts = sum(k[x]["heads"] for x in ("tentative", "confirmed", "boarded", "unresolved"))
        rep.checks.append(Check(k["affected"]["heads"] == parts, f"every affected passenger is in exactly one state ({parts} of {k['affected']['heads']} heads)"))
        return k

    # ------------------------------------------------------------------ the demo
    def run(self):
        meta = self.post("/sim/load-scenario", {"seed": self.seed, "n_passengers": self.n_passengers})
        self.out(f"loaded {meta['label']} scenario: seed {self.seed}, {meta['heads']} passengers, {meta['vehicles']} vehicles, clock {meta['clock']}")
        timeline = self.get("/sim/timeline")
        steps = timeline["steps"]
        state = {}
        for step in steps:
            rep = StepReport(step["step"], step["label"], step["at"])
            before = self.snapshot()
            result = self.post("/sim/timeline/next")["result"]
            self.after_step(step, result, before, rep, state)
            self.invariants(rep)
            self.reports.append(rep)
            self.print_step(rep)
        self.final(state)
        return self.reports

    def snapshot(self):
        return {"sms": self.sms_events(), "confirmed": set(self.confirmed()), "capacity": self.capacity(), "kpis": self.get("/api/kpis"),
                "pending": self.get("/api/batches/pending")}

    def new_sms(self, before):
        last = max([x["seq"] for x in before["sms"]], default=0)
        return [e for e in self.sms_events() if e["seq"] > last]

    def kinds_by_group(self, events):
        return {e["payload"]["group_id"]: (e["payload"].get("detail") or {}).get("kind") for e in events}

    @staticmethod
    def with_reason(events):
        return all(e["payload"].get("reason") and e["payload"]["reason"] in e["payload"]["message"] for e in events)

    # ------------------------------------------------------------------ per-step expectations (from the timeline's own `expect`)
    def after_step(self, step, result, before, rep, state):
        exp, add = step["expect"], rep.checks.append
        n, k, pend = step["step"], self.get("/api/kpis"), self.get("/api/batches/pending")
        sms_now = self.sms_events()
        if n == 1:
            add(Check(k["affected"]["heads"] == exp["affected_heads"], f"{k['affected']['heads']} stranded passengers affected (expected {exp['affected_heads']})"))
            add(Check(self.get("/api/state")["banner"]["active"], "disruption banner is up: " + self.get("/api/state")["banner"]["title"]))
            add(Check(pend is not None and pend["status"] == exp["batch_status"] and pend["cause"] == "TRAIN_CANCELLED", "a plan was proposed automatically (pending, needs approval)"))
            add(Check(not pend["stale"], "the pending plan is fresh (not stale)"))
            add(Check(k["unresolved"]["heads"] >= exp["unresolved_heads_min"], f"some demand is unresolved and shown with alternatives (>= {exp['unresolved_heads_min']} head)"))
            alt = self.get("/api/unresolved")
            add(Check(alt and all(i["alternatives"][-1]["type"] == "WAITLIST" for g in alt for i in g["items"]), "every unresolved group has ranked alternatives ending in a waitlist position"))
            add(Check(len(sms_now) == 0, "nothing has been sent to passengers yet (approval only)"))
        elif n == 2:
            conf = self.confirmed()
            add(Check(k["confirmed"]["heads"] >= exp["confirmed_heads_min"], f"plan approved: {k['confirmed']['groups']} groups confirmed"))
            add(Check(k["tentative"]["heads"] == exp["tentative_heads"] == 0, "nothing is left tentative"))
            notified = {e["payload"]["group_id"] for e in sms_now}
            add(Check(notified == set(conf), f"an SMS went to every confirmed group ({len(notified)} of {len(conf)}) and to nobody else"))
            missing = [g for g, p in conf.items() if p["pnr"] and not self.get(f"/api/phone/{p['pnr']}/messages")["messages"]]
            add(Check(not missing, "every confirmed passenger's phone mock shows the message"))
            wrong = [g for g, p in list(conf.items())[:60] if not self.message_matches(p)]
            add(Check(not wrong, "messages name the journey times and a reason (spot-checked on 60 groups)"))
            add(Check(all(m == "NEW" for m in self.kinds_by_group(sms_now).values()), "every first message is a NEW journey"))
        elif n == 3:
            pool = self.capacity()[step["payload"]["pool_id"]]
            add(Check(pool["field_report"] and pool["field_report"]["level"] == "OVERCROWDED", f"{step['payload']['vehicle_id']} is flagged OVERCROWDED in the capacity view"))
            add(Check(any(e["type"] == "LOAD_REPORT" and e["payload"]["vehicle_id"] == step["payload"]["vehicle_id"] for e in self.events()), "the field report is in the event log"))
            now_conf = set(self.confirmed())
            displaced = before["confirmed"] - now_conf
            add(Check(now_conf <= before["confirmed"] and len(displaced) >= exp["displaced_groups_min"],
                      f"only confirmed groups on that bus lost a seat ({len(displaced)} displaced); nobody new was confirmed"))
            items = (pend or {}).get("items", {}).get("DISPLACED", [])
            add(Check(displaced <= {i["group_id"] for i in items}, "every displaced group appears as DISPLACED in the new pending plan"))
            add(Check(all(i["detail"].get("old_sms_still_held") for i in items), "the operator is warned that displaced passengers still hold the old SMS"))
            add(Check(len(sms_now) == len(before["sms"]), "no SMS was sent for the displacement (it needs approval)"))
            state["displaced_replaced_alone"] = sum(1 for i in items if i["detail"].get("replaced"))
            state["confirmed_before"] = now_conf
        elif n == 4:
            new_id = exp["deployed_vehicle"]
            cap = {v["vehicle_id"]: v for v in self.get("/api/capacity")}
            extra = cap.get(new_id)
            scripted = self.get("/sim/timeline")["steps"][2]["payload"]["vehicle_id"]
            add(Check(extra is not None and extra["status"] == "SCHEDULED" and extra["role"] == "ALLOCATION", f"the extra special {new_id} is now allocatable in the capacity view"))
            add(Check(extra is not None and extra["route_id"] == cap[scripted]["route_id"] and extra["stops"] == cap[scripted]["stops"],
                      f"it runs the same route and stops as the overcrowded {scripted}"))
            add(Check(any(e["type"] == "VEHICLE_DEPLOYED" for e in self.events()), "the deployment is in the event log (type VEHICLE_DEPLOYED)"))
            add(Check(set(self.confirmed()) == state["confirmed_before"], "confirmed passengers are frozen (only displaced ones may move)"))
            items = (pend or {}).get("items", {}).get("DISPLACED", [])
            on_new = [i for i in items if i["detail"].get("vehicle_id") == new_id]
            share = len(on_new) / max(1, len(items))
            add(Check(share >= exp["displaced_replaced_share_min"] and len(on_new) >= state["displaced_replaced_alone"],
                      f"the re-plan puts {len(on_new)} of {len(items)} displaced groups on the extra bus ({share:.0%}); before it, {state['displaced_replaced_alone']} had a seat"))
            add(Check(pend is not None and not pend["stale"], "a fresh re-plan is pending"))
            add(Check(len(sms_now) == len(before["sms"]), "still nothing sent (the re-plan needs approval)"))
            state["moved_groups"] = {i["group_id"] for i in items if i["detail"].get("replaced")}
            state["displaced_unplaced"] = {i["group_id"] for i in items if not i["detail"].get("replaced")}
        elif n == 5:
            new = self.new_sms(before)
            new_groups = {e["payload"]["group_id"] for e in new}
            kinds = self.kinds_by_group(new)
            add(Check(k["tentative"]["heads"] == exp["tentative_heads"] == 0 and pend is None, "re-plan approved: nothing left pending"))
            add(Check(state["moved_groups"] <= new_groups, f"every displaced group that got a new seat was told ({len(state['moved_groups'])} groups)"))
            add(Check(state["displaced_unplaced"] <= new_groups, f"displaced passengers with no new seat were told so ({len(state['displaced_unplaced'])} groups)"))
            add(Check(not (new_groups & state["confirmed_before"]), "groups whose seat did not change were not messaged again"))
            add(Check(all(kinds.get(g) == "CHANGED" for g in state["moved_groups"]), 'the moved groups got a CHANGED update ("moved to ...")'))
            add(Check(all(kinds.get(g) == "DISPLACED_UNPLACED" for g in state["displaced_unplaced"]), "the groups still without a seat got a seat-lost message"))
            add(Check(self.with_reason(new), "every message carries its short reason"))
            state["confirmed_before"] = set(self.confirmed())
        elif n == 6:
            p = step["payload"]
            b, a = before["capacity"][p["pool_id"]], self.capacity()[p["pool_id"]]
            idx = range(p["from_seg"], p["to_seg"])
            grew = [a["segments"][i]["cap"] - b["segments"][i]["cap"] for i in idx]
            ok = all(g == min(exp["vacancy_increase_seats"], a["nominal"] - b["segments"][i]["cap"]) for g, i in zip(grew, idx))
            add(Check(ok and max(grew) > 0, f"second-chart vacancies: {p['vehicle_id']} gains up to {p['seats_freed']} seats per segment"))
            add(Check(any(e["type"] == "NOSHOWS_REPORTED" for e in self.events()), "the vacancy report is in the event log (type NOSHOWS_REPORTED)"))
            add(Check(pend is not None and not pend["stale"], "a fresh re-plan is pending"))
            add(Check(set(self.confirmed()) == state["confirmed_before"], "confirmed passengers are frozen"))
            counts = pend["diff"]
            placed = counts["NEWLY_PLACED"]
            add(Check(placed["groups"] >= exp["newly_placed_groups_min"],
                      f"the vacancies place people who were still waiting: {placed['groups']} groups / {placed['heads']} heads newly placed"))
            add(Check(True, "re-plan diff: " + ", ".join(f"{c} {counts[c]['groups']}" for c in ("DISPLACED", "NEWLY_PLACED", "RESHUFFLED", "PLACED", "UNRESOLVED"))))
            add(Check(len(sms_now) == len(before["sms"]), "still nothing sent"))
            state["newly_placed"] = {i["group_id"] for i in pend["items"].get("NEWLY_PLACED", [])}
            state["pending_groups"] = {i["group_id"] for cat in ("NEWLY_PLACED", "RESHUFFLED", "DISPLACED") for i in pend["items"].get(cat, []) if i["detail"].get("vehicle_id")}
        elif n == 7:
            new = self.new_sms(before)
            new_groups = {e["payload"]["group_id"] for e in new}
            kinds = self.kinds_by_group(new)
            add(Check(k["tentative"]["heads"] == exp["tentative_heads"] == 0 and pend is None, "second re-plan approved: nothing left pending"))
            add(Check(state["pending_groups"] <= new_groups, f"every group whose journey changed was told ({len(state['pending_groups'])} placed groups)"))
            add(Check(new_groups <= state["pending_groups"], "nobody else was messaged"))
            add(Check(not (new_groups & state["confirmed_before"]), "groups whose seat did not change were not messaged again"))
            add(Check(all(kinds.get(g) == "NEW" for g in state["newly_placed"]), "the newly placed groups got a NEW journey message"))
            add(Check(self.with_reason(new), "every message carries its short reason"))

    def message_matches(self, passenger):
        a = passenger["allocation"]
        msgs = self.get(f"/api/phone/{passenger['pnr'] or passenger['group_id']}/messages")["messages"]
        if not msgs or not a:
            return False
        text = msgs[-1]["message"]
        return a["depart"] in text and a["arrive"] in text and bool(msgs[-1]["reason"]) and msgs[-1]["reason"] in text

    def final(self, state):
        rep = StepReport(0, "Whole run", "")
        k = self.get("/api/kpis")
        types = {}
        for e in self.events():
            types[e["type"]] = types.get(e["type"], 0) + 1
        rep.checks.append(Check(types.get("BATCH_APPROVED") == 3 and types.get("TRAIN_CANCELLED") == 1 and types.get("VEHICLE_DEPLOYED") == 1,
                                "the log shows 1 cancellation, 1 extra bus and 3 approvals"))
        rep.checks.append(Check(k["tentative"]["heads"] == 0, "no tentative plan left over at the end"))
        batches = self.get("/api/batches")
        rep.checks.append(Check([b["status"] for b in batches].count("APPROVED") == 3 and all(b["status"] in ("APPROVED", "SUPERSEDED") for b in batches),
                                "every plan was approved or superseded"))
        self.reports.append(rep)
        self.print_step(rep)

    def print_step(self, rep):
        head = "Whole run" if rep.step == 0 else f"Step {rep.step} ({rep.at}) {rep.label}"
        self.out(f"\n{head}: {'PASS' if rep.ok else 'FAIL'}")
        for c in rep.checks:
            self.out(f"   [{'ok' if c.ok else 'FAIL'}] {c.text}")


def summarise(reports):
    return {"passed": all(r.ok for r in reports), "steps": [{"step": r.step, "label": r.label, "ok": r.ok,
                                                           "checks": [{"ok": c.ok, "text": c.text} for c in r.checks]} for r in reports]}


# ------------------------------------------------------------------------------------------------ clients
def inprocess_client(notifier=None):
    sys.path.insert(0, str(ROOT / "backend"))
    from fastapi.testclient import TestClient
    from safarset.api.app import create_app
    from safarset.notify.notifier import Notifier
    return TestClient(create_app(notifier or Notifier()))


def spawn_server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "safarset.api.app:app", "--port", str(port), "--log-level", "warning"], cwd=ROOT / "backend")
    import httpx
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60)
    for _ in range(60):
        try:
            if client.get("/health").status_code == 200:
                return proc, client
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("the server did not start")


def main(argv=None, client=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url")
    ap.add_argument("--inprocess", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--passengers", type=int, default=300)
    ap.add_argument("--json")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    out = (lambda *_: None) if args.quiet else print
    proc = None
    try:
        if client is None:
            if args.inprocess:
                client = inprocess_client()
            elif args.url:
                import httpx
                client = httpx.Client(base_url=args.url, timeout=60)
            else:
                proc, client = spawn_server()
        demo = Demo(client, args.seed, args.passengers, out)
        reports = demo.run()
    except Exception as e:                                           # a refused or broken API call is a failed demo, not a crash
        print(f"\nDEMO ABORTED: {e}")
        return 2
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
    result = summarise(reports)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    n_ok = sum(c.ok for r in reports for c in r.checks)
    n = sum(len(r.checks) for r in reports)
    print(f"\n{'ALL CHECKS PASSED' if result['passed'] else 'SOME CHECKS FAILED'}: {n_ok} of {n} checks")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
