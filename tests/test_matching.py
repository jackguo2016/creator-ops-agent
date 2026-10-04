from app.campaigns import DEMO_CAMPAIGN
from app.matching import check_eligibility, score_creator, list_matches, refresh_rule_matches


BASE_CREATOR = {
    "id": 1,
    "country": "US",
    "platform": "TikTok",
    "category": "fitness",
    "followers": 100_000,
    "engagement_rate": 4.5,
    "estimated_fee": 900.0,
    "data_quality_status": "valid",
}


def test_hard_requirements_exclude_over_budget_creator():
    creator = {**BASE_CREATOR, "estimated_fee": 1_500.0}

    result = check_eligibility(DEMO_CAMPAIGN, creator)

    assert result.eligible is False
    assert "报价超过单人预算" in result.reasons


def test_category_mismatch_lowers_score_without_excluding():
    mismatched = score_creator(DEMO_CAMPAIGN, {**BASE_CREATOR, "category": "food"})
    aligned = score_creator(DEMO_CAMPAIGN, BASE_CREATOR)

    assert mismatched.score < aligned.score
    assert "类别非优先" in mismatched.notes
    assert mismatched.eligible is True


def test_match_list_uses_ai_score_when_available(db):
    from datetime import date
    from pathlib import Path
    from app.creators import parse_creator_csv, upsert_creators

    upsert_creators(db, parse_creator_csv(Path("data/creators.csv").read_bytes(), date(2026, 10, 3)))
    refresh_rule_matches(db, 1)
    eligible = db.execute("SELECT creator_id FROM matches WHERE eligible = 1 ORDER BY creator_id LIMIT 2").fetchall()
    first, second = [row[0] for row in eligible]
    db.execute("UPDATE matches SET llm_score = 0 WHERE eligible = 1")
    db.execute("UPDATE matches SET rule_score = 100, llm_score = 10 WHERE creator_id = ?", (first,))
    db.execute("UPDATE matches SET rule_score = 10, llm_score = 99 WHERE creator_id = ?", (second,))
    db.commit()

    assert list_matches(db, 1)[0]["creator_id"] == second
