"""SafarSet Hybrid Passenger Prioritisation Engine.

Implements the 4-layer prioritisation architecture:
  Layer 1: Hard eligibility & feasibility constraints (capacity, accessibility, groups intact).
  Layer 2: Priority tiers (Tier 0: Critical, Tier 1: High Priority, Tier 2: Standard).
  Layer 3: Weighted scoring within tiers (normalized 0-100 factors + linear uncapped ageing).
  Layer 4: Group prioritisation (highest-tier inheritance with companion validation).
  Plus starvation prevention through auditable wait escalation (Tier 2 -> Tier 1).
"""
from __future__ import annotations

from typing import Any, Mapping

from .interface import ScoreContext, ScoreResult
from .policy import PriorityPolicy, load_priority_policy


def _get_policy(ctx: ScoreContext | None = None) -> PriorityPolicy:
    if ctx is not None and hasattr(ctx, "policy") and getattr(ctx, "policy") is not None:
        return getattr(ctx, "policy")
    return load_priority_policy()


def _get_weights(ctx: ScoreContext | None, policy: PriorityPolicy) -> dict[str, float]:
    base = policy.factor_weights.model_dump()
    if ctx and ctx.weights:
        # Operator overrides if matching keys provided
        for k in base:
            if k in ctx.weights:
                base[k] = float(ctx.weights[k])
    return base


