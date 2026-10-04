import json
from dataclasses import replace

import httpx
import pytest

from app.campaigns import DEMO_CAMPAIGN
from app.llm import LLMClient, LLMError
from app.retrieval import KnowledgeHit


CREATOR = {
    "id": 7,
    "name": "Maya Moves",
    "handle": "@mayamoves",
    "platform": "TikTok",
    "country": "US",
    "category": "fitness",
    "followers": 91_000,
    "engagement_rate": 5.0,
    "estimated_fee": 950.0,
    "rule_score": 82,
}

KNOWLEDGE = [
    KnowledgeHit(
        id=1,
        title="Product facts",
        source_label="LumaSip 产品事实",
        text="LumaSip has a 14-day battery.",
        rank=-1.0,
    )
]


class SequenceTransport(httpx.BaseTransport):
    def __init__(self, responses: list[httpx.Response]):
        self.responses = responses
        self.calls = 0
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses[self.calls]
        self.calls += 1
        return response


def _api_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
        },
    )


def test_mock_match_is_deterministic_and_logged(db, settings):
    llm = LLMClient(settings, db)

    first = llm.rank_creator(DEMO_CAMPAIGN, CREATOR, KNOWLEDGE)
    second = llm.rank_creator(DEMO_CAMPAIGN, CREATOR, KNOWLEDGE)

    assert first == second
    assert 0 <= first.score <= 100
    assert first.evidence == ["LumaSip 产品事实"]
    assert db.execute("SELECT COUNT(*) FROM model_runs").fetchone()[0] == 2


def test_deepseek_retries_one_invalid_json_response(db, settings):
    valid = json.dumps(
        {
            "score": 88,
            "recommendation": "Strong fit",
            "reasons": ["US fitness audience"],
            "evidence": ["LumaSip 产品事实"],
            "risks": ["Confirm final quote"],
        }
    )
    transport = SequenceTransport([_api_response("not json"), _api_response(valid)])
    deepseek_settings = replace(
        settings,
        llm_provider="deepseek",
        deepseek_api_key="sk-test-only",
    )

    result = LLMClient(deepseek_settings, db, transport).rank_creator(
        DEMO_CAMPAIGN, CREATOR, KNOWLEDGE
    )

    assert result.score == 88
    assert transport.calls == 2
    run = db.execute("SELECT * FROM model_runs ORDER BY id DESC LIMIT 1").fetchone()
    assert run["status"] == "success"
    assert run["input_tokens"] == 2000
    assert run["output_tokens"] == 400
    assert run["estimated_cost_usd"] == pytest.approx(0.00108)


def test_deepseek_disables_thinking_for_low_cost_tasks(db, settings):
    content = json.dumps(
        {
            "score": 88,
            "recommendation": "Strong fit",
            "reasons": ["US fitness audience"],
            "evidence": ["LumaSip 产品事实"],
            "risks": [],
        }
    )
    transport = SequenceTransport([_api_response(content)])
    deepseek_settings = replace(
        settings,
        llm_provider="deepseek",
        deepseek_api_key="sk-test-only",
    )

    LLMClient(deepseek_settings, db, transport).rank_creator(
        DEMO_CAMPAIGN, CREATOR, KNOWLEDGE
    )

    payload = json.loads(transport.requests[0].content)
    assert payload["thinking"] == {"type": "disabled"}


def test_content_review_retries_noncanonical_issue_labels(db, settings):
    invalid = json.dumps(
        {
            "passed_checks": [],
            "missing_requirements": ["Add disclosure"],
            "issue_labels": ["Missing #ad disclosure"],
            "risks": [],
            "suggestions": ["Add #ad"],
            "sources": ["LumaSip 产品事实"],
        }
    )
    valid = json.dumps(
        {
            "passed_checks": [],
            "missing_requirements": ["Add disclosure"],
            "issue_labels": ["missing_disclosure"],
            "risks": [],
            "suggestions": ["Add #ad"],
            "sources": ["LumaSip 产品事实"],
        }
    )
    transport = SequenceTransport([_api_response(invalid), _api_response(valid)])
    deepseek_settings = replace(
        settings,
        llm_provider="deepseek",
        deepseek_api_key="sk-test-only",
    )

    result = LLMClient(deepseek_settings, db, transport).review_content(
        DEMO_CAMPAIGN,
        "LumaSip needs disclosure",
        {"link": "https://example.test", "planned_publish_at": "2026-11-01"},
        KNOWLEDGE,
    )

    assert result.issue_labels == ["missing_disclosure"]
    assert transport.calls == 2


