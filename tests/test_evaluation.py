from pathlib import Path

import pytest

from app.campaigns import get_campaign
from app.evaluation import dashboard_metrics, run_evaluation
from app.llm import LLMClient
from app.models import ContentReviewResult
from app.outreach import _knowledge
from app.reviews import ReviewSubmission, create_content_review


CASES_PATH = Path("data/evaluation_cases.json")
ALL_ISSUE_LABELS = [
    "missing_disclosure",
    "missing_product",
    "medical_claim",
    "missing_link",
    "late_publish",
    "unsupported_battery_claim",
    "missing_visible_product",
]


def test_mock_evaluation_is_repeatable_and_complete(db, settings):
    llm = LLMClient(settings, db)

    first = run_evaluation(db, llm, CASES_PATH)
    second = run_evaluation(db, llm, CASES_PATH)

    assert first.match_top1_hit_rate == second.match_top1_hit_rate == 1
    assert first.issue_recall == second.issue_recall == 1
    assert first.issue_precision == second.issue_precision == 1
    assert first.review_exact_match_rate == second.review_exact_match_rate == 1
    assert first.schema_success_rate == second.schema_success_rate
    assert first.total_match_cases == 10
    assert first.total_review_cases == 10
    assert 0 <= first.match_top1_hit_rate <= 1
    assert 0 <= first.issue_recall <= 1
    assert first.schema_success_rate == 1


def test_constant_scores_do_not_get_full_matching_credit(db, settings, monkeypatch):
    llm = LLMClient(settings, db)
    rank_creator = llm.rank_creator
    monkeypatch.setattr(
        llm,
        "rank_creator",
        lambda *args: rank_creator(*args).model_copy(update={"score": 0}),
    )

    report = run_evaluation(db, llm, CASES_PATH)

    assert report.match_top1_hit_rate < 1
    assert report.schema_success_rate == 1


def test_reporting_every_label_does_not_get_full_review_credit(db, settings, monkeypatch):
    llm = LLMClient(settings, db)
    review_content = llm.review_content
    monkeypatch.setattr(
        llm,
        "review_content",
        lambda *args: review_content(*args).model_copy(
            update={"issue_labels": ALL_ISSUE_LABELS}
        ),
    )

    report = run_evaluation(db, llm, CASES_PATH)

    assert report.issue_recall == 1
    assert report.issue_precision == pytest.approx(9 / 70)
    assert report.review_exact_match_rate == 0


def test_false_alarms_on_both_valid_deliveries_lower_review_scores(db, settings, monkeypatch):
    llm = LLMClient(settings, db)
    review_content = llm.review_content

    def add_false_alarm(*args):
        result = review_content(*args)
        if not result.issue_labels:
            return result.model_copy(update={"issue_labels": ["missing_disclosure"]})
        return result

    monkeypatch.setattr(llm, "review_content", add_false_alarm)

    report = run_evaluation(db, llm, CASES_PATH)

    assert report.issue_recall == 1
    assert report.issue_precision == pytest.approx(9 / 11)
    assert report.review_exact_match_rate == 0.8


def test_dashboard_counts_risk_only_reviews_as_needing_verification(db):
    for labels, risks in [
        ([], ["Check the product shot manually"]),
        (["medical_claim"], []),
        ([], []),
    ]:
        result = ContentReviewResult(
            passed_checks=[],
            missing_requirements=[],
            issue_labels=labels,
            risks=risks,
            suggestions=[],
            sources=[],
        )
        db.execute(
            "INSERT INTO content_reviews (campaign_id, submission_content, result_json) "
            "VALUES (1, ?, ?)",
            ("A delivery requiring review", result.model_dump_json()),
        )
    db.commit()

    assert dashboard_metrics(db, 1)["reviews_with_risks"] == 2


def test_evaluation_page_explains_metrics_and_final_validation(client):
    response = client.post("/evaluate")

    assert response.status_code == 200
    assert "Top-1 命中率" in response.text
    assert "问题标签精确率" in response.text
    assert "审核标签完全一致率" in response.text
    assert "最终结构化输出成功率" in response.text
    assert "不是首次响应正确率" in response.text


def test_evaluation_uses_workflow_knowledge_without_adding_business_reviews(db, settings, monkeypatch):
    llm = LLMClient(settings, db)
    rank_creator = llm.rank_creator
    review_content = llm.review_content
    match_contexts = []
    review_contexts = []

    def record_match(campaign, creator, knowledge):
        match_contexts.append(knowledge)
        return rank_creator(campaign, creator, knowledge)

    def record_review(campaign, content, metadata, knowledge):
        review_contexts.append(knowledge)
        return review_content(campaign, content, metadata, knowledge)

    monkeypatch.setattr(llm, "rank_creator", record_match)
    monkeypatch.setattr(llm, "review_content", record_review)
    expected_match_context = _knowledge(db, get_campaign(db, 1))
    create_content_review(
        db,
        1,
        ReviewSubmission(content="#ad LumaSip appears in the first 5 seconds."),
        llm,
    )
    expected_review_context = review_contexts.pop()

    run_evaluation(db, llm, CASES_PATH)

    assert db.execute("SELECT COUNT(*) FROM content_reviews").fetchone()[0] == 1
    assert len(review_contexts) == 10
    assert all(context == expected_review_context for context in review_contexts)
    assert match_contexts
    assert all(context == expected_match_context for context in match_contexts)
