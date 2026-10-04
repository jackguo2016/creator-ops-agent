import json
from datetime import datetime, timezone

from app.llm import LLMClient
from app.reviews import ReviewSubmission, create_content_review, get_content_review


def test_review_flags_missing_disclosure_and_medical_claim(db, settings):
    campaign_id = db.execute("SELECT id FROM campaigns").fetchone()[0]
    review_id = create_content_review(
        db,
        campaign_id,
        ReviewSubmission(
            content="LumaSip cures dehydration. Link in profile.",
            link="https://example.test/lumasip",
            planned_publish_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        ),
        LLMClient(settings, db),
    )

    result = json.loads(get_content_review(db, review_id)["result_json"])

    assert "missing_disclosure" in result["issue_labels"]
    assert "medical_claim" in result["issue_labels"]
