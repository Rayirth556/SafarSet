"""The end-to-end demo script (scripts/run_demo.py): it must pass on a healthy platform, and it must FAIL when the platform
misbehaves, otherwise it proves nothing."""
import importlib.util
import json
from pathlib import Path

import pytest

from safarset.notify.notifier import Notifier

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_demo", ROOT / "scripts" / "run_demo.py")
run_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_demo)


def play(notifier=None, seed=42, tmp=None):
    client = run_demo.inprocess_client(notifier)
    argv = ["--quiet", "--seed", str(seed)] + (["--json", str(tmp)] if tmp else [])
    with client:
        code = run_demo.main(argv, client=client)
    return code


def test_demo_passes_every_check_against_the_api(tmp_path, capsys):
    report = tmp_path / "report.json"
    assert play(tmp=report) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["passed"] is True
    assert [s["step"] for s in data["steps"]] == [1, 2, 3, 4, 5, 6, 7, 0]
    assert all(s["ok"] and s["checks"] for s in data["steps"])
    labels = [s["label"] for s in data["steps"]]
    assert "Second-chart vacancies reported on a train" in labels and not any("no-show" in l.lower() for l in labels)
    texts = " ".join(c["text"] for s in data["steps"] for c in s["checks"])
    for must in ("approval only", "over-allocation", "event log is contiguous", "frozen", "OVERCROWDED", "DISPLACED", "old SMS"):
        assert must in texts, must
    assert "ALL CHECKS PASSED" in capsys.readouterr().out


@pytest.mark.parametrize("seed", [1, 7])
def test_demo_passes_for_other_seeds(seed):
    assert play(seed=seed) == 0


def test_demo_fails_when_nobody_is_notified_on_approval(tmp_path):
    class Silent(Notifier):
        def notify(self, *a, **k):
            return []
    report = tmp_path / "r.json"
    assert play(Silent(), tmp=report) == 1
    data = json.loads(report.read_text(encoding="utf-8"))
    failed = [(s["step"], c["text"]) for s in data["steps"] for c in s["checks"] if not c["ok"]]
    assert any(step == 3 and "SMS went to every confirmed group" in text for step, text in failed)


def test_demo_fails_when_messages_leave_out_the_journey_times(tmp_path):
    class Vague(Notifier):
        def notify(self, group, allocation, kind, ctx=None):
            return [{"channel": "PHONE_MOCK", "lang": "en", "message": "SafarSet: please check with the control room.", "reason": "n/a", "status": "SENT", "detail": None}]
    report = tmp_path / "r.json"
    assert play(Vague(), tmp=report) == 1
    failed = [c["text"] for s in json.loads(report.read_text(encoding="utf-8"))["steps"] for c in s["checks"] if not c["ok"]]
    assert any("journey times and a reason" in t for t in failed)


def test_demo_fails_when_something_is_sent_before_approval(tmp_path):
    from safarset.domain import loop

    class Eager(Notifier):
        pass
    original = loop.Engine.replan

    def chatty(self, *a, **k):                                           # a broken platform that messages passengers when it merely proposes
        bid = original(self, *a, **k)
        if bid and self.notifier:
            row = self.conn.execute("SELECT group_id FROM allocations WHERE batch_id = ? LIMIT 1", (bid,)).fetchone()
            if row:
                from safarset.events.apply import apply_event
                apply_event(self.conn, "SMS_SENT", "system", {"group_id": row["group_id"], "channel": "PHONE_MOCK", "lang": "en", "message": "too early", "reason": "x"})
        return bid
    loop.Engine.replan = chatty
    try:
        report = tmp_path / "r.json"
        assert play(Eager(), tmp=report) == 1
    finally:
        loop.Engine.replan = original
    failed = [c["text"] for s in json.loads(report.read_text(encoding="utf-8"))["steps"] for c in s["checks"] if not c["ok"]]
    assert any("nothing has been sent" in t for t in failed)


def test_demo_reports_an_aborted_run_instead_of_crashing(capsys):
    class Broken:
        def get(self, *a, **k):
            raise ConnectionError("server is down")
        post = get
    assert run_demo.main(["--quiet"], client=Broken()) == 2
    assert "DEMO ABORTED" in capsys.readouterr().out
