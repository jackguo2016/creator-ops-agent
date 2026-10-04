from __future__ import annotations

import json
import sqlite3

from app.models import Campaign, CampaignInput
from app.db import invalidate_campaign_results


class CampaignNotFoundError(LookupError):
    pass


DEMO_CAMPAIGN = CampaignInput(
    brand="LumaSip",
    name="LumaSip 美国创作者启动项目",
    market="US",
    language="English",
    platforms=["TikTok", "YouTube"],
    categories=["fitness", "tech"],
    min_followers=20_000,
    max_followers=500_000,
    max_fee=1_200,
    total_budget=6_000,
    deadline="2026-11-15",
    deliverables="1 short video; profile link for 7 days",
    restrictions="Include #ad; no medical claims; show the product in the first 5 seconds",
    brief_text=(
        "Launch the LumaSip smart hydration bottle for active US consumers. "
        "Highlight hydration reminders, the 14-day battery, and IPX7 water resistance."
    ),
)


def _split_json(value: str) -> list[str]:
    parsed = json.loads(value)
    return [str(item) for item in parsed]


def _row_to_campaign(row: sqlite3.Row) -> Campaign:
    return Campaign(
        id=row["id"],
        brand=row["brand"],
        name=row["name"],
        market=row["market"],
        language=row["language"],
        platforms=_split_json(row["platforms_json"]),
        categories=_split_json(row["categories_json"]),
        min_followers=row["min_followers"],
        max_followers=row["max_followers"],
        max_fee=row["max_fee"],
        total_budget=row["total_budget"],
        deadline=row["deadline"],
        deliverables=row["deliverables"],
        restrictions=row["restrictions"],
        brief_text=row["brief_text"],
        status=row["status"],
    )


def seed_demo_campaign(connection: sqlite3.Connection) -> int:
    existing = connection.execute("SELECT id FROM campaigns LIMIT 1").fetchone()
    if existing:
        return int(existing["id"])
    values = DEMO_CAMPAIGN
    cursor = connection.execute(
        """
        INSERT INTO campaigns (
            brand, name, market, language, platforms_json, categories_json,
            min_followers, max_followers, max_fee, total_budget, deadline,
            deliverables, restrictions, brief_text, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (
            values.brand,
            values.name,
            values.market,
            values.language,
            json.dumps(values.platforms, ensure_ascii=False),
            json.dumps(values.categories, ensure_ascii=False),
            values.min_followers,
            values.max_followers,
            values.max_fee,
            values.total_budget,
            values.deadline.isoformat(),
            values.deliverables,
            values.restrictions,
            values.brief_text,
        ),
    )
    connection.commit()
    return int(cursor.lastrowid)


def get_campaign(connection: sqlite3.Connection, campaign_id: int) -> Campaign:
    row = connection.execute(
        "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if row is None:
        raise CampaignNotFoundError(f"campaign {campaign_id} not found")
    return _row_to_campaign(row)


def update_campaign(
    connection: sqlite3.Connection, campaign_id: int, data: CampaignInput
) -> Campaign:
    current = get_campaign(connection, campaign_id)
    changed = any(getattr(current, key) != value for key, value in data.model_dump().items())
    cursor = connection.execute(
        """
        UPDATE campaigns
        SET brand = ?, name = ?, market = ?, language = ?, platforms_json = ?,
            categories_json = ?, min_followers = ?, max_followers = ?, max_fee = ?,
            total_budget = ?, deadline = ?, deliverables = ?, restrictions = ?,
            brief_text = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            data.brand,
            data.name,
            data.market,
            data.language,
            json.dumps(data.platforms, ensure_ascii=False),
            json.dumps(data.categories, ensure_ascii=False),
            data.min_followers,
            data.max_followers,
            data.max_fee,
            data.total_budget,
            data.deadline.isoformat(),
            data.deliverables,
            data.restrictions,
            data.brief_text,
            campaign_id,
        ),
    )
    if cursor.rowcount != 1:
        raise CampaignNotFoundError(f"campaign {campaign_id} not found")
    if changed:
        invalidate_campaign_results(connection, campaign_id)
    connection.commit()
    return get_campaign(connection, campaign_id)
