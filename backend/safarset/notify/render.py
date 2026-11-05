"""Message rendering: structured allocation reason + journey facts -> short plain-language text in the passenger's language.

SMS carries a SHORT reason: the top one or two priority factors ("Priority: senior citizen, deadline 20:00"), or, when the
group has none, a plain statement of why this journey ("Why: fastest option within 15 min, in your booked class").
Rule text (tolerances, reshuffles, scores, ranks) is operator-only: it lives in the allocation reason text and the
operator's "Why" panel, never in a passenger message.

Everything is built from the allocation's machine-readable `reason` (never from its English text), so every language
explains the same decision. Templates live in templates/{en,ta}.json.
"""
import json
from functools import lru_cache
from pathlib import Path

TEMPLATE_DIR = Path(__file__).with_name("templates")
LANGUAGES = ("en", "ta")
PRIORITY_FACTORS = ("medical_disability", "senior_60_plus", "child_or_pregnant", "hard_deadline")   # reserved ticket and waiting time are not shown
_SPEED = {"EARLIEST_ARRIVAL": "EARLIEST_ARRIVAL", "ONLY_FEASIBLE_OPTION": "ONLY_FEASIBLE_OPTION", "CLASS_STEP": "WITHIN_TOLERANCE",
          "UPGRADE_DISTANCE": "WITHIN_TOLERANCE", "BEST_FIT": "WITHIN_TOLERANCE", "ARRIVAL": "WITHIN_TOLERANCE", "MODE_TIER": "WITHIN_TOLERANCE"}


@lru_cache(maxsize=None)
def load_templates(lang):
    return json.loads((TEMPLATE_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _vehicle(t, ctx):
    v = ctx["vehicle"]
    return t["vehicle"][v["mode"]].format(train_no=v.get("train_no") or "", name=v.get("name") or v["vehicle_id"])


def _boarding(t, ctx):
    b = ctx["boarding"]
    stop = b.get("stop_name") or t["origin"]                 # trains board at the origin station
    if b.get("walk_m"):
        return t["boarding"]["walk"].format(stop=stop, meters=b["walk_m"], origin_from=t["origin_from"])
    return t["boarding"]["plain"].format(stop=stop)


def priority_factors(t, group, reason):
    """Top one or two priority factors (by points) that this group has, as short phrases."""
    r = t["reason"]
    pts = {name: p for name, p in ((reason.get("score") or {}).get("breakdown") or []) if name in PRIORITY_FACTORS and p and p > 0}
    top = sorted(pts, key=lambda n: (-pts[n], n))[:2]
    deadline = (group.get("attrs") or {}).get("deadline_min")
    out = []
    for name in top:
        phrase = r["priority_factors"][name]
        if name == "hard_deadline":
            if deadline is None:
                continue
            phrase = phrase.format(deadline=hhmm(deadline))
        out.append(phrase)
    return out


def plain_reason(t, reason):
    r = t["reason"]
    decided = (reason.get("why_chosen") or {}).get("decided_by")
    step = (reason.get("chosen") or {}).get("class_step")
    return r["plain_label"].format(speed=r["speed"][_SPEED.get(decided, "DEFAULT")], **{"class": r["class"].get(step, "")})


def reason_text(t, group, reason, kind, ctx):
    """The short, passenger-facing reason for a new or changed journey."""
    r = t["reason"]
    if reason.get("algorithm") == "operator-override":
        return r["override"]
    parts = []
    if kind == "CHANGED":
        cause = (ctx or {}).get("change_cause")
        if cause:
            parts.append(r["changed_prefix"].format(cause=t["causes"].get(cause, t["causes"]["DEFAULT"])))
    moved = reason.get("reshuffled_from")
    if moved:
        parts.append(r["moved"].format(delta=f"{reason['chosen']['arrive_min'] - moved['arrive_min']:+d}"))
    factors = priority_factors(t, group, reason)
    if factors:
        parts.append(r["priority_label"].format(factors=", ".join(factors)))
    elif not parts:
        parts.append(plain_reason(t, reason))
    return ". ".join(parts)


def displaced_reason_text(t, ctx):
    return t["causes"].get((ctx or {}).get("change_cause"), t["causes"]["DEFAULT"])


def render(group, allocation, kind, ctx, lang):
    """-> (text, reason_summary, lang_used). Raises KeyError/TypeError on malformed input; the Notifier catches that."""
    lang = lang if lang in LANGUAGES else "en"
    t = load_templates(lang)
    if kind == "DISPLACED_UNPLACED" or allocation is None:
        reason = t["reason"]["changed_prefix"].format(cause=displaced_reason_text(t, ctx))
        return t["messages"]["DISPLACED_UNPLACED"].format(reason=reason), reason, lang
    ch = allocation["reason"]["chosen"]
    reason = reason_text(t, group, allocation["reason"], kind, ctx)
    dest = t["places"].get(group["dest_place"]) or ctx["dest_name"]
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
