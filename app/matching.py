from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.campaigns import get_campaign
from app.models import CampaignInput


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reasons: list[str]


@dataclass(frozen=True)
class RuleMatch:
    creator_id: int
    eligible: bool
    score: int
    notes: list[str]
    eligibility_reasons: list[str]


def check_eligibility(
    campaign: CampaignInput, creator: Mapping[str, Any]
) -> EligibilityResult:
    reasons: list[str] = []
    if str(creator.get("country", "")).upper() != campaign.market.upper():
        reasons.append("目标市场不匹配")
    allowed_platforms = {platform.lower() for platform in campaign.platforms}
    if str(creator.get("platform", "")).lower() not in allowed_platforms:
        reasons.append("目标平台不匹配")
    followers = int(creator.get("followers", -1))
    if not campaign.min_followers <= followers <= campaign.max_followers:
        reasons.append("粉丝量不在目标范围")
    if float(creator.get("estimated_fee", -1)) > campaign.max_fee:
        reasons.append("报价超过单人预算")
    if creator.get("data_quality_status", "valid") != "valid":
        reasons.append("数据质量未通过")
    required = ("country", "platform", "followers", "estimated_fee")
    if any(creator.get(key) in (None, "") for key in required):
        reasons.append("缺少关键字段")
    return EligibilityResult(eligible=not reasons, reasons=reasons)


def score_creator(campaign: CampaignInput, creator: Mapping[str, Any]) -> RuleMatch:
    eligibility = check_eligibility(campaign, creator)
    if not eligibility.eligible:
        return RuleMatch(
            creator_id=int(creator.get("id", 0)),
            eligible=False,
            score=0,
            notes=[],
            eligibility_reasons=eligibility.reasons,
        )

    score = 35.0
    notes: list[str] = []
    preferred_categories = {category.lower() for category in campaign.categories}
    if str(creator.get("category", "")).lower() in preferred_categories:
        score += 20
    else:
        notes.append("类别非优先")

    minimum = campaign.min_followers
    maximum = campaign.max_followers
    midpoint = (minimum + maximum) / 2
    half_range = max((maximum - minimum) / 2, 1)
    follower_fit = max(0.0, 1 - abs(float(creator["followers"]) - midpoint) / half_range)
    score += 15 * follower_fit

    engagement = max(0.0, min(float(creator["engagement_rate"]) / 6.0, 1.0))
    score += 15 * engagement

    if campaign.max_fee > 0:
        budget_headroom = max(
            0.0,
            min((campaign.max_fee - float(creator["estimated_fee"])) / campaign.max_fee, 1.0),
        )
        score += 15 * budget_headroom
    else:
        score += 15

    return RuleMatch(
        creator_id=int(creator.get("id", 0)),
        eligible=True,
        score=max(0, min(round(score), 100)),
        notes=notes,
        eligibility_reasons=[],
    )


def refresh_rule_matches(
    connection: sqlite3.Connection, campaign_id: int
) -> list[RuleMatch]:
    campaign = get_campaign(connection, campaign_id)
    creators = connection.execute("SELECT * FROM creators ORDER BY id").fetchall()
    results = [score_creator(campaign, dict(creator)) for creator in creators]
    with connection:
        for result in results:
            connection.execute(
                """
                INSERT INTO matches (
                    campaign_id, creator_id, eligible, eligibility_reasons_json,
                    rule_score, updated_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(campaign_id, creator_id) DO UPDATE SET
                    eligible = excluded.eligible,
                    eligibility_reasons_json = excluded.eligibility_reasons_json,
                    rule_score = excluded.rule_score,
                    llm_score = NULL,
                    recommendation = '',
                    reasons_json = '[]',
                    evidence_json = '[]',
                    risks_json = '[]',
                    selected = CASE WHEN excluded.eligible = 0 THEN 0 ELSE matches.selected END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    campaign_id,
                    result.creator_id,
                    int(result.eligible),
                    json.dumps(result.eligibility_reasons, ensure_ascii=False),
                    result.score,
                ),
            )
        connection.execute(
            """
            UPDATE drafts SET status = 'stale', updated_at = CURRENT_TIMESTAMP
            WHERE campaign_id = ? AND status IN ('pending', 'approved')
              AND creator_id IN (SELECT creator_id FROM matches WHERE campaign_id = ? AND eligible = 0)
            """,
            (campaign_id, campaign_id),
        )
    return results


def ensure_rule_matches(connection: sqlite3.Connection, campaign_id: int) -> None:
    get_campaign(connection, campaign_id)
    count, incomplete = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(rule_score IS NULL), 0) FROM matches WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    creator_count = connection.execute("SELECT COUNT(*) FROM creators").fetchone()[0]
    if count != creator_count or incomplete:
        refresh_rule_matches(connection, campaign_id)


def list_matches(
    connection: sqlite3.Connection, campaign_id: int
) -> list[sqlite3.Row]:
    ensure_rule_matches(connection, campaign_id)
    return connection.execute(
        """
        SELECT matches.*, creators.name, creators.handle, creators.platform,
               creators.country, creators.category, creators.followers,
               creators.engagement_rate, creators.estimated_fee, creators.currency
        FROM matches
        JOIN creators ON creators.id = matches.creator_id
        WHERE matches.campaign_id = ?
        ORDER BY matches.eligible DESC, COALESCE(matches.llm_score, matches.rule_score) DESC,
                 matches.rule_score DESC, creators.followers DESC, creators.id
        """,
        (campaign_id,),
    ).fetchall()
