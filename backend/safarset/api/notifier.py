"""PLACEHOLDER notifier used by the API until Phase 7 adds the real templates (English + Tamil) and backends.

It only builds an English message from the allocation's machine-readable reason, so the phone mock has something to show.
Same interface the Engine expects: notify(group, allocation, kind) -> {channel, lang, message, reason} or None.
"""


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


class PlaceholderNotifier:
    channel = "PHONE_MOCK"

    def notify(self, group, allocation, kind):
        lang = group["attrs"].get("language", "en")
        if allocation is None:                                    # DISPLACED_UNPLACED
            msg = "SafarSet: your earlier seat is no longer available. We are finding another option and will message you again."
            return {"channel": self.channel, "lang": lang, "message": msg, "reason": "seat lost; no replacement yet"}
        r = allocation["reason"]
        ch = r.get("chosen", {})
        head = "SafarSet: your new journey" if kind == "NEW" else "SafarSet: your journey has CHANGED"
        msg = (f"{head}: {ch.get('vehicle_id')} departs {hhmm(ch['depart_min'])}, arrives {hhmm(ch['arrive_min'])}. "
               f"Group of {group['size']}. " + (ch.get("boarding_note") + ". " if ch.get("boarding_note") else "") +
               f"Why: {r.get('text', '')}")
        return {"channel": self.channel, "lang": lang, "message": msg, "reason": r.get("text")}
