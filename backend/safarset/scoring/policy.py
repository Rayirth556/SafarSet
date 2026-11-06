"""Configurable priority policy loader and validator for SafarSet."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _BaseConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TierDefinition(_BaseConfig):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rank: int = Field(ge=0, le=2)


class FactorWeights(_BaseConfig):
    waiting_time: float = Field(ge=0, le=100)
    age_vulnerability: float = Field(ge=0, le=100)
    journey_urgency: float = Field(ge=0, le=100)
    additional_assistance: float = Field(ge=0, le=100)
    disruption_impact: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _validate_sum(self) -> FactorWeights:
        total = (self.waiting_time + self.age_vulnerability +
                 self.journey_urgency + self.additional_assistance +
                 self.disruption_impact)
        if abs(total - 100.0) > 1e-4:
            raise ValueError(f"Priority factor weights must sum to exactly 100, got {total}")
        return self


class AgeScoringConfig(_BaseConfig):
    senior_threshold: int = Field(default=60, ge=40, le=100)
    elderly_assistance_threshold: int = Field(default=75, ge=50, le=110)
    child_threshold: int = Field(default=12, ge=0, le=18)
    infant_threshold: int = Field(default=5, ge=0, le=10)


class AgeingConfig(_BaseConfig):
    rate_per_minute: float = Field(ge=0)
    linear: bool = True
    uncapped: bool = True

    @field_validator("rate_per_minute")
    @classmethod
    def _rate_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"Ageing rate must be non-negative, got {v}")
        return v


class EscalationConfig(_BaseConfig):
    enabled: bool = True
    tier_2_max_wait_minutes: int = Field(default=120, gt=0)
    escalate_to_tier: int = Field(default=1, ge=1, le=1)
    allow_escalation_to_tier_0: bool = False

    @model_validator(mode="after")
    def _validate_escalation_rules(self) -> EscalationConfig:
        if self.allow_escalation_to_tier_0:
            raise ValueError("Escalation to Tier 0 is prohibited by operational policy")
        if self.escalate_to_tier != 1:
            raise ValueError(f"Escalation target must be Tier 1, got {self.escalate_to_tier}")
        if self.tier_2_max_wait_minutes <= 0:
            raise ValueError(f"Escalation wait threshold must be positive, got {self.tier_2_max_wait_minutes}")
        return self


class GroupPolicyConfig(_BaseConfig):
    strategy: Literal["highest_tier_member_average"] = "highest_tier_member_average"
    companion_verification_required: bool = False
    max_unverified_group_size: int = Field(default=6, ge=1)


class ReservedVsUnreservedConfig(_BaseConfig):
    auto_rank_reserved_above_unreserved: bool = False
    reserved_priority_bonus: float = Field(default=0.0, ge=0)


class WalkOnPolicyConfig(_BaseConfig):
    individually_allocated: bool = False
    contribute_to_buffers: bool = True
    deduct_actual_boardings: bool = True

    @field_validator("individually_allocated")
    @classmethod
    def _no_individual_walkons(cls, v: bool) -> bool:
        if v:
            raise ValueError("Walk-on demand cannot be individually allocated; must contribute to buffers only")
        return v


class PriorityPolicy(_BaseConfig):
    tiers: dict[str, TierDefinition]
    factor_weights: FactorWeights
    age_scoring: AgeScoringConfig
    ageing: AgeingConfig
    escalation: EscalationConfig
    group_policy: GroupPolicyConfig
    reserved_vs_unreserved: ReservedVsUnreservedConfig
    walk_on_policy: WalkOnPolicyConfig
    _note: str | None = None

    @model_validator(mode="after")
    def _validate_tiers(self) -> PriorityPolicy:
        required = {"0", "1", "2"}
        if not required.issubset(self.tiers.keys()):
            raise ValueError(f"Policy must define tiers '0', '1', and '2', got {list(self.tiers.keys())}")
        ranks = {t.rank for t in self.tiers.values()}
        if ranks != {0, 1, 2}:
            raise ValueError(f"Tiers must define ranks 0, 1, 2, got {ranks}")
        return self


_CACHED_POLICY: PriorityPolicy | None = None


def get_default_policy_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "priority_policy.json"


def load_priority_policy(config_path: Path | str | None = None, reload: bool = False) -> PriorityPolicy:
    global _CACHED_POLICY
    if _CACHED_POLICY is not None and not reload and config_path is None:
        return _CACHED_POLICY
    path = Path(config_path) if config_path else get_default_policy_path()
    if not path.is_file():
        raise FileNotFoundError(f"Priority policy configuration file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    policy = PriorityPolicy.model_validate(data)
    if config_path is None:
        _CACHED_POLICY = policy
    return policy
