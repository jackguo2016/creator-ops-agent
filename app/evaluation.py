from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.campaigns import DEMO_CAMPAIGN, get_campaign
from app.llm import LLMClient
from app.matching import score_creator
from app.models import CampaignInput
from app.outreach import _knowledge as match_knowledge
from app.reviews import review_knowledge


@dataclass(frozen=True)
class EvaluationReport:
    match_top1_hit_rate: float
    issue_recall: float
    issue_precision: float
    review_exact_match_rate: float
    schema_success_rate: float
    average_latency_ms: float
    estimated_cost_usd: float
    total_match_cases: int
    total_review_cases: int


def _campaign(overrides: dict) -> CampaignInput:
    values = DEMO_CAMPAIGN.model_dump(mode="json")
    values.update(overrides)
    return CampaignInput.model_validate(values)


def _creator(values: dict, index: int) -> dict:
    return {
        "id": index,
        "name": values.get("handle", f"Creator {index}").lstrip("@"),
        "handle": f"@creator{index}",
        "platform": "TikTok",
        "country": "US",
        "category": "fitness",
        "followers": 120_000,
        "engagement_rate": 4.0,
        "estimated_fee": 800,
        "currency": "USD",
        "data_quality_status": "valid",
        **values,
    }


def run_evaluation(
    connection: sqlite3.Connection, llm: LLMClient, cases_path: Path
) -> EvaluationReport:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    start_id = connection.execute(
        "SELECT COALESCE(MAX(id), 0) FROM model_runs"
    ).fetchone()[0]
    match_hits = 0
    label_hits = 0
    expected_labels = 0
    predicted_labels = 0
    exact_reviews = 0
    attempts = 0
    valid_results = 0

    for case in cases["match_cases"]:
        campaign = _campaign(case["campaign"])
        knowledge = match_knowledge(connection, campaign)
        ranked: list[tuple[int, str]] = []
        for index, raw_creator in enumerate(case["candidates"], 1):
            creator = _creator(raw_creator, index)
            rule = score_creator(campaign, creator)
            if not rule.eligible:
                continue
            creator["rule_score"] = rule.score
            attempts += 1
            try:
                result = llm.rank_creator(campaign, creator, knowledge)
            except Exception:
                continue
            valid_results += 1
            ranked.append((result.score, creator["handle"]))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if ranked and ranked[0][1] in case["expected_handles"]:
            match_hits += 1

    for case in cases["review_cases"]:
        campaign = _campaign({})
        knowledge = review_knowledge(connection, campaign)
        attempts += 1
        expected = set(case["expected_labels"])
        expected_labels += len(expected)
        try:
            result = llm.review_content(
                campaign,
                case["content"],
                {
                    "link": case["link"],
                    "planned_publish_at": datetime.fromisoformat(
                        case["planned_publish_at"].replace("Z", "+00:00")
                    ),
                },
                knowledge,
            )
        except Exception:
            continue
        valid_results += 1
        predicted = set(result.issue_labels)
        predicted_labels += len(predicted)
        label_hits += len(expected.intersection(predicted))
        exact_reviews += int(predicted == expected)

    run_stats = connection.execute(
        """
        SELECT COALESCE(AVG(elapsed_ms), 0),
               COALESCE(SUM(estimated_cost_usd), 0)
        FROM model_runs WHERE id > ?
        """,
        (start_id,),
    ).fetchone()
    match_count = len(cases["match_cases"])
    review_count = len(cases["review_cases"])
    return EvaluationReport(
        match_top1_hit_rate=match_hits / match_count if match_count else 0,
        issue_recall=label_hits / expected_labels if expected_labels else 1,
        issue_precision=(
            label_hits / predicted_labels if predicted_labels else float(not expected_labels)
        ),
        review_exact_match_rate=exact_reviews / review_count if review_count else 0,
        schema_success_rate=valid_results / attempts if attempts else 0,
        average_latency_ms=float(run_stats[0]),
        estimated_cost_usd=float(run_stats[1]),
        total_match_cases=match_count,
        total_review_cases=review_count,
    )


def dashboard_metrics(
    connection: sqlite3.Connection, campaign_id: int
) -> dict[str, int | float]:
    get_campaign(connection, campaign_id)
    reviews = [
        json.loads(row["result_json"])
        for row in connection.execute(
            "SELECT result_json FROM content_reviews WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchall()
    ]
    return {
        "total_creators": connection.execute(
            "SELECT COUNT(*) FROM creators"
        ).fetchone()[0],
        "eligible_candidates": connection.execute(
            "SELECT COUNT(*) FROM matches WHERE campaign_id = ? AND eligible = 1",
            (campaign_id,),
        ).fetchone()[0],
        "pending_drafts": connection.execute(
            "SELECT COUNT(*) FROM drafts WHERE campaign_id = ? AND status = 'pending'",
            (campaign_id,),
        ).fetchone()[0],
        "reviews_with_risks": sum(
            bool(review["issue_labels"] or review["risks"]) for review in reviews
        ),
        "recent_model_errors": connection.execute(
            "SELECT COUNT(*) FROM model_runs WHERE status = 'error'"
        ).fetchone()[0],
        "estimated_cost_usd": float(
            connection.execute(
                "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM model_runs"
            ).fetchone()[0]
        ),
    }


def recent_model_runs(
    connection: sqlite3.Connection, limit: int = 100
) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM model_runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
