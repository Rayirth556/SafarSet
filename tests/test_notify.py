"""Phase 7: templates (EN + TA) that carry the journey and the reason, the always-on phone mock, and the optional real-SMS
backend behind a flag."""
import json
import re
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from safarset.api.app import create_app
from safarset.db.conn import new_db
from safarset.db.invariants import check_invariants
from safarset.domain.loop import Engine
from safarset.events.apply import apply_event
from safarset.notify import render
from safarset.notify.notifier import Notifier
from safarset.notify.samples import samples
from safarset.notify.sms_http import INDIAN_MOBILE, SmsConfig, SmsHttpBackend, config_from_env
from safarset.sim import world
from safarset.sim.generator import generate

ROOT = Path(__file__).resolve().parents[1]
TAMIL = re.compile(r"[஀-௿]")
CFG = SmsConfig("http://sms.invalid/send", "key-123", "SAFSET", "ENT-1", "TPL-9")


def placeholders(s):
    return set(re.findall(r"\{(\w+)\}", s))


def flatten(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from flatten(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


# ================================================================================================ templates
def test_english_and_tamil_templates_have_identical_keys_and_placeholders():
    en, ta = render.load_templates("en"), render.load_templates("ta")
    ek, tk = dict(flatten(en)), dict(flatten(ta))
    skip = {"places", "review_status", "language", "origin", "origin_from", "change_prefix"}
    keys = lambda d: {k for k in d if k.split(".")[0] not in skip}
    assert keys(ek) == keys(tk)
    for k in keys(ek):
        assert placeholders(str(ek[k])) == placeholders(str(tk[k])), k
    assert placeholders(en["change_prefix"]) == placeholders(ta["change_prefix"]) == {"cause"}
    assert set(ta["places"]) >= {p for p, v in world.PLACES.items()}                 # every place has a Tamil name


def test_tamil_is_marked_as_needing_native_review():
    assert "NEEDS REVIEW" in render.load_templates("ta")["review_status"]
    assert "NEEDS REVIEW" in (ROOT / "docs/messages.md").read_text(encoding="utf-8")


def test_sample_message_document_is_in_sync_with_the_templates():
    import importlib.util
    spec = importlib.util.spec_from_file_location("render_sample_messages", ROOT / "scripts/render_sample_messages.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (ROOT / "docs/messages.md").read_text(encoding="utf-8").rstrip("\n") == mod.build().rstrip("\n"), "run scripts/render_sample_messages.py"


# ================================================================================================ rendering
def by_title(fragment):
    return next(s for s in samples() if fragment in s[0])


def go(sample):
    title, group, alloc, kind, ctx = sample
    return render.render(group, alloc, kind, ctx, group["attrs"]["language"])


def test_golden_english_and_tamil_messages():
    text, reason, lang = go(by_title("en: new journey by bus"))
    assert lang == "en" and reason == "it is the earliest arrival we could offer"
    assert text == ("SafarSet: your new journey is arranged. Take bus MTC 120 R1. Board at Nurse Quarters (about 260 m straight-line from Chennai Central). "
                    "Departs 14:50; arrives Avadi at 15:57. Group of 3. Reason: it is the earliest arrival we could offer.")
    text, reason, lang = go(by_title("ta: new journey by bus"))
    assert lang == "ta"
    assert text == ("SafarSet: உங்கள் புதிய பயணம் ஏற்பாடு செய்யப்பட்டுள்ளது. வாகனம்: பேருந்து MTC 120 R1. ஏறும் இடம்: Nurse Quarters "
                    "(சென்னை சென்ட்ரலில் இருந்து நேர்கோட்டில் சுமார் 260 மீ). புறப்பாடு: 14:50. சேருமிடம்: ஆவடி, வருகை: 15:57. குழு: 3 பேர். "
                    "காரணம்: நாங்கள் வழங்கக்கூடிய மிக விரைவான வருகை இதுவே.")


@pytest.mark.parametrize("sample", samples(), ids=lambda s: s[0])
def test_every_sample_names_the_journey_and_gives_a_reason(sample):
    title, group, alloc, kind, ctx = sample
    text, reason, lang = go(sample)
    assert text.startswith("SafarSet:") and reason and reason in text
    assert lang == group["attrs"]["language"]
    if alloc is not None:                                        # new/changed journey: vehicle, boarding, both times, destination, size
        ch = alloc["reason"]["chosen"]
        assert render.hhmm(ch["depart_min"]) in text and render.hhmm(ch["arrive_min"]) in text and str(group["size"]) in text
        assert ctx["vehicle"]["name"] in text
        t = render.load_templates(lang)
        assert t["places"].get(group["dest_place"], ctx["dest_name"]) in text
    assert bool(TAMIL.search(text)) == (lang == "ta")            # Tamil script exactly when the passenger reads Tamil
    assert not placeholders(text)                                # no template placeholder left unfilled


def test_reason_is_built_from_structured_fields_in_both_languages():
    base = by_title("en: new journey by bus")
    group, ctx = base[1], base[4]
    for lang in ("en", "ta"):
        t = render.load_templates(lang)
        for decided, phrase in t["reasons"]["decided_by"].items():
            alloc = {"reason": {"algorithm": "greedy-priority-v2", "chosen": base[2]["reason"]["chosen"], "why_chosen": {"decided_by": decided}}}
            assert phrase in render.render(group, alloc, "NEW", ctx, lang)[0]
        for step, phrase in t["reasons"]["class_step"].items():
            alloc = {"reason": {"chosen": dict(base[2]["reason"]["chosen"], class_step=step), "why_chosen": {"decided_by": "EARLIEST_ARRIVAL"}}}
            assert phrase in render.render(group, alloc, "NEW", ctx, lang)[0]
        moved = {"reason": {"chosen": dict(base[2]["reason"]["chosen"], arrive_min=972), "why_chosen": {"decided_by": "EARLIEST_ARRIVAL"},
                            "reshuffled_from": {"pool_id": "x", "arrive_min": 957}}}
        text = render.render(group, moved, "NEW", ctx, lang)[0]
        assert "+15" in text
        full = {"reason": {"chosen": base[2]["reason"]["chosen"], "why_chosen": {"decided_by": "EARLIEST_ARRIVAL"}, "binding_constraints": [{"code": "CAPACITY"}]}}
        assert t["reasons"]["earlier_full"] in render.render(group, full, "NEW", ctx, lang)[0]
        override = {"reason": {"algorithm": "operator-override", "chosen": base[2]["reason"]["chosen"]}}
        assert t["reasons"]["override"] in render.render(group, override, "NEW", ctx, lang)[0]
        for cause, phrase in t["causes"].items():
            if cause != "DEFAULT":
                text = render.render(group, base[2], "CHANGED", dict(ctx, change_cause=cause), lang)[0]
                assert phrase in text
        assert t["causes"]["ROAD_CLOSED"] in render.render(group, None, "DISPLACED_UNPLACED", dict(ctx, change_cause="ROAD_CLOSED"), lang)[0]


def test_unknown_language_falls_back_to_english_and_sms_cost_is_reported():
    title, group, alloc, kind, ctx = by_title("en: new journey by bus")
    text, _, lang = render.render(group, alloc, kind, ctx, "hi")
    assert lang == "en" and not TAMIL.search(text)
    en, ta = render.sms_stats(text), render.sms_stats(go(by_title("ta: new journey by bus"))[0])
    assert en["encoding"] == "GSM-7" and ta["encoding"] == "UCS-2" and ta["segments"] > en["segments"] >= 1


def test_notifier_never_fails_the_phone_mock_even_on_malformed_input():
    n = Notifier()
    broken = n.notify({"group_id": "G1", "size": 1, "dest_place": "AVADI", "attrs": {"language": "ta"}},
                      {"reason": {"chosen": {}}}, "NEW", {})                       # missing everything
    assert len(broken) == 1 and broken[0]["channel"] == "PHONE_MOCK" and broken[0]["status"] == "SENT" and TAMIL.search(broken[0]["message"])
    assert n.status()["phone_mock"] is True


# ================================================================================================ real SMS backend (flag)
def test_real_sms_is_off_by_default_and_needs_every_setting():
    assert config_from_env({})[0] is None and "off" in config_from_env({})[1]
    cfg, note = config_from_env({"SAFARSET_SMS_ENABLED": "1", "SAFARSET_SMS_URL": "http://x"})
    assert cfg is None and "missing" in note and "SAFARSET_SMS_API_KEY" in note
    env = {"SAFARSET_SMS_ENABLED": "1", "SAFARSET_SMS_URL": "http://x", "SAFARSET_SMS_API_KEY": "k", "SAFARSET_SMS_SENDER": "S",
           "SAFARSET_SMS_DLT_ENTITY_ID": "E", "SAFARSET_SMS_DLT_TEMPLATE_ID": "T"}
    cfg, note = config_from_env(env)
    assert cfg and cfg.dlt_template_id == "T" and cfg.timeout == 5.0
    assert config_from_env(dict(env, SAFARSET_SMS_ENABLED="0"))[0] is None
    n = Notifier.from_env({})
    assert n.sms is None and [m["channel"] for m in n.notify(*by_title("en: new journey by bus")[1:4], by_title("en: new journey by bus")[4])] == ["PHONE_MOCK"]
    assert Notifier.from_env(env).sms is not None and Notifier.from_env(env).status()["sms"]["enabled"] is True


def test_indian_mobile_validation_never_dials_simulated_numbers():
    assert INDIAN_MOBILE.match("+919876543210") and not INDIAN_MOBILE.match("+910000000123") and not INDIAN_MOBILE.match("9876543210")
    calls = []
    backend = SmsHttpBackend(CFG, opener=lambda *a, **k: calls.append(a))
    for bad in (None, "", "+91000000000", "+911234567890", "98765"):
        r = backend.send(bad, "hi", "en")
        assert r["status"] == "SKIPPED" and "simulated numbers are never sent" in r["detail"]["reason"]
    assert calls == []                                                           # no HTTP request was even built


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def getcode(self):
        return self.status


def test_real_sms_request_carries_the_dlt_ids_and_the_unicode_flag():
    seen = {}

    def opener(req, timeout):
        seen.update(url=req.full_url, body=json.loads(req.data.decode("utf-8")), headers=dict(req.header_items()), timeout=timeout)
        return FakeResponse(200)
    backend = SmsHttpBackend(CFG, opener=opener)
    r = backend.send("+919876543210", "SafarSet: தமிழ்", "ta")
    assert r == {"status": "SENT", "detail": {"http_status": 200}}
    assert seen["url"] == "http://sms.invalid/send" and seen["timeout"] == 5.0
    assert seen["body"] == {"to": "+919876543210", "sender": "SAFSET", "text": "SafarSet: தமிழ்", "unicode": True,
                            "dlt_entity_id": "ENT-1", "dlt_template_id": "TPL-9"}
    assert seen["headers"]["X-api-key"] == "key-123"
    assert json.loads(json.dumps(seen["body"], ensure_ascii=False))["unicode"] is True
    backend.send("+919876543210", "plain", "en")
    assert seen["body"]["unicode"] is False


def test_real_sms_failures_are_reported_never_raised():
    def boom(req, timeout):
        raise OSError("network down")
    assert SmsHttpBackend(CFG, opener=boom).send("+919876543210", "x", "en")["status"] == "FAILED"
    assert "network down" in SmsHttpBackend(CFG, opener=boom).send("+919876543210", "x", "en")["detail"]["error"]

    def http_500(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)
    r = SmsHttpBackend(CFG, opener=http_500).send("+919876543210", "x", "en")
    assert r["status"] == "FAILED" and r["detail"]["http_status"] == 500
    assert SmsHttpBackend(CFG, opener=lambda r, timeout: FakeResponse(503)).send("+919876543210", "x", "en")["status"] == "FAILED"


# ================================================================================================ through the engine
def make_world(scenario, notifier):
    c = new_db()
    apply_event(c, "SCENARIO_LOADED", "sim", {"scenario": scenario})
    e = Engine(c, notifier=notifier)
    e.handle("TRAIN_CANCELLED", "sim", {"vehicle_id": "TRAIN-SIM-CXL"}, 840)
    return e, c


@pytest.fixture(scope="module")
def scenario():
    return generate(42)


def rows(c, sql, *a):
    return c.execute(sql, a).fetchall()


def test_approval_sends_each_group_a_message_in_its_language_naming_the_journey_and_reason(scenario):
    e, c = make_world(scenario, Notifier())
    res = e.approve(None, 850)
    assert rows(c, "SELECT COUNT(*) n FROM notifications")[0]["n"] == len(res.confirmed_groups) == len(res.notified)
    langs = {}
    for r in rows(c, """SELECT n.*, g.attrs, g.size, a.reason areason FROM notifications n JOIN groups g USING (group_id)
                        JOIN allocations a ON a.group_id = n.group_id AND a.status = 'CONFIRMED'"""):
        lang = json.loads(r["attrs"])["language"]
        langs[lang] = langs.get(lang, 0) + 1
        ch = json.loads(r["areason"])["chosen"]
        assert r["lang"] == lang and r["status"] == "SENT" and r["channel"] == "PHONE_MOCK"
        assert render.hhmm(ch["depart_min"]) in r["message"] and render.hhmm(ch["arrive_min"]) in r["message"] and r["reason"] and r["reason"] in r["message"]
        assert bool(TAMIL.search(r["message"])) == (lang == "ta")
        assert json.loads(r["detail"])["segments"] >= 1
    assert set(langs) == {"en", "ta"}                                            # both languages exercised by the default scenario


def test_changed_and_displaced_messages_explain_what_happened(scenario):
    e, c = make_world(scenario, Notifier())
    e.approve(None, 850)
    n0 = rows(c, "SELECT COUNT(*) n FROM notifications")[0]["n"]
    e.handle("LOAD_REPORT", "field", {"vehicle_id": "BUS-SPL-01", "pool_id": "BUS-SPL-01:UR", "level": "OVERCROWDED", "count": 40}, 870)
    displaced = {r["group_id"] for r in rows(c, "SELECT group_id FROM allocations WHERE status = 'DISPLACED'")}
    assert displaced
    assert rows(c, "SELECT COUNT(*) n FROM notifications")[0]["n"] == n0                  # nothing is sent until the new batch is approved
    e.approve(None, 871)
    new = rows(c, "SELECT n.*, g.attrs FROM notifications n JOIN groups g USING (group_id) WHERE n.id > ?", n0)
    assert {r["group_id"] for r in new} == displaced or {r["group_id"] for r in new} >= displaced
    for r in new:
        lang = json.loads(r["attrs"])["language"]
        t = render.load_templates(lang)
        assert t["causes"]["LOAD_REPORT"] in r["message"]                                 # why it changed, in the right language
        placed = rows(c, "SELECT 1 FROM allocations WHERE group_id = ? AND status = 'CONFIRMED'", r["group_id"])
        assert (t["messages"]["DISPLACED_UNPLACED"].split("{")[0] in r["message"]) != bool(placed)


def test_phone_mock_always_delivers_even_when_real_sms_fails_and_real_sms_skips_simulated_numbers(scenario):
    sc = json.loads(json.dumps(scenario))
    for i, g in enumerate(sc["groups"]):
        if i < 40:
            g["attrs"]["phone"] = f"+9198765{i:05d}"                              # a few real-looking numbers; the rest stay simulated
    calls = []

    def flaky(req, timeout):
        body = json.loads(req.data.decode("utf-8"))
        calls.append(body)
        if len(calls) % 2 == 0:
            raise OSError("gateway unreachable")
        return FakeResponse(202)
    e, c = make_world(sc, Notifier(SmsHttpBackend(CFG, opener=flaky), "real SMS enabled"))
    res = e.approve(None, 850)                                                     # approval succeeds whatever the gateway does
    assert res.confirmed_groups and check_invariants(c) == []
    by_channel = {}
    for r in rows(c, "SELECT channel, status, COUNT(*) n FROM notifications GROUP BY channel, status"):
        by_channel[(r["channel"], r["status"])] = r["n"]
    phone = by_channel[("PHONE_MOCK", "SENT")]
    assert phone == len(res.confirmed_groups)                                     # every group reached the phone mock
    sms_total = sum(n for (ch, _), n in by_channel.items() if ch == "SMS_HTTP")
    assert sms_total == phone                                                     # one SMS attempt record per group
    assert by_channel.get(("SMS_HTTP", "SKIPPED"), 0) > 0 and by_channel.get(("SMS_HTTP", "SENT"), 0) > 0 and by_channel.get(("SMS_HTTP", "FAILED"), 0) > 0
    assert len(calls) == by_channel[("SMS_HTTP", "SENT")] + by_channel[("SMS_HTTP", "FAILED")]      # only valid numbers hit the network
    assert all(INDIAN_MOBILE.match(b["to"]) and b["dlt_template_id"] == "TPL-9" for b in calls)


def test_api_phone_view_shows_one_message_per_group_even_with_real_sms(scenario):
    sc = json.loads(json.dumps(scenario))
    for g in sc["groups"]:
        g["attrs"]["phone"] = "+919876543210"
    notifier = Notifier(SmsHttpBackend(CFG, opener=lambda req, timeout: FakeResponse(200)), "real SMS enabled")
    with TestClient(create_app(notifier)) as client:
        client.post("/sim/load-scenario", json={"seed": 42})
        assert client.get("/api/notifier").json()["sms"] == {"enabled": True, "note": "real SMS enabled"}
        client.post("/sim/cancel-train")
        client.post("/api/batches/B1/approve")
        pnr = next(i["pnr"] for i in client.get("/api/passengers?status=CONFIRMED").json()["items"] if i["pnr"])
        msgs = client.get(f"/api/phone/{pnr}/messages").json()["messages"]
        assert len(msgs) == 1 and msgs[0]["channel"] == "PHONE_MOCK" and msgs[0]["detail"]["segments"] >= 1
    with TestClient(create_app(Notifier.from_env({}))) as client:
        assert client.get("/api/notifier").json()["sms"]["enabled"] is False
        assert client.get("/api/notifier").json()["phone_mock"] is True
        assert "NEEDS REVIEW" in client.get("/api/notifier").json()["tamil_review_status"]
