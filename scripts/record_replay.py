"""Record the scripted demo as static JSON for the GitHub Pages replay (frontend/public/replay/).

Runs the real backend in-process: load the seed-42 scenario, then for each scripted timeline step play it and save every
response the screens read. steps/<n>.json is the state after n steps, keyed by the request path plus its sorted query string
(the same key the frontend's replay mode builds). Run from the repository root:  python scripts/record_replay.py
"""
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from safarset.api.app import create_app  # noqa: E402

OUT = ROOT / "frontend" / "public" / "replay"
SEED = 42
BATCH_KINDS = ("NEW", "CHANGED", "DISPLACED_UNPLACED")


def key(path, params=None):
    return path + ("?" + urlencode(sorted((k, str(v)) for k, v in params.items())) if params else "")


def snapshot(c):
    out = {}

    def get(path, params=None):
        r = c.get(path, params=params)
        if r.status_code == 200:
            out[key(path, params)] = r.json()
        return out.get(key(path, params))

    for path, params in [
        ("/health", None), ("/api/state", None), ("/api/capacity", {"role": "ALLOCATION"}), ("/api/capacity", {"role": "all"}),
        ("/api/unresolved", None), ("/api/batches", None), ("/api/batches/pending", None), ("/api/rules", None),
        ("/api/notifier", None), ("/api/conflicts", None), ("/api/field/vehicles", None), ("/sim/params", None),
        ("/sim/timeline", None), ("/api/events", {"tail": "true", "limit": 300, "hide_rejected": "true"}),
    ]:
        get(path, params)

    page = get("/api/passengers", {"limit": 500, "offset": 0}) or {"items": []}
    groups = [p["group_id"] for p in page["items"]]
    for gid in groups:
        get(f"/api/passengers/{quote(gid, safe='')}/why")
        thread = get(f"/api/phone/{quote(gid, safe='')}/messages")
        if thread and thread.get("pnr"):
            out[key(f"/api/phone/{quote(thread['pnr'], safe='')}/messages")] = thread

    for v in out.get(key("/api/field/vehicles"), []):
        get(f"/api/field/vehicles/{quote(v['vehicle_id'], safe='')}/manifest")

    for b in (out.get(key("/api/batches")) or []):
        bid = quote(b["batch_id"], safe="")
        get(f"/api/batches/{bid}")
        for kind in BATCH_KINDS:
            get(f"/api/batches/{bid}/preview", {"kind": kind, "lang": "en"})
    return out


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "steps").mkdir(parents=True)
    with TestClient(create_app()) as c:
        assert c.post("/sim/load-scenario", json={"seed": SEED}).status_code == 200
        total = c.get("/sim/timeline").json()["total"]
        for n in range(total + 1):
            if n:
                r = c.post("/sim/timeline/next")
                assert r.status_code == 200, r.text
            data = snapshot(c)
            (OUT / "steps" / f"{n}.json").write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
            print(f"step {n}/{total}: {len(data)} screens recorded")
    (OUT / "manifest.json").write_text(json.dumps({"seed": SEED, "total": total}), encoding="utf-8")


if __name__ == "__main__":
    main()
