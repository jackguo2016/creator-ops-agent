from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.campaigns import get_campaign
from app.llm import LLMClient
from app.models import CampaignInput
from app.retrieval import KnowledgeHit, search_knowledge


class ReviewSubmission(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=20_000)
    link: str | None = Field(default=None, max_length=2_000)
    planned_publish_at: datetime | None = None


def review_knowledge(
    connection: sqlite3.Connection, campaign: CampaignInput
) -> list[KnowledgeHit]:
    return search_knowledge(
        connection,
        f"{campaign.brand} disclosure medical claims content delivery {campaign.restrictions}",
    )


def create_content_review(
    connection: sqlite3.Connection,
    campaign_id: int,
    submission: ReviewSubmission,
    llm: LLMClient,
) -> int:
    campaign = get_campaign(connection, campaign_id)
    knowledge = review_knowledge(connection, campaign)
    result = llm.review_content(
        campaign,
        submission.content,
        {
            "link": submission.link,
            "planned_publish_at": submission.planned_publish_at,
        },
        knowledge,
    )
    with connection:
        cursor = connection.execute(
            """
            INSERT INTO content_reviews (
                campaign_id, submission_content, submission_link,
                planned_publish_at, result_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                submission.content,
                submission.link,
                submission.planned_publish_at.isoformat()
                if submission.planned_publish_at
                else None,
                result.model_dump_json(),
            ),
        )
    return int(cursor.lastrowid)


def get_content_review(
    connection: sqlite3.Connection, review_id: int
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM content_reviews WHERE id = ?", (review_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"review {review_id} not found")
    return row


def list_content_reviews(
    connection: sqlite3.Connection, campaign_id: int
) -> list[dict]:
    rows = connection.execute(
        """
        SELECT * FROM content_reviews
        WHERE campaign_id = ? ORDER BY id DESC
        """,
        (campaign_id,),
    ).fetchall()
    return [{**dict(row), "result": json.loads(row["result_json"])} for row in rows]
