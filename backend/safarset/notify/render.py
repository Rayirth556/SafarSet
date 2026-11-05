"""Message rendering: structured allocation reason + journey facts -> text in the passenger's language.

The reason comes from the allocation's machine-readable `reason` JSON (never from its English text), so every language
explains the same decision. Templates live in templates/{en,ta}.json.
"""
import json
from functools import lru_cache
from pathlib import Path

TEMPLATE_DIR = Path(__file__).with_name("templates")
LANGUAGES = ("en", "ta")


@lru_cache(maxsize=None)
def load_templates(lang):
    return json.loads((TEMPLATE_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _place(t, ctx, place_id, fallback):
    return t["places"].get(place_id) or fallback


def _vehicle(t, ctx):
    v = ctx["vehicle"]
    return t["vehicle"][v["mode"]].format(train_no=v.get("train_no") or "", name=v.get("name") or v["vehicle_id"])


def _boarding(t, ctx):
    b = ctx["boarding"]
    stop = b.get("stop_name") or t["origin"]                 # trains board at the origin station
    if b.get("walk_m"):
        return t["boarding"]["walk"].format(stop=stop, meters=b["walk_m"], origin_from=t["origin_from"])
    return t["boarding"]["plain"].format(stop=stop)


def reason_text(t, reason, kind, ctx):
    """One sentence fragment explaining the decision, built only from structured fields."""
    r = t["reasons"]
    parts = []
    if kind == "CHANGED":
        cause = (ctx or {}).get("change_cause")
        if cause:
            parts.append(t["change_prefix"].format(cause=t["causes"].get(cause, t["causes"]["DEFAULT"])))
    if reason.get("algorithm") == "operator-override":
        parts.append(r["override"])
        return "; ".join(parts)
    decided = (reason.get("why_chosen") or {}).get("decided_by")
    parts.append(r["decided_by"].get(decided, r["decided_by"]["DEFAULT"]))
    step = (reason.get("chosen") or {}).get("class_step")
    if step in r["class_step"]:
        parts.append(r["class_step"][step])
    if reason.get("binding_constraints"):
        parts.append(r["earlier_full"])
    moved = reason.get("reshuffled_from")
    if moved:
        delta = reason["chosen"]["arrive_min"] - moved["arrive_min"]
        parts.append(r["reshuffle_moved"].format(delta=f"{delta:+d}"))
    elif reason.get("reshuffle"):
        parts.append(r["reshuffle_made_room"])
    return "; ".join(parts)


def displaced_reason_text(t, ctx):
    cause = (ctx or {}).get("change_cause")
    return t["causes"].get(cause, t["causes"]["DEFAULT"])


def render(group, allocation, kind, ctx, lang):
    """-> (text, reason_summary, lang_used). Raises KeyError/TypeError on malformed input; the Notifier catches that."""
    lang = lang if lang in LANGUAGES else "en"
    t = load_templates(lang)
    if kind == "DISPLACED_UNPLACED" or allocation is None:
        reason = displaced_reason_text(t, ctx)
        return t["messages"]["DISPLACED_UNPLACED"].format(reason=reason), reason, lang
    ch = allocation["reason"]["chosen"]
    reason = reason_text(t, allocation["reason"], kind, ctx)
    dest = _place(t, ctx, group["dest_place"], ctx["dest_name"])
    text = t["messages"]["CHANGED" if kind == "CHANGED" else "NEW"].format(
        vehicle=_vehicle(t, ctx), boarding=_boarding(t, ctx), depart=hhmm(ch["depart_min"]), arrive=hhmm(ch["arrive_min"]),
        dest=dest, size=group["size"], reason=reason)
    return text, reason, lang


def sms_stats(text):
    """Rough SMS cost: GSM-7 (plain ASCII) is 160 chars per message (153 when joined); anything else (Tamil) is UCS-2, 70 (67)."""
    n = len(text)
    ascii_only = all(ord(c) < 128 for c in text)
    single, joined = (160, 153) if ascii_only else (70, 67)
    segments = 1 if n <= single else -(-n // joined)
    return {"chars": n, "encoding": "GSM-7" if ascii_only else "UCS-2", "segments": segments, "approximate": True}
