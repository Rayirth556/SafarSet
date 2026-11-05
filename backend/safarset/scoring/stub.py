"""STUB scorer with PLACEHOLDER rules and weights (config/scoring_weights.json). Replace with the real one.

Group rule (PLACEHOLDER): a group scores as its highest-scoring member. Member-level factors come from each member's
age; group-level factors (disability, pregnancy, deadline, reserved ticket, ageing) apply to every member.
"""
import json
from pathlib import Path

from .interface import ScoreContext, ScoreResult

FACTORS = ["medical_disability", "senior_60_plus", "child_or_pregnant", "hard_deadline", "reserved_pnr", "ageing"]
GROUP_RULE = "max_member (PLACEHOLDER)"


def default_weights(config_dir=None):
    path = Path(config_dir) if config_dir else Path(__file__).resolve().parents[3] / "config"
    return json.loads((path / "scoring_weights.json").read_text(encoding="utf-8"))["weights"]


def score(group, ctx: ScoreContext) -> ScoreResult:
    w = ctx.weights
    attrs = group["attrs"]
    ages = attrs.get("ages") or [attrs.get("max_age", 30)] * group.get("size", 1)
    waited_h = max(0, ctx.now_min - group["waiting_since"]) / 60.0
    group_level = {
        "medical_disability": w["medical_disability"] if attrs.get("disability") else 0,
        "hard_deadline": w["hard_deadline"] if attrs.get("deadline_min") is not None else 0,
        "reserved_pnr": w["reserved_pnr"] if group.get("reserved") else 0,
        "ageing": round(w["ageing_per_hour"] * waited_h, 4),          # linear in time waited: nobody is starved
    }
    best = None
    for age in ages:
        member = dict(group_level)
        member["senior_60_plus"] = w["senior_60_plus"] if age >= 60 else 0
        member["child_or_pregnant"] = w["child_or_pregnant"] if (age < 12 or attrs.get("pregnant")) else 0
        total = sum(member.values())
        if best is None or total > best[0]:          # ties: first member, deterministic
            best = (total, member)
    total, member = best
    return {"total": round(total, 4), "breakdown": [(f, member[f]) for f in FACTORS]}