def test_final_invalid_output_failure_keeps_all_received_usage(db, settings):
    transport = SequenceTransport([_api_response("not json"), _api_response("not json")])
    llm = LLMClient(
        replace(settings, llm_provider="deepseek", deepseek_api_key="sk-test-only"),
        db,
        transport,
    )

    with pytest.raises(LLMError):
        llm.rank_creator(DEMO_CAMPAIGN, CREATOR, KNOWLEDGE)

    run = db.execute("SELECT * FROM model_runs").fetchone()
    assert run["status"] == "error"
    assert run["input_tokens"] == 2000
    assert run["output_tokens"] == 400
    assert run["estimated_cost_usd"] == pytest.approx(0.00108)


@pytest.mark.parametrize("choices", [[], None, [None], [{"message": None}]])
def test_malformed_choices_fail_with_a_logged_controlled_error(db, settings, choices):
    responses = [
        httpx.Response(
            200,
            json={"choices": choices, "usage": {"prompt_tokens": 1000, "completion_tokens": 200}},
        )
        for _ in range(2)
    ]
    transport = SequenceTransport(responses)
    llm = LLMClient(
        replace(settings, llm_provider="deepseek", deepseek_api_key="sk-test-only"),
        db,
        transport,
    )

    with pytest.raises(LLMError):
        llm.rank_creator(DEMO_CAMPAIGN, CREATOR, KNOWLEDGE)

    run = db.execute("SELECT * FROM model_runs").fetchone()
    assert run["status"] == "error"
    assert run["input_tokens"] == 2000
    assert run["output_tokens"] == 400


@pytest.mark.parametrize("purpose", ["match", "review"])
def test_model_cannot_cite_a_source_outside_supplied_knowledge(db, settings, purpose):
    if purpose == "match":
        result = {
            "score": 88, "recommendation": "Strong fit", "reasons": ["US audience"],
            "evidence": ["Invented FDA certificate"], "risks": [],
        }
    else:
        result = {
            "passed_checks": [], "missing_requirements": [], "issue_labels": [],
            "risks": [], "suggestions": [], "sources": ["Invented FDA certificate"],
        }
    transport = SequenceTransport([_api_response(json.dumps(result)) for _ in range(2)])
    llm = LLMClient(
        replace(settings, llm_provider="deepseek", deepseek_api_key="sk-test-only"),
        db,
        transport,
    )

    with pytest.raises(LLMError):
        if purpose == "match":
            llm.rank_creator(DEMO_CAMPAIGN, CREATOR, KNOWLEDGE)
        else:
            llm.review_content(DEMO_CAMPAIGN, "#ad LumaSip", {}, KNOWLEDGE)

    assert db.execute("SELECT status FROM model_runs").fetchone()[0] == "error"


def test_empty_knowledge_mock_uses_explicit_campaign_brief_fallback(db, settings):
    llm = LLMClient(settings, db)

    match = llm.rank_creator(DEMO_CAMPAIGN, CREATOR, [])
    review = llm.review_content(DEMO_CAMPAIGN, "#ad LumaSip", {}, [])

    assert match.evidence == ["项目 Brief"]
    assert review.sources == ["项目 Brief"]


def test_error_summary_does_not_echo_generated_content_or_validation_input(db, settings):
    private_output = "PRIVATE_CREATOR_EMAIL"
    transport = SequenceTransport([_api_response(private_output) for _ in range(2)])
    llm = LLMClient(
        replace(settings, llm_provider="deepseek", deepseek_api_key="sk-test-only"),
        db,
        transport,
    )

    with pytest.raises(LLMError) as failure:
        llm.generate_outreach(DEMO_CAMPAIGN, CREATOR, KNOWLEDGE)

    summary = db.execute("SELECT error_summary FROM model_runs").fetchone()[0]
    assert private_output not in summary
    assert "input_value" not in summary
    assert "PRIVATE" not in str(failure.value)


def test_mock_outreach_and_product_check_use_current_campaign_brand(db, settings):
    campaign = DEMO_CAMPAIGN.model_copy(update={"brand": "NewBottle"})
    llm = LLMClient(settings, db)

    draft = llm.generate_outreach(campaign, CREATOR, [])
    review = llm.review_content(campaign, "#ad NewBottle appears in the first 5 seconds.", {}, [])
    missing = llm.review_content(campaign, "#ad An unnamed bottle", {}, [])

    assert draft.subject.startswith("NewBottle collaboration")
    assert "missing_product" not in review.issue_labels
    assert "Mention NewBottle" in missing.missing_requirements


