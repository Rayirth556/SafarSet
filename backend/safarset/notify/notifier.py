"""The notifier abstraction: notify(group, allocation, kind, ctx) -> list of messages to log as SMS_SENT events.

Backends:
  * PHONE_MOCK: always on; the logged event IS the delivery (the phone mock reads it). It can never be switched off or fail.
  * SMS_HTTP:   optional real SMS (see sms_http.py), only when enabled by the SAFARSET_SMS_* environment flag.
The message names the new journey AND the reason, in the group's language (English or Tamil).
"""
import os

from . import render
from .sms_http import SmsHttpBackend, config_from_env


class Notifier:
    def __init__(self, sms=None, sms_note="real SMS is off"):
        self.sms = sms
        self.sms_note = sms_note

    @classmethod
    def from_env(cls, env=None):
        config, note = config_from_env(os.environ if env is None else env)
        return cls(SmsHttpBackend(config) if config else None, note)

    def status(self):
        return {"phone_mock": True, "sms": {"enabled": self.sms is not None, "note": self.sms_note}, "languages": list(render.LANGUAGES),
                "tamil_review_status": render.load_templates("ta")["review_status"]}

    def notify(self, group, allocation, kind, ctx=None):
        lang = group["attrs"].get("language", "en")
        try:
            text, reason, lang = render.render(group, allocation, kind, ctx or {}, lang)
        except Exception:                           # malformed input must never block the phone mock or an approval
            lang = lang if lang in render.LANGUAGES else "en"
            text, reason = render.load_templates(lang)["messages"]["FALLBACK"], None
        messages = [{"channel": "PHONE_MOCK", "lang": lang, "message": text, "reason": reason, "status": "SENT", "detail": render.sms_stats(text)}]
        if self.sms is not None:
            res = self.sms.send(group["attrs"].get("phone"), text, lang)
            messages.append({"channel": self.sms.channel, "lang": lang, "message": text, "reason": reason, "status": res["status"],
                             "detail": dict(render.sms_stats(text), **res["detail"])})
        return messages
