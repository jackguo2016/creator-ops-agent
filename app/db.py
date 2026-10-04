from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema)
    connection.commit()


def invalidate_campaign_results(connection: sqlite3.Connection, campaign_id: int) -> None:
    """Keep history, but stop actions based on changed campaign inputs."""
    connection.execute(
        """
        UPDATE matches SET eligible = 0, selected = 0, rule_score = NULL,
            llm_score = NULL, recommendation = '', reasons_json = '[]',
            evidence_json = '[]', risks_json = '[]', updated_at = CURRENT_TIMESTAMP
        WHERE campaign_id = ?
        """,
        (campaign_id,),
    )
    connection.execute(
        """
        UPDATE drafts SET status = 'stale', updated_at = CURRENT_TIMESTAMP
        WHERE campaign_id = ? AND status IN ('pending', 'approved')
        """,
        (campaign_id,),
    )


def initialize_demo(connection: sqlite3.Connection) -> None:
    init_db(connection)
    from app.campaigns import seed_demo_campaign
    from app.retrieval import seed_knowledge

    seed_demo_campaign(connection)
    seed_knowledge(
        connection, Path(__file__).parent.parent / "data" / "knowledge.json"
    )
