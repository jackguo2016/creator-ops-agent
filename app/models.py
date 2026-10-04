from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CampaignInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

    brand: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    market: str = Field(min_length=2, max_length=80)
    language: str = Field(min_length=2, max_length=80)
    platforms: list[str] = Field(min_length=1)
    categories: list[str] = Field(min_length=1)
    min_followers: int = Field(ge=0, le=2**63 - 1)
    max_followers: int = Field(ge=0, le=2**63 - 1)
    max_fee: float = Field(ge=0)
    total_budget: float = Field(ge=0)
    deadline: date
    deliverables: str = Field(min_length=1, max_length=4000)
    restrictions: str = Field(min_length=1, max_length=4000)
    brief_text: str = Field(min_length=1, max_length=12000)

    @model_validator(mode="after")
    def follower_range_is_ordered(self) -> "CampaignInput":
        if self.max_followers < self.min_followers:
            raise ValueError("粉丝数上限不能低于下限")
        return self


class Campaign(CampaignInput):
    id: int
    status: str


class StrictResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MatchExplanation(StrictResult):
    score: int = Field(ge=0, le=100)
    recommendation: str = Field(min_length=1, max_length=1200)
    reasons: list[str] = Field(min_length=1, max_length=6)
    evidence: list[str] = Field(min_length=1, max_length=6)
    risks: list[str] = Field(max_length=6)


class OutreachDraftResult(StrictResult):
    subject: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=8000)
    brief: str = Field(min_length=1, max_length=8000)


ReviewIssueLabel = Literal[
    "missing_disclosure",
    "missing_product",
    "medical_claim",
    "missing_link",
    "late_publish",
    "unsupported_battery_claim",
    "missing_visible_product",
]


class ContentReviewResult(StrictResult):
    passed_checks: list[str] = Field(max_length=12)
    missing_requirements: list[str] = Field(max_length=12)
    issue_labels: list[ReviewIssueLabel] = Field(max_length=12)
    risks: list[str] = Field(max_length=12)
    suggestions: list[str] = Field(max_length=12)
    sources: list[str] = Field(max_length=6)
