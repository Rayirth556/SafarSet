"""Phase 7: short plain-language messages (EN + TA) with the journey and a short reason, the always-on phone mock, the
English-only switch, and the optional real-SMS backend behind a flag."""
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
from safarset.notify.notifier import Notifier, load_switches
from safarset.notify.samples import samples
from safarset.notify.sms_http import INDIAN_MOBILE, SmsConfig, SmsHttpBackend, config_from_env
from safarset.sim import world
from safarset.sim.generator import generate

ROOT = Path(__file__).resolve().parents[1]
TAMIL = re.compile(r"[஀-௿]")
CFG = SmsConfig("http://sms.invalid/send", "key-123", "SAFSET", "ENT-1", "TPL-9")
# operator-only rule wording: it must never appear in a passenger message
OPERATOR_ONLY = ("count as equal", "tolerance", "reshuffle", "stability", "Priority rank", "score", "segment", "buffer", "greedy")


def placeholders(s):
    return set(re.findall(r"\{(\w+)\}", s))


def flatten(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from flatten(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


def has_reason_label(text):
    return any(label in text for label in ("Priority:", "Why:", "Changed:", "Assigned by", "Moved to make room", "மற்றொரு பயணிக்கு", "முன்னுரிமை:", "காரணம்:", "மாற்றம்:", "கட்டுப்பாட்டு அறை"))


# ================================================================================================ templates
def test_english_and_tamil_templates_have_identical_keys_and_placeholders():
    en, ta = render.load_templates("en"), render.load_templates("ta")
    ek, tk = dict(flatten(en)), dict(flatten(ta))
    skip = {"places", "review_status", "language", "origin", "origin_from"}
    keys = lambda d: {k for k in d if k.split(".")[0] not in skip}
    assert keys(ek) == keys(tk)
    for k in keys(ek):
        if not k.endswith("_note"):
            assert placeholders(str(ek[k])) == placeholders(str(tk[k])), k
    assert set(ta["places"]) >= set(world.PLACES)                                     # every place has a Tamil name


def test_passenger_templates_contain_no_operator_rule_wording():
    for lang in render.LANGUAGES:
        values = " ".join(str(v) for k, v in flatten(render.load_templates(lang)) if not k.endswith("_note"))   # wording only, not keys or notes
        for word in OPERATOR_ONLY:
            assert word.lower() not in values.lower(), (lang, word)


def test_tamil_is_marked_as_needing_native_review_everywhere():
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
    text, reason, lang = go(by_title("en: new journey by bus, priority factors"))
    assert lang == "en" and reason == "Priority: senior citizen, deadline 20:00"
    assert text == ("SafarSet: your new journey: bus MTC 120 R1. Board at Nurse Quarters (about 260 m from Chennai Central). "
                    "Departs 14:50, arrives Avadi 15:57. Group of 3. Priority: senior citizen, deadline 20:00.")
    text, reason, lang = go(by_title("en: new journey by train, equal arrivals"))
    assert reason == "Why: fastest option within 15 min, in your booked class"                       # the owner's example wording
    text, reason, lang = go(by_title("ta: new journey by bus, priority factors"))
    assert lang == "ta"
    assert text == ("SafarSet: புதிய பயணம்: பேருந்து MTC 120 R1. ஏறும் இடம்: Nurse Quarters (சென்னை சென்ட்ரலில் இருந்து சுமார் 260 மீ). "
                    "புறப்பாடு 14:50, ஆவடி வருகை 15:57. 3 பேர். முன்னுரிமை: மூத்த குடிமகன், காலக்கெடு 20:00.")


@pytest.mark.parametrize("sample", samples(), ids=lambda s: s[0])
def test_every_sample_is_short_names_the_journey_and_gives_a_short_reason(sample):
    title, group, alloc, kind, ctx = sample
    text, reason, lang = go(sample)
    assert text.startswith("SafarSet:") and reason and reason in text and has_reason_label(text)
    assert lang == group["attrs"]["language"] and not placeholders(text)
    assert bool(TAMIL.search(text)) == (lang == "ta")
    stats = render.sms_stats(text)
    assert stats["segments"] <= (2 if lang == "en" else 4), (stats, text)                 # English: 2 segments at most; Tamil: as short as practical
    assert len(text) <= (230 if lang == "en" else 230)
    for word in OPERATOR_ONLY:
        assert word.lower() not in text.lower(), word
    if alloc is not None:                                         # new/changed journey: vehicle, boarding, both times, destination, size
        ch = alloc["reason"]["chosen"]
        assert render.hhmm(ch["depart_min"]) in text and render.hhmm(ch["arrive_min"]) in text and str(group["size"]) in text
        assert ctx["vehicle"]["name"] in text
        assert render.load_templates(lang)["places"].get(group["dest_place"], ctx["dest_name"]) in text


def test_sms_reason_is_the_top_one_or_two_priority_factors_by_points():
    for lang in render.LANGUAGES:
        t = render.load_templates(lang)["reason"]
        one = render.render(by_title("en: new journey by bus, priority")[1] | {"attrs": {"language": lang, "deadline_min": None}},
                            by_title("en: new journey by bus, priority")[2], "NEW", by_title("en: new journey by bus, priority")[4], lang)[1]
        assert one == t["priority_label"].format(factors=t["priority_factors"]["senior_60_plus"])      # deadline factor needs a deadline to show
    two = go(by_title("en: new journey by bus, priority factors"))[1]
    assert two.count(",") == 1 and two.startswith("Priority:")
    three = go(by_title("en: new journey by bus, three priority"))[1]
    assert three == "Priority: medical need, senior citizen" and "deadline" not in three        # only the top two, highest points first
    plain = go(by_title("en: new journey by bus, no priority"))[1]
    assert plain.startswith("Why:") and "Priority" not in plain                                  # ticket type and waiting time are not shown as priority


def test_plain_reason_wording_for_every_decision_and_class_step():
    base = by_title("en: new journey by bus, no priority")
    group, ctx = base[1], base[4]
    expected_speed = {"EARLIEST_ARRIVAL": "fastest option", "ONLY_FEASIBLE_OPTION": "the only option that fits your group",
                      "CLASS_STEP": "fastest option within 15 min", "UPGRADE_DISTANCE": "fastest option within 15 min", "BEST_FIT": "fastest option within 15 min",
                      "ARRIVAL": "fastest option within 15 min", "MODE_TIER": "fastest option within 15 min"}
    for lang in render.LANGUAGES:
        t = render.load_templates(lang)["reason"]
        for decided, speed_key in (("EARLIEST_ARRIVAL", "EARLIEST_ARRIVAL"), ("ONLY_FEASIBLE_OPTION", "ONLY_FEASIBLE_OPTION"), ("CLASS_STEP", "WITHIN_TOLERANCE"),
                                   ("BEST_FIT", "WITHIN_TOLERANCE"), ("MODE_TIER", "WITHIN_TOLERANCE")):
            alloc = _alloc(base, decided=decided)
            assert t["speed"][speed_key] in render.render(group, alloc, "NEW", ctx, lang)[1]
        for step, phrase in t["class"].items():
            assert phrase in render.render(group, _alloc(base, step=step), "NEW", ctx, lang)[1]
        assert render.render(group, _alloc(base, step="UNRESERVED_TICKET"), "NEW", ctx, lang)[1].count(",") == 0
    assert expected_speed["EARLIEST_ARRIVAL"] in render.render(group, _alloc(base), "NEW", ctx, "en")[1]
    assert "in your booked class" in render.render(group, _alloc(base), "NEW", ctx, "en")[1]


def _alloc(base, decided="EARLIEST_ARRIVAL", step="SAME_CLASS", **extra):
    reason = dict(base[2]["reason"], why_chosen={"decided_by": decided}, chosen=dict(base[2]["reason"]["chosen"], class_step=step))
    reason.update(extra)
    return {"reason": reason}


def test_changed_moved_override_and_displaced_wording_in_both_languages():
    base = by_title("en: new journey by bus, no priority")
    group, ctx = base[1], base[4]
    for lang in render.LANGUAGES:
        t = render.load_templates(lang)
        for cause, phrase in t["causes"].items():
            if cause != "DEFAULT":
                text = render.render(group, _alloc(base), "CHANGED", dict(ctx, change_cause=cause), lang)[1]
                assert t["reason"]["changed_prefix"].format(cause=phrase) in text
                assert t["causes"][cause] in render.render(group, None, "DISPLACED_UNPLACED", dict(ctx, change_cause=cause), lang)[0]
        moved = render.render(group, _alloc(base, reshuffled_from={"pool_id": "x", "arrive_min": 940}), "CHANGED", ctx, lang)[1]
        assert "+17" in moved
        assert render.load_templates(lang)["reason"]["override"] in render.render(group, _alloc(base, algorithm="operator-override"), "NEW", ctx, lang)[1]
    assert render.render(group, None, "DISPLACED_UNPLACED", {}, "en")[1] == "Changed: the plan changed"          # no cause known: generic


def test_unknown_language_falls_back_to_english_and_sms_cost_is_reported():
    title, group, alloc, kind, ctx = by_title("en: new journey by bus, no priority")
    text, _, lang = render.render(group, alloc, kind, ctx, "hi")
    assert lang == "en" and not TAMIL.search(text)
    en, ta = render.sms_stats(text), render.sms_stats(go(by_title("ta: new journey by bus, no priority"))[0])
    assert en["encoding"] == "GSM-7" and ta["encoding"] == "UCS-2" and ta["segments"] > en["segments"] >= 1


def test_notifier_never_fails_the_phone_mock_even_on_malformed_input():
    n = Notifier()
    broken = n.notify({"group_id": "G1", "size": 1, "dest_place": "AVADI", "attrs": {"language": "ta"}}, {"reason": {"chosen": {}}}, "NEW", {})
    assert len(broken) == 1 and broken[0]["channel"] == "PHONE_MOCK" and broken[0]["status"] == "SENT" and TAMIL.search(broken[0]["message"])
    assert n.status()["phone_mock"] is True


# ================================================================================================ English-only switch
def tamil_sample():
    return by_title("ta: new journey by bus, priority factors")


def test_phone_mock_english_only_switch_leaves_tamil_off_the_phone_mock():
    title, group, alloc, kind, ctx = tamil_sample()
    default = Notifier().notify(group, alloc, kind, ctx)[0]
    assert default["lang"] == "ta" and TAMIL.search(default["message"]) and default["detail"]["draft_translation"] is True
    english = Notifier(phone_mock_english_only=True).notify(group, alloc, kind, ctx)[0]
    assert english["lang"] == "en" and not TAMIL.search(english["message"]) and english["channel"] == "PHONE_MOCK"
    assert english["detail"]["preferred_language"] == "ta" and english["detail"]["draft_translation"] is False
    assert Notifier(phone_mock_english_only=True).status()["phone_mock_english_only"] is True


def test_switches_come_from_the_config_file_and_environment(tmp_path):
    p = tmp_path / "notifier.json"
    assert load_switches({}, ROOT / "config/notifier.json") == {"phone_mock_english_only": False, "sms_allow_tamil": False}     # shipped defaults
    p.write_text(json.dumps({"phone_mock_english_only": True}), encoding="utf-8")
    assert load_switches({}, p) == {"phone_mock_english_only": True, "sms_allow_tamil": False}
    assert load_switches({"SAFARSET_PHONE_ENGLISH_ONLY": "0"}, p)["phone_mock_english_only"] is False             # the environment wins
    assert load_switches({"SAFARSET_SMS_ALLOW_TAMIL": "1"}, p)["sms_allow_tamil"] is True
    assert Notifier.from_env({"SAFARSET_PHONE_ENGLISH_ONLY": "1"}).phone_mock_english_only is True
    assert load_switches({}, tmp_path / "missing.json") == {"phone_mock_english_only": False, "sms_allow_tamil": False}


def test_real_sms_stays_english_until_tamil_is_explicitly_allowed():
    title, group, alloc, kind, ctx = tamil_sample()
    sent = []
    sms = SmsHttpBackend(CFG, opener=lambda req, timeout: (sent.append(json.loads(req.data.decode("utf-8"))), FakeResponse(200))[1])
    group = dict(group, attrs=dict(group["attrs"], phone="+919876543210"))
    msgs = Notifier(sms).notify(group, alloc, kind, ctx)
    assert [m["channel"] for m in msgs] == ["PHONE_MOCK", "SMS_HTTP"] and msgs[0]["lang"] == "ta" and msgs[1]["lang"] == "en"
    assert sent[0]["unicode"] is False and not TAMIL.search(sent[0]["text"])
    sent.clear()
    msgs = Notifier(sms, sms_allow_tamil=True).notify(group, alloc, kind, ctx)
    assert msgs[1]["lang"] == "ta" and sent[0]["unicode"] is True and TAMIL.search(sent[0]["text"])


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
    sample = by_title("en: new journey by bus, no priority")
    assert [m["channel"] for m in Notifier.from_env({}).notify(*sample[1:4], sample[4])] == ["PHONE_MOCK"]
    assert Notifier.from_env(env).status()["sms"]["enabled"] is True


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


def test_approval_sends_short_plain_messages_in_each_groups_language(scenario):
    e, c = make_world(scenario, Notifier())
    res = e.approve(None, 850)
    assert rows(c, "SELECT COUNT(*) n FROM notifications")[0]["n"] == len(res.confirmed_groups) == len(res.notified)
    langs, priority_seen = {}, False
    for r in rows(c, """SELECT n.*, g.attrs, g.size, a.reason areason FROM notifications n JOIN groups g USING (group_id)
                        JOIN allocations a ON a.group_id = n.group_id AND a.status = 'CONFIRMED'"""):
        lang = json.loads(r["attrs"])["language"]
        langs[lang] = langs.get(lang, 0) + 1
        ch = json.loads(r["areason"])["chosen"]
        assert r["lang"] == lang and r["status"] == "SENT" and r["channel"] == "PHONE_MOCK"
        assert render.hhmm(ch["depart_min"]) in r["message"] and render.hhmm(ch["arrive_min"]) in r["message"] and r["reason"] and r["reason"] in r["message"]
        assert bool(TAMIL.search(r["message"])) == (lang == "ta") and has_reason_label(r["message"])
        detail = json.loads(r["detail"])
        assert detail["segments"] <= (2 if lang == "en" else 4) and detail["draft_translation"] == (lang == "ta")
        assert not any(w.lower() in r["message"].lower() for w in OPERATOR_ONLY)
        priority_seen |= "Priority:" in r["message"] or "முன்னுரிமை:" in r["message"]
    assert set(langs) == {"en", "ta"} and priority_seen                          # both languages, and priority wording, in the default scenario
    # the FULL reason is still available to the operator, untouched by the short SMS wording
    full = json.loads(rows(c, "SELECT reason FROM allocations WHERE status = 'CONFIRMED' LIMIT 1")[0]["reason"])
    assert full["text"].startswith("Priority rank") and "count as equal" in full["text"] + "count as equal" and full["score"]["breakdown"]


def test_english_only_phone_mock_through_the_engine(scenario):
    e, c = make_world(scenario, Notifier(phone_mock_english_only=True))
    e.approve(None, 850)
    messages = rows(c, "SELECT message, lang, detail FROM notifications")
    assert messages and all(m["lang"] == "en" and not TAMIL.search(m["message"]) for m in messages)
    assert any(json.loads(m["detail"])["preferred_language"] == "ta" for m in messages)          # Tamil readers exist; they just see English for now


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
    assert {r["group_id"] for r in new} >= displaced
    for r in new:
        lang = json.loads(r["attrs"])["language"]
        t = render.load_templates(lang)
        assert t["causes"]["LOAD_REPORT"] in r["message"]                                 # why it changed, in the right language
        assert not any(w.lower() in r["message"].lower() for w in OPERATOR_ONLY)


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
    assert sum(n for (ch, _), n in by_channel.items() if ch == "SMS_HTTP") == phone
    assert by_channel.get(("SMS_HTTP", "SKIPPED"), 0) > 0 and by_channel.get(("SMS_HTTP", "SENT"), 0) > 0 and by_channel.get(("SMS_HTTP", "FAILED"), 0) > 0
    assert len(calls) == by_channel[("SMS_HTTP", "SENT")] + by_channel[("SMS_HTTP", "FAILED")]      # only valid numbers hit the network
    assert all(INDIAN_MOBILE.match(b["to"]) and b["dlt_template_id"] == "TPL-9" and not TAMIL.search(b["text"]) for b in calls)   # Tamil off by default


def test_api_phone_view_shows_one_message_per_group_with_a_draft_flag_for_tamil(scenario):
    sc = json.loads(json.dumps(scenario))
    for g in sc["groups"]:
        g["attrs"]["phone"] = "+919876543210"
    notifier = Notifier(SmsHttpBackend(CFG, opener=lambda req, timeout: FakeResponse(200)), "real SMS enabled")
    with TestClient(create_app(notifier)) as client:
        client.post("/sim/load-scenario", json={"seed": 42})
        status = client.get("/api/notifier").json()
        assert status["sms"] == {"enabled": True, "note": "real SMS enabled", "tamil_allowed": False} and status["phone_mock_english_only"] is False
        client.post("/sim/cancel-train")
        client.post("/api/batches/B1/approve")
        items = [i for i in client.get("/api/passengers?status=CONFIRMED").json()["items"] if i["pnr"]]
        seen_langs = set()
        for i in items[:40]:
            msgs = client.get(f"/api/phone/{i['pnr']}/messages").json()["messages"]
            assert len(msgs) == 1 and msgs[0]["channel"] == "PHONE_MOCK" and msgs[0]["detail"]["segments"] >= 1
            assert msgs[0]["detail"]["draft_translation"] == (msgs[0]["lang"] == "ta")
            seen_langs.add(msgs[0]["lang"])
        assert seen_langs == {"en", "ta"}
    with TestClient(create_app(Notifier.from_env({}))) as client:
        assert client.get("/api/notifier").json()["sms"]["enabled"] is False
        assert "NEEDS REVIEW" in client.get("/api/notifier").json()["tamil_review_status"]
