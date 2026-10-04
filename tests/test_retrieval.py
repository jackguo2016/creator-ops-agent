from pathlib import Path

from app.retrieval import search_knowledge, seed_knowledge


def test_retrieval_returns_product_and_disclosure_sources(db):
    seed_knowledge(db, Path("data/knowledge.json"))

    hits = search_knowledge(db, "hydration bottle medical claims #ad", limit=3)

    assert len(hits) == 3
    labels = {hit.source_label for hit in hits}
    assert "LumaSip 产品事实" in labels
    assert "美国创作者披露规范" in labels


def test_empty_retrieval_query_returns_no_hits(db):
    seed_knowledge(db, Path("data/knowledge.json"))

    assert search_knowledge(db, "!!!", limit=3) == []