def _extract_members(group: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract individual members from group attrs or synthesize from ages/size."""
    attrs = group.get("attrs") or {}
    reqs = group.get("requirements") or {}
    size = max(1, int(group.get("size", 1)))

    if "members" in attrs and isinstance(attrs["members"], list) and len(attrs["members"]) == size:
        res = []
        for idx, m in enumerate(attrs["members"]):
            d = dict(m)
            d.setdefault("idx", idx)
            res.append(d)
        return res

    ages = attrs.get("ages")
    if not ages:
        ages = [attrs.get("max_age", 30)] * size
    elif len(ages) < size:
        ages = list(ages) + [30] * (size - len(ages))
    elif len(ages) > size:
        ages = ages[:size]

    members = []
    for idx, age in enumerate(ages):
        m = {
            "idx": idx,
            "age": int(age),
            "medical_emergency": bool(attrs.get("medical_emergency") or attrs.get("verified_critical")),
            "disability": bool(attrs.get("disability")),
            "wheelchair": bool(reqs.get("wheelchair")),
            "pregnant": bool(attrs.get("pregnant")),
            "assistance_required": bool(attrs.get("assistance_required")),
            "unaccompanied_minor": bool(attrs.get("unaccompanied_minor")),
        }
        # In a synthesized group, flags in attrs may apply to lead member or group
        if idx > 0 and not attrs.get("all_members_disabled"):
            # Secondary member: only inherit disability/emergency if explicitly stated
            pass
        members.append(m)

    # Detect unaccompanied minor: single traveler under 18 or explicitly flagged
    if size == 1 and (members[0]["age"] < 18 or attrs.get("unaccompanied_minor")):
        members[0]["unaccompanied_minor"] = True

    return members


def evaluate_member_tier(
    member: dict[str, Any],
    group: Mapping[str, Any],
    policy: PriorityPolicy,
) -> tuple[int, str]:
    """Layer 2: Determine member priority tier (0, 1, or 2) and reason.

    Tier 0 - Critical: Verified medical emergency or operator-verified critical case.
    Tier 1 - High Priority: Assistance required, disability assistance, elderly needing assistance, unaccompanied minor.
    Tier 2 - Standard: All other eligible passengers (including healthy seniors without assistance need).
    """
    attrs = group.get("attrs") or {}
    age = member.get("age", 30)

    # Tier 0: Critical
    if (
        member.get("medical_emergency")
        or attrs.get("medical_emergency")
        or attrs.get("verified_critical")
        or attrs.get("critical_case")
    ):
        return 0, "Verified critical medical case / operator-verified emergency"

    # Tier 1: High Priority
    reasons_tier_1 = []

    if member.get("unaccompanied_minor") or attrs.get("unaccompanied_minor"):
        reasons_tier_1.append("Unaccompanied minor")

    if member.get("wheelchair") or (group.get("requirements") or {}).get("wheelchair"):
        reasons_tier_1.append("Wheelchair accessibility assistance required")

    if member.get("disability") or attrs.get("disability"):
        reasons_tier_1.append("Disability-related assistance required")

    # Elderly requiring assistance: age >= senior_threshold AND assistance flag
    elderly_needs_assistance = (
        age >= policy.age_scoring.senior_threshold
        and (
            member.get("assistance_required")
            or attrs.get("assistance_required")
            or attrs.get("elderly_assistance")
            or member.get("disability")
            or age >= policy.age_scoring.elderly_assistance_threshold
        )
    )
    if elderly_needs_assistance:
        reasons_tier_1.append(f"Elderly passenger (age {age}) requiring assistance")

    # General assistance flag (not covered above)
    if (member.get("assistance_required") or attrs.get("assistance_required")) and not reasons_tier_1:
        reasons_tier_1.append("Special assistance required")

    if member.get("pregnant") or attrs.get("pregnant"):
        if attrs.get("pregnancy_assistance") or member.get("assistance_required"):
            reasons_tier_1.append("Expectant passenger requiring assistance")

    if reasons_tier_1:
        return 1, "; ".join(reasons_tier_1)

    # Tier 2: Standard
    if age >= policy.age_scoring.senior_threshold:
        return 2, f"Standard passenger (senior age {age}, no special assistance required)"
    return 2, "Standard passenger"


def calculate_member_factor_scores(
    member: dict[str, Any],
    group: Mapping[str, Any],
    tier: int,
    waiting_minutes: float,
    now_min: int,
    policy: PriorityPolicy,
) -> dict[str, float]:
    """Layer 3: Calculate individual normalized (0-100) factor scores for a member."""
    attrs = group.get("attrs") or {}
    age = member.get("age", 30)

    # 1. Waiting time / accumulated delay (0-100 scale: 120 min wait = 100)
    # Factor is capped at 100 for normalization before linear ageing is added
    norm_waiting = min(100.0, max(0.0, (waiting_minutes / 120.0) * 100.0))

    # 2. Age-related vulnerability (0-100 scale)
    if age < policy.age_scoring.infant_threshold:
        norm_age = 100.0
    elif age < policy.age_scoring.child_threshold:
        norm_age = 80.0
    elif age < 18:
        norm_age = 40.0
    elif age >= 80:
        norm_age = 90.0
    elif age >= 70:
        norm_age = 70.0
    elif age >= policy.age_scoring.senior_threshold:
        norm_age = 50.0
    else:
        norm_age = 0.0

    # 3. Journey urgency (0-100 scale based on deadline proximity)
    deadline_min = attrs.get("deadline_min")
    if deadline_min is not None:
        slack = deadline_min - now_min
        if slack <= 30:
            norm_urgency = 100.0
        elif slack <= 60:
            norm_urgency = 80.0
        elif slack <= 120:
            norm_urgency = 60.0
        elif slack <= 240:
            norm_urgency = 40.0
        else:
            norm_urgency = 20.0
    else:
        norm_urgency = 0.0

    # 4. Additional assistance requirements (0-100 scale)
    # Avoid double-counting: reflects secondary assistance intensity
    norm_assistance = 0.0
    reqs = group.get("requirements") or {}
    if member.get("wheelchair") or reqs.get("wheelchair"):
        norm_assistance = 100.0
    elif member.get("disability") or attrs.get("disability"):
        norm_assistance = 75.0
    elif member.get("pregnant") or attrs.get("pregnant"):
        norm_assistance = 60.0
    elif member.get("unaccompanied_minor") or attrs.get("unaccompanied_minor"):
        norm_assistance = 50.0
    elif age >= policy.age_scoring.elderly_assistance_threshold:
        norm_assistance = 40.0

    # 5. Disruption impact (0-100 scale)
    # Base disruption impact with modifier for connecting journeys
    norm_disruption = 50.0
    if attrs.get("transfer_journey") or attrs.get("connecting"):
        norm_disruption = 90.0
    elif waiting_minutes > 60:
        norm_disruption = min(100.0, 50.0 + (waiting_minutes - 60) * 0.5)

    return {
        "waiting_time": round(norm_waiting, 4),
        "age_vulnerability": round(norm_age, 4),
        "journey_urgency": round(norm_urgency, 4),
        "additional_assistance": round(norm_assistance, 4),
        "disruption_impact": round(norm_disruption, 4),
    }


def score_member(
    member: dict[str, Any],
    group: Mapping[str, Any],
    waiting_minutes: float,
    now_min: int,
    weights: dict[str, float],
    policy: PriorityPolicy,
) -> dict[str, Any]:
    """Score a single passenger member."""
    tier, tier_reason = evaluate_member_tier(member, group, policy)
    norm_factors = calculate_member_factor_scores(member, group, tier, waiting_minutes, now_min, policy)

    # Weighted base score: sum(norm * weight) / 100
    weighted_parts = {
        k: (norm_factors[k] * weights.get(k, 0.0)) / 100.0
        for k in norm_factors
    }
    base_score = sum(weighted_parts.values())

    # Reserved authority policy check: do not auto-rank reserved unless explicitly configured
    if group.get("reserved") and policy.reserved_vs_unreserved.auto_rank_reserved_above_unreserved:
        base_score += policy.reserved_vs_unreserved.reserved_priority_bonus

    # Linear uncapped ageing: rate_per_minute * waiting_minutes
    ageing_points = policy.ageing.rate_per_minute * waiting_minutes
    effective_score = base_score + ageing_points

    return {
        "idx": member["idx"],
        "age": member["age"],
        "tier": tier,
        "tier_reason": tier_reason,
        "norm_factors": norm_factors,
        "weighted_parts": weighted_parts,
        "base_score": round(base_score, 4),
        "ageing_points": round(ageing_points, 4),
        "effective_score": round(effective_score, 4),
    }


def score(group: Mapping[str, Any], ctx: ScoreContext) -> ScoreResult:
    """Entry point for the SafarSet Prioritisation Engine.

    Preserves teammate contract: score(group, ctx) -> {"total": float, "breakdown": list}.
    Enriches result with structured tier, explainability, and escalation metadata.
    """
    policy = _get_policy(ctx)
    weights = _get_weights(ctx, policy)
    attrs = group.get("attrs") or {}
    now_min = ctx.now_min
    waiting_since = group.get("waiting_since", now_min)
    waiting_minutes = max(0.0, float(now_min - waiting_since))

    members = _extract_members(group)
    scored_members = [
        score_member(m, group, waiting_minutes, now_min, weights, policy)
        for m in members
    ]

    # Layer 4: Group prioritisation
    # Highest-priority tier among members (min tier number: 0 > 1 > 2)
    raw_group_tier = min(m["tier"] for m in scored_members)

    # Companion abuse protection:
    # If group size exceeds max_unverified_group_size without operator verification,
    # companions cannot exploit priority inheritance into Tier 0 or Tier 1.
    is_companion_verified = bool(attrs.get("companion_verified") or attrs.get("verified_companions"))
    companion_blocked = False
    if raw_group_tier < 2 and len(members) > policy.group_policy.max_unverified_group_size:
        if policy.group_policy.companion_verification_required or not is_companion_verified:
            companion_blocked = True
            # Restrict group tier to Tier 2 (or require verification)
            assigned_tier = 2
            tier_reason = (
                f"Group of size {len(members)} exceeds unverified limit "
                f"({policy.group_policy.max_unverified_group_size}); companion priority inheritance requires verification."
            )
        else:
            assigned_tier = raw_group_tier
            tier_reason = f"Operator-verified companion group of size {len(members)}."
    else:
        assigned_tier = raw_group_tier
        best_member = next(m for m in scored_members if m["tier"] == raw_group_tier)
        if len(members) == 1:
            tier_reason = best_member["tier_reason"]
        else:
            tier_reason = (
                f"Group tier {assigned_tier} inherited from Member {best_member['idx'] + 1} "
                f"(age {best_member['age']}): {best_member['tier_reason']}"
            )

    # Starvation Prevention: Wait Escalation
    # Tier 2 group waiting beyond threshold is escalated to Tier 1 (never Tier 0)
    escalated = False
    escalation_reason = None
    if (
        policy.escalation.enabled
        and assigned_tier == 2
        and (waiting_minutes >= policy.escalation.tier_2_max_wait_minutes or attrs.get("escalated"))
    ):
        assigned_tier = policy.escalation.escalate_to_tier
        escalated = True
        escalation_reason = (
            f"Wait time {int(waiting_minutes)}m reached threshold "
            f"({policy.escalation.tier_2_max_wait_minutes}m); promoted from Tier 2 to Tier 1."
        )

    # Group score calculation:
    # Average score of members belonging to the highest-priority tier
    tier_members = [m for m in scored_members if m["tier"] == raw_group_tier]
    if not tier_members:
        tier_members = scored_members

    avg_base_score = sum(m["base_score"] for m in tier_members) / len(tier_members)
    avg_ageing = sum(m["ageing_points"] for m in tier_members) / len(tier_members)
    group_effective_score = avg_base_score + avg_ageing

    # Aggregate breakdown across the relevant tier members for explainability
    breakdown_factors = [
        "waiting_time",
        "age_vulnerability",
        "journey_urgency",
        "additional_assistance",
        "disruption_impact",
    ]
    avg_parts = {
        f: round(sum(m["weighted_parts"][f] for m in tier_members) / len(tier_members), 4)
        for f in breakdown_factors
    }

    breakdown = [
        ("waiting_time", avg_parts["waiting_time"]),
        ("age_vulnerability", avg_parts["age_vulnerability"]),
        ("journey_urgency", avg_parts["journey_urgency"]),
        ("additional_assistance", avg_parts["additional_assistance"]),
        ("disruption_impact", avg_parts["disruption_impact"]),
        ("ageing", round(avg_ageing, 4)),
    ]

    tier_name = policy.tiers[str(assigned_tier)].name

    deadline_min = attrs.get("deadline_min")
    deadline_slack = (deadline_min - now_min) if deadline_min is not None else float("inf")

    result: ScoreResult = {
        "total": round(group_effective_score, 4),
        "breakdown": breakdown,
    }
    # Rich structured metadata
    result["tier"] = assigned_tier
    result["tier_name"] = tier_name
    result["tier_reason"] = tier_reason
    result["base_score"] = round(avg_base_score, 4)
    result["effective_score"] = round(group_effective_score, 4)
    result["ageing"] = round(avg_ageing, 4)
    result["escalated"] = escalated
    result["escalation_reason"] = escalation_reason
    result["companion_blocked"] = companion_blocked
    result["factor_scores"] = {
        f: round(sum(m["norm_factors"][f] for m in tier_members) / len(tier_members), 2)
        for f in breakdown_factors
    }
    result["factor_weights"] = weights
    result["member_scores"] = scored_members
    result["deadline_slack"] = deadline_slack

    return result