def test_http_error_keeps_reported_usage_and_hides_url_credentials(db, settings):
    transport = SequenceTransport([
        httpx.Response(500, json={"usage": {"prompt_tokens": 1000, "completion_tokens": 200}})
        for _ in range(2)
    ])
    llm = LLMClient(
        replace(
            settings, llm_provider="deepseek", deepseek_api_key="sk-test-only",
            deepseek_base_url="https://example.test/private-credential",
        ),
        db,
        transport,
    )

    with pytest.raises(LLMError) as failure:
        llm.generate_outreach(DEMO_CAMPAIGN, CREATOR, KNOWLEDGE)

    run = db.execute("SELECT * FROM model_runs").fetchone()
    assert run["input_tokens"] == 2000
    assert run["estimated_cost_usd"] == pytest.approx(0.00108)
    assert "500" in run["error_summary"]
    assert "private-credential" not in run["error_summary"]
    assert "sk-test-only" not in str(failure.value)


def test_missing_usage_is_marked_unknown_in_the_log(db, settings):
    result = {"subject": "Hello", "body": "Please confirm your quote.", "brief": "One video"}
    transport = SequenceTransport([httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(result)}}],
    })])
    llm = LLMClient(
        replace(settings, llm_provider="deepseek", deepseek_api_key="sk-test-only"),
        db,
        transport,
    )

    llm.generate_outreach(DEMO_CAMPAIGN, CREATOR, KNOWLEDGE)

    run = db.execute("SELECT * FROM model_runs").fetchone()
    assert run["status"] == "success"
    assert "usage_unknown" in run["error_summary"]


@pytest.mark.parametrize("usage, input_tokens, output_tokens, cost", [
    ({"prompt_tokens": 1000, "completion_tokens": "invalid"}, 2000, 0, 0.0006),
    ({"prompt_tokens": "invalid", "completion_tokens": 200}, 0, 400, 0.00048),
])
def test_partially_invalid_usage_keeps_known_tokens_and_matching_cost(
    db, settings, usage, input_tokens, output_tokens, cost
):
    transport = SequenceTransport([httpx.Response(200, json={
        "usage": usage,
    }) for _ in range(2)])
    llm = LLMClient(
        replace(settings, llm_provider="deepseek", deepseek_api_key="sk-test-only"),
        db,
        transport,
    )

    with pytest.raises(LLMError):
        llm.generate_outreach(DEMO_CAMPAIGN, CREATOR, KNOWLEDGE)

    run = db.execute("SELECT * FROM model_runs").fetchone()
    assert run["input_tokens"] == input_tokens
    assert run["output_tokens"] == output_tokens
    assert run["estimated_cost_usd"] == pytest.approx(cost)
    assert "usage_unknown" in run["error_summary"]


@pytest.mark.parametrize("purpose", ["match", "review"])
def test_real_model_can_use_campaign_brief_only_when_knowledge_is_empty(db, settings, purpose):
    if purpose == "match":
        result = {
            "score": 88, "recommendation": "Strong fit", "reasons": ["US audience"],
            "evidence": ["项目 Brief"], "risks": [],
        }
    else:
        result = {
            "passed_checks": [], "missing_requirements": [], "issue_labels": [],
            "risks": [], "suggestions": [], "sources": ["项目 Brief"],
        }
    transport = SequenceTransport([_api_response(json.dumps(result)) for _ in range(3)])
    llm = LLMClient(
        replace(settings, llm_provider="deepseek", deepseek_api_key="sk-test-only"),
        db,
        transport,
    )

    def call(knowledge):
        if purpose == "match":
            return llm.rank_creator(DEMO_CAMPAIGN, CREATOR, knowledge)
        return llm.review_content(DEMO_CAMPAIGN, "#ad LumaSip", {}, knowledge)

    call([])
    with pytest.raises(LLMError):
        call(KNOWLEDGE)


@pytest.mark.parametrize("field", ["prompt_tokens", "completion_tokens"])
@pytest.mark.parametrize("value", [2**63, 10**400], ids=["int64-overflow", "float-overflow"])
def test_oversized_usage_cannot_overflow_model_log(db, settings, field, value):
    usage = {"prompt_tokens": 1000, "completion_tokens": 200, field: value}
    transport = SequenceTransport([httpx.Response(200, json={"usage": usage}) for _ in range(2)])
    llm = LLMClient(replace(settings, llm_provider="deepseek", deepseek_api_key="test-only"), db, transport)

    with pytest.raises(LLMError):
        llm.generate_outreach(DEMO_CAMPAIGN, CREATOR, KNOWLEDGE)

    run = db.execute("SELECT * FROM model_runs").fetchone()
    assert run["status"] == "error"
    assert "usage_unknown" in run["error_summary"]
    assert (run["input_tokens"], run["output_tokens"]) == ((0, 400) if field == "prompt_tokens" else (2000, 0))
