"""OPTIONAL real-SMS backend behind a flag (a bonus: it may not be feasible in time).

Commercial SMS to Indian numbers falls under TRAI's DLT rules: the sender id, the principal-entity id and every message
template must be registered with the operator, and the text must match a registered template (variables only). This
backend therefore carries the DLT ids in every request and needs a gateway that accepts them; it is OFF unless
SAFARSET_SMS_ENABLED=1 and all settings are present. It never raises (a gateway failure must not block approvals or the
phone mock) and it never sends to numbers that are not valid Indian mobiles, so the SIMULATED numbers in the demo are
never dialled.

Environment:
  SAFARSET_SMS_ENABLED=1
  SAFARSET_SMS_URL, SAFARSET_SMS_API_KEY, SAFARSET_SMS_SENDER,
  SAFARSET_SMS_DLT_ENTITY_ID, SAFARSET_SMS_DLT_TEMPLATE_ID   (all required)
  SAFARSET_SMS_TIMEOUT (seconds, default 5)
"""
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

INDIAN_MOBILE = re.compile(r"^\+91[6-9]\d{9}$")
REQUIRED = ("SAFARSET_SMS_URL", "SAFARSET_SMS_API_KEY", "SAFARSET_SMS_SENDER", "SAFARSET_SMS_DLT_ENTITY_ID", "SAFARSET_SMS_DLT_TEMPLATE_ID")


@dataclass
class SmsConfig:
    url: str
    api_key: str
    sender: str
    dlt_entity_id: str
    dlt_template_id: str
    timeout: float = 5.0


def config_from_env(env):
    """-> (SmsConfig | None, note). None when the flag is off or settings are missing (the note says which)."""
    if env.get("SAFARSET_SMS_ENABLED") != "1":
        return None, "real SMS is off (set SAFARSET_SMS_ENABLED=1 to enable)"
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        return None, "real SMS requested but disabled: missing " + ", ".join(missing)
    return SmsConfig(env["SAFARSET_SMS_URL"], env["SAFARSET_SMS_API_KEY"], env["SAFARSET_SMS_SENDER"], env["SAFARSET_SMS_DLT_ENTITY_ID"],
                     env["SAFARSET_SMS_DLT_TEMPLATE_ID"], float(env.get("SAFARSET_SMS_TIMEOUT", "5"))), "real SMS enabled"


class SmsHttpBackend:
    channel = "SMS_HTTP"

    def __init__(self, config: SmsConfig, opener=None):
        self.config = config
        self._open = opener or urllib.request.urlopen

    def send(self, to, text, lang):
        """-> {"status": SENT | FAILED | SKIPPED, "detail": {...}}. Never raises."""
        if not to or not INDIAN_MOBILE.match(to):
            return {"status": "SKIPPED", "detail": {"reason": "not a valid Indian mobile number; simulated numbers are never sent"}}
        c = self.config
        body = json.dumps({"to": to, "sender": c.sender, "text": text, "unicode": lang != "en", "dlt_entity_id": c.dlt_entity_id,
                           "dlt_template_id": c.dlt_template_id}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(c.url, data=body, method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8", "X-API-Key": c.api_key})
        try:
            with self._open(req, timeout=c.timeout) as resp:
                code = getattr(resp, "status", None) or resp.getcode()
            return {"status": "SENT" if 200 <= code < 300 else "FAILED", "detail": {"http_status": code}}
        except urllib.error.HTTPError as e:
            return {"status": "FAILED", "detail": {"http_status": e.code, "error": str(e)}}
        except Exception as e:                       # network down, timeout, bad URL ...
            return {"status": "FAILED", "detail": {"error": f"{type(e).__name__}: {e}"}}
