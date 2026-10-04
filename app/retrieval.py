from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KnowledgeHit:
    id: int
    title: str
    source_label: str
    text: str
    rank: float


def seed_knowledge(connection: sqlite3.Connection, path: Path) -> int:
    documents = json.loads(path.read_text(encoding="utf-8"))
    with connection:
        for document in documents:
            connection.execute(
                """
                INSERT INTO knowledge_docs (
                    slug, title, doc_type, body, source_label, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    title = excluded.title,
                    doc_type = excluded.doc_type,
                    body = excluded.body,
                    source_label = excluded.source_label,
                    updated_at = excluded.updated_at
                """,
                (
                    document["slug"],
                    document["title"],
                    document["doc_type"],
                    document["body"],
                    document["source_label"],
                    document["updated_at"],
                ),
            )
            doc_id = connection.execute(
                "SELECT id FROM knowledge_docs WHERE slug = ?", (document["slug"],)
            ).fetchone()[0]
            connection.execute(
                "DELETE FROM knowledge_docs_fts WHERE doc_id = ?", (doc_id,)
            )
            connection.execute(
                """
                INSERT INTO knowledge_docs_fts (doc_id, title, body, source_label)
                VALUES (?, ?, ?, ?)
                """,
                (
                    doc_id,
                    document["title"],
                    document["body"],
                    document["source_label"],
                ),
            )
    return len(documents)


def _fts_query(text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", text.lower())
    return " OR ".join(f'"{token}"' for token in tokens if token)


def search_knowledge(
    connection: sqlite3.Connection, query: str, limit: int = 3
) -> list[KnowledgeHit]:
    match_query = _fts_query(query)
    if not match_query:
        return []
    rows = connection.execute(
        """
        SELECT knowledge_docs.id, knowledge_docs.title,
               knowledge_docs.source_label, knowledge_docs.body,
               bm25(knowledge_docs_fts) AS rank
        FROM knowledge_docs_fts
        JOIN knowledge_docs
          ON knowledge_docs.id = CAST(knowledge_docs_fts.doc_id AS INTEGER)
        WHERE knowledge_docs_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (match_query, min(max(limit, 1), 3)),
    ).fetchall()
    return [
        KnowledgeHit(
            id=row["id"],
            title=row["title"],
            source_label=row["source_label"],
            text=row["body"],
            rank=row["rank"],
        )
        for row in rows
    ]
