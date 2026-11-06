"""The notifier abstraction: notify(group, allocation, kind, ctx) -> list of messages to log as SMS_SENT events.

Backends:
  * PHONE_MOCK: always on; the logged event IS the delivery (the phone mock reads it). It can never be switched off or fail.
  * SMS_HTTP:   optional real SMS (see sms_http.py), only when enabled by the SAFARSET_SMS_* environment flag.
The message names the new journey and a SHORT reason, in the group's language (English or Tamil; Tamil is a draft).
config/notifier.json: `phone_mock_english_only` shows English only on the phone mock; `sms_allow_tamil` (default false) keeps
unreviewed Tamil off the real SMS channel.
"""
import json
import os
from pathlib import Path

from . import render
from .sms_http import SmsHttpBackend, config_from_env

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "notifier.json"


def load_switches(env=None, path=None):
    env = os.environ if env is None else env
    p = Path(path) if path else DEFAULT_CONFIG
    sw = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    out = {"phone_mock_english_only": bool(sw.get("phone_mock_english_only", False)), "sms_allow_tamil": bool(sw.get("sms_allow_tamil", False))}
    for key, var in (("phone_mock_english_only", "SAFARSET_PHONE_ENGLISH_ONLY"), ("sms_allow_tamil", "SAFARSET_SMS_ALLOW_TAMIL")):
        if env.get(var) in ("0", "1"):
            out[key] = env[var] == "1"
    return out


class Notifier:
    def __init__(self, sms=None, sms_note="real SMS is off", phone_mock_english_only=False, sms_allow_tamil=False):
        self.sms, self.sms_note = sms, sms_note
        self.phone_mock_english_only, self.sms_allow_tamil = phone_mock_english_only, sms_allow_tamil

    @classmethod
    def from_env(cls, env=None, config_path=None):
        config, note = config_from_env(os.environ if env is None else env)
        return cls(SmsHttpBackend(config) if config else None, note, **load_switches(env, config_path))

    def status(self):
        return {"phone_mock": True, "phone_mock_english_only": self.phone_mock_english_only,
                "sms": {"enabled": self.sms is not None, "note": self.sms_note, "tamil_allowed": self.sms_allow_tamil},
                "languages": list(render.LANGUAGES), "tamil_review_status": render.load_templates("ta")["review_status"]}

    def _render(self, group, allocation, kind, ctx, lang):
        try:
            return render.render(group, allocation, kind, ctx or {}, lang)
        except Exception:                           # malformed input must never block the phone mock or an approval
            lang = lang if lang in render.LANGUAGES else "en"
            return render.load_templates(lang)["messages"]["FALLBACK"], None, lang

    def preview(self, group, allocation, kind, ctx, lang):
        """The text a passenger would receive, without sending or logging it: the same renderer and fallback as notify()."""
        text, reason, lang = self._render(group, allocation, kind, ctx, lang)
        return {"lang": lang, "message": text, "reason": reason, **render.sms_stats(text), "draft_translation": lang == "ta"}

    def notify(self, group, allocation, kind, ctx=None):
        preferred = group["attrs"].get("language", "en")
        phone_lang = "en" if self.phone_mock_english_only else preferred
        text, reason, lang = self._render(group, allocation, kind, ctx, phone_lang)
        detail = dict(render.sms_stats(text), preferred_language=preferred, draft_translation=lang == "ta")
        messages = [{"channel": "PHONE_MOCK", "lang": lang, "message": text, "reason": reason, "status": "SENT", "detail": detail}]
        if self.sms is not None:
            sms_lang = preferred if (preferred == "en" or self.sms_allow_tamil) else "en"
            s_text, s_reason, s_lang = (text, reason, lang) if sms_lang == lang else self._render(group, allocation, kind, ctx, sms_lang)
            res = self.sms.send(group["attrs"].get("phone"), s_text, s_lang)
            messages.append({"channel": self.sms.channel, "lang": s_lang, "message": s_text, "reason": s_reason, "status": res["status"],
                             "detail": dict(render.sms_stats(s_text), preferred_language=preferred, draft_translation=s_lang == "ta", **res["detail"])})
        return messages
