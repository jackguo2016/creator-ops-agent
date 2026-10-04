from __future__ import annotations

import json
import sqlite3

from app.campaigns import get_campaign
from app.llm import LLMClient
from app.matching import check_eligibility, ensure_rule_matches
from app.models import Campaign
from app.retrieval import search_knowledge


def _knowledge(connection: sqlite3.Connection, campaign) -> list:
    return search_knowledge(
        connection,
        f"{campaign.brand} {campaign.market} {campaign.deliverables} {campaign.restrictions}",
    )


def _check_generation_inputs(connection: sqlite3.Connection, campaign: Campaign, creator: sqlite3.Row) -> sqlite3.Row:
    # Lock only after the model returns, never while waiting on its network request.
    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    current_creator = connection.execute("SELECT * FROM creators WHERE id = ?", (creator["id"],)).fetchone()
    match = connection.execute(
        "SELECT eligible, selected, rule_score FROM matches WHERE campaign_id = ? AND creator_id = ?",
        (campaign.id, creator["id"]),
    ).fetchone()
    if (
        get_campaign(connection, campaign.id) != campaign
        or current_creator is None
        or any(current_creator[key] != creator[key] for key in current_creator.keys() if key not in {"created_at", "updated_at"})
        or match is None
        or not match["eligible"]
        or match["rule_score"] is None
    ):
        raise ValueError("模型生成期间项目或创作者资料已变化，请重新筛选后再试")
    return match


def rank_eligible_matches(
    connection: sqlite3.Connection, campaign_id: int, llm: LLMClient
) -> int:
    campaign = get_campaign(connection, campaign_id)
    ensure_rule_matches(connection, campaign_id)
    rows = connection.execute(
        """
        SELECT matches.rule_score, creators.*
        FROM matches JOIN creators ON creators.id = matches.creator_id
        WHERE matches.campaign_id = ? AND matches.eligible = 1
        ORDER BY matches.rule_score DESC
        """,
        (campaign_id,),
    ).fetchall()
    knowledge = _knowledge(connection, campaign)
    ranked_count = 0
    for row in rows:
        if not check_eligibility(campaign, dict(row)).eligible:
            continue
        result = llm.rank_creator(campaign, dict(row), knowledge)
        with connection:
            _check_generation_inputs(connection, campaign, row)
            connection.execute(
                """
                UPDATE matches SET llm_score = ?, recommendation = ?, reasons_json = ?,
                    evidence_json = ?, risks_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE campaign_id = ? AND creator_id = ?
                """,
                (
                    result.score,
                    result.recommendation,
                    json.dumps(result.reasons, ensure_ascii=False),
                    json.dumps(result.evidence, ensure_ascii=False),
                    json.dumps(result.risks, ensure_ascii=False),
                    campaign_id,
                    row["id"],
                ),
            )
        ranked_count += 1
    return ranked_count


def select_creator(
    connection: sqlite3.Connection, campaign_id: int, creator_id: int
) -> None:
    ensure_rule_matches(connection, campaign_id)
    creator = connection.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone()
    if creator is None or not check_eligibility(get_campaign(connection, campaign_id), dict(creator)).eligible:
        raise ValueError("只能选择通过当前硬条件筛选的创作者")
    with connection:
        cursor = connection.execute(
            """
            UPDATE matches SET selected = 1, updated_at = CURRENT_TIMESTAMP
            WHERE campaign_id = ? AND creator_id = ? AND eligible = 1
            """,
            (campaign_id, creator_id),
        )
    if cursor.rowcount != 1:
        raise ValueError("只能选择通过硬条件筛选的创作者")


def create_outreach_draft(
    connection: sqlite3.Connection,
    campaign_id: int,
    creator_id: int,
    llm: LLMClient,
) -> int:
    campaign = get_campaign(connection, campaign_id)
    ensure_rule_matches(connection, campaign_id)
    creator = connection.execute(
        """
        SELECT creators.* FROM creators
        JOIN matches ON matches.creator_id = creators.id
        WHERE matches.campaign_id = ? AND creators.id = ?
          AND matches.eligible = 1 AND matches.selected = 1
        """,
        (campaign_id, creator_id),
    ).fetchone()
    if creator is None or not check_eligibility(campaign, dict(creator)).eligible:
        raise ValueError("请先选择通过筛选的创作者")
    result = llm.generate_outreach(
        campaign, dict(creator), _knowledge(connection, campaign)
    )
    with connection:
        match = _check_generation_inputs(connection, campaign, creator)
        if not match["selected"]:
            raise ValueError("创作者选择已变化，请重新选择后生成")
        cursor = connection.execute(
            """
            INSERT INTO drafts (
                campaign_id, creator_id, draft_type, subject, body, brief, status
            ) VALUES (?, ?, 'outreach', ?, ?, ?, 'pending')
            """,
            (campaign_id, creator_id, result.subject, result.body, result.brief),
        )
    return int(cursor.lastrowid)


def approve_draft(connection: sqlite3.Connection, draft_id: int) -> None:
    draft = connection.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if draft is None or draft["status"] != "pending":
        raise ValueError("只有当前有效的待批准草稿可以批准；失效草稿请重新生成")
    creator = connection.execute("SELECT * FROM creators WHERE id = ?", (draft["creator_id"],)).fetchone()
    match = connection.execute(
        "SELECT 1 FROM matches WHERE campaign_id = ? AND creator_id = ? AND eligible = 1 AND selected = 1 AND rule_score IS NOT NULL",
        (draft["campaign_id"], draft["creator_id"]),
    ).fetchone()
    if creator is None or match is None or not check_eligibility(get_campaign(connection, draft["campaign_id"]), dict(creator)).eligible:
        raise ValueError("创作者已不符合当前硬条件，请重新筛选")
    with connection:
        cursor = connection.execute(
            """
            UPDATE drafts SET status = 'approved', approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'pending'
            """,
            (draft_id,),
        )
    if cursor.rowcount != 1:
        raise ValueError("只有待批准草稿可以批准")


def list_selected_creators(
    connection: sqlite3.Connection, campaign_id: int
) -> list[sqlite3.Row]:
    ensure_rule_matches(connection, campaign_id)
    return connection.execute(
        """
        SELECT creators.*, matches.rule_score, matches.llm_score
        FROM matches JOIN creators ON creators.id = matches.creator_id
        WHERE matches.campaign_id = ? AND matches.selected = 1 AND matches.eligible = 1
        ORDER BY COALESCE(matches.llm_score, matches.rule_score) DESC
        """,
        (campaign_id,),
    ).fetchall()


def list_drafts(
    connection: sqlite3.Connection, campaign_id: int
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT drafts.*, creators.name, creators.handle
        FROM drafts JOIN creators ON creators.id = drafts.creator_id
        WHERE drafts.campaign_id = ? ORDER BY drafts.id DESC
        """,
        (campaign_id,),
    ).fetchall()
