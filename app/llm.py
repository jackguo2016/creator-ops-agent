from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.models import (
    CampaignInput,
    ContentReviewResult,
    MatchExplanation,
    OutreachDraftResult,
)
from app.retrieval import KnowledgeHit


ResultType = TypeVar("ResultType", bound=BaseModel)


class LLMError(RuntimeError):
    """A model call failed after the allowed retry."""


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        connection: sqlite3.Connection,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.connection = connection
        self.transport = transport

    def rank_creator(
        self,
        campaign: CampaignInput,
        creator: Mapping[str, Any],
        knowledge: Sequence[KnowledgeHit],
    ) -> MatchExplanation:
        sources = [hit.source_label for hit in knowledge[:3]] or ["项目 Brief"]
        base_score = int(creator.get("rule_score", 70))
        category_match = str(creator.get("category", "")).lower() in {
            item.lower() for item in campaign.categories
        }
        mock = MatchExplanation(
            score=max(0, min(base_score + (5 if category_match else -4), 100)),
            recommendation=(
                f"{creator.get('name', creator.get('handle', 'This creator'))} fits "
                f"the {campaign.market} {creator.get('platform', '')} campaign and "
                "should move to a human quote check."
            ),
            reasons=[
                f"Audience market: {creator.get('country', '')}",
                f"Category: {creator.get('category', '')}",
                f"Rule score: {base_score}",
            ],
            evidence=sources,
            risks=["Confirm availability and final quote before approval"],
        )
        payload = {
            "campaign": campaign.model_dump(mode="json"),
            "creator": dict(creator),
            "knowledge": self._knowledge_payload(knowledge),
            "allowed_sources": sources,
            "required_json": {
                "score": "integer 0-100",
                "recommendation": "string",
                "reasons": ["string"],
                "evidence": ["source label"],
                "risks": ["string"],
            },
        }
        return self._run(
            purpose="creator_match",
            result_type=MatchExplanation,
            payload=payload,
            mock_result=mock,
            system_prompt=(
                "You rank a creator for a marketing campaign. Use only supplied facts. "
                "Return one JSON object matching required_json. Evidence values must be "
                "labels from allowed_sources. When knowledge is empty, 项目 Brief refers "
                "to the supplied campaign facts."
            ),
        )

    def generate_outreach(
        self,
        campaign: CampaignInput,
        creator: Mapping[str, Any],
        knowledge: Sequence[KnowledgeHit],
    ) -> OutreachDraftResult:
        name = str(creator.get("name") or creator.get("handle") or "there")
        deliverables = campaign.deliverables
        mock = OutreachDraftResult(
            subject=f"{campaign.brand} collaboration opportunity for {name}",
            body=(
                f"Hi {name},\n\nWe are planning a {campaign.brand} campaign for "
                f"{campaign.market} audiences and think your {creator.get('category', '')} "
                "content could be a strong fit. The proposed deliverable is "
                f"{deliverables}. Please let us know your availability and current quote. "
                "Sponsored content must include a clear #ad disclosure.\n\nBest,\nCreator Partnerships"
            ),
            brief=(
                f"Brand: {campaign.brand}\nMarket: {campaign.market}\nDeliverables: "
                f"{deliverables}\nDeadline: {campaign.deadline.isoformat()}\n"
                f"Restrictions: {campaign.restrictions}"
            ),
        )
        payload = {
            "campaign": campaign.model_dump(mode="json"),
            "creator": dict(creator),
            "knowledge": self._knowledge_payload(knowledge),
            "required_json": {"subject": "string", "body": "string", "brief": "string"},
        }
        return self._run(
            purpose="outreach_draft",
            result_type=OutreachDraftResult,
            payload=payload,
            mock_result=mock,
            system_prompt=(
                "Write concise professional English creator outreach. Do not promise final "
                "acceptance or invent product facts. Return one JSON object matching required_json."
            ),
        )

    def review_content(
        self,
        campaign: CampaignInput,
        content: str,
        metadata: Mapping[str, Any],
        knowledge: Sequence[KnowledgeHit],
    ) -> ContentReviewResult:
        lowered = content.lower()
        passed: list[str] = []
        missing: list[str] = []
        labels: list[str] = []
        risks: list[str] = []
        suggestions: list[str] = []

        if "#ad" in lowered:
            passed.append("Disclosure is present")
        else:
            missing.append("Add a visible #ad disclosure")
            labels.append("missing_disclosure")
            suggestions.append("Add #ad near the beginning of the caption")
        if campaign.brand.lower() in lowered:
            passed.append("Product name is present")
        else:
            missing.append(f"Mention {campaign.brand}")
            labels.append("missing_product")
        medical_terms = ("cure", "treat", "prevent disease", "治疗", "治愈")
        if any(term in lowered for term in medical_terms):
            labels.append("medical_claim")
            risks.append("Unsupported medical or treatment claim")
            suggestions.append("Replace the claim with verified product facts")
        else:
            passed.append("No prohibited medical claim detected")
        if metadata.get("link"):
            passed.append("Delivery link is present")
        else:
            missing.append("Provide the delivery link")
            labels.append("missing_link")
        publish_at = metadata.get("planned_publish_at")
        if publish_at:
            publish_date = self._as_date(publish_at)
            if publish_date > campaign.deadline:
                labels.append("late_publish")
                risks.append("Planned publish date is after the campaign deadline")
            else:
                passed.append("Publish date is within the deadline")
        if "30-day battery" in lowered or "30 day battery" in lowered:
            labels.append("unsupported_battery_claim")
            risks.append("Battery-life claim conflicts with the verified 14-day fact")
            suggestions.append("Replace the battery claim with 14-day battery")
        else:
            passed.append("No unsupported battery-life claim detected")
        if "first 5 seconds" in lowered or "first five seconds" in lowered:
            passed.append("Script shows the product in the first five seconds")
        else:
            labels.append("missing_visible_product")
            missing.append("Show the product in the first five seconds")
            suggestions.append("Add an opening product shot to the script")

        sources = [hit.source_label for hit in knowledge[:3]] or ["项目 Brief"]
        mock = ContentReviewResult(
            passed_checks=passed,
            missing_requirements=missing,
            issue_labels=labels,
            risks=risks,
            suggestions=suggestions,
            sources=sources,
        )
        payload = {
            "campaign": campaign.model_dump(mode="json"),
            "submission": {"content": content, "metadata": dict(metadata)},
            "knowledge": self._knowledge_payload(knowledge),
            "allowed_sources": sources,
            "required_json": {
                "passed_checks": ["string"],
                "missing_requirements": ["string"],
                "issue_labels": [
                    "missing_disclosure",
                    "missing_product",
                    "medical_claim",
                    "missing_link",
                    "late_publish",
                    "unsupported_battery_claim",
                    "missing_visible_product",
                ],
                "risks": ["string"],
                "suggestions": ["string"],
                "sources": ["source label"],
            },
        }
        return self._run(
            purpose="content_review",
            result_type=ContentReviewResult,
            payload=payload,
            mock_result=mock,
            system_prompt=(
                "Review creator content against supplied campaign facts and rules. Do not "
                "invent requirements. Return one JSON object matching required_json. "
                "Sources must be labels from allowed_sources. When knowledge is empty, "
                "项目 Brief refers to the supplied campaign facts."
            ),
        )

    @staticmethod
    def _knowledge_payload(knowledge: Sequence[KnowledgeHit]) -> list[dict[str, str]]:
        return [
            {"source_label": hit.source_label, "title": hit.title, "text": hit.text}
            for hit in knowledge[:3]
        ]

    @staticmethod
    def _as_date(value: Any) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])

    def _run(
        self,
        *,
        purpose: str,
        result_type: type[ResultType],
        payload: dict[str, Any],
        mock_result: ResultType,
        system_prompt: str,
    ) -> ResultType:
        if self.settings.llm_provider == "mock":
            self._log_run(
                purpose=purpose,
                provider="mock",
                model="deterministic-v1",
                input_tokens=0,
                output_tokens=0,
                elapsed_ms=0,
                cost=0,
                status="success",
                error_summary="",
            )
            return mock_result

        if not self.settings.deepseek_api_key:
            message = "DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek"
            self._log_run(
                purpose=purpose,
                provider="deepseek",
                model=self.settings.deepseek_model,
                input_tokens=0,
                output_tokens=0,
                elapsed_ms=0,
                cost=0,
                status="error",
                error_summary=message,
            )
            raise LLMError(message)

        started = time.perf_counter()
        last_error: Exception | None = None
        input_tokens = 0
        output_tokens = 0
        cost = 0.0
        usage_unknown = False
        for _attempt in range(2):
            received_usage = False
            try:
                with httpx.Client(
                    base_url=self.settings.deepseek_base_url,
                    timeout=self.settings.request_timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = client.post(
                        "/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.settings.deepseek_model,
                            "thinking": {"type": "disabled"},
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {
                                    "role": "user",
                                    "content": json.dumps(payload, ensure_ascii=False, default=str),
                                },
                            ],
                            "response_format": {"type": "json_object"},
                            "stream": False,
                        },
                    )
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("Invalid response object")
                usage = body.get("usage") or {}
                if not isinstance(usage, dict):
                    raise ValueError("Invalid usage object")
                usage_error: Exception | None = None
                try:
                    attempt_input_tokens = max(0, int(usage.get("prompt_tokens") or 0))
                    if attempt_input_tokens > 2**63 - 1 - input_tokens:
                        raise ValueError("Input usage exceeds log integer range")
                    input_tokens += attempt_input_tokens
                    cost += attempt_input_tokens / 1_000_000 * self.settings.input_price_per_million
                except (TypeError, ValueError, OverflowError) as exc:
                    usage_error = exc
                try:
                    attempt_output_tokens = max(0, int(usage.get("completion_tokens") or 0))
                    if attempt_output_tokens > 2**63 - 1 - output_tokens:
                        raise ValueError("Output usage exceeds log integer range")
                    output_tokens += attempt_output_tokens
                    cost += attempt_output_tokens / 1_000_000 * self.settings.output_price_per_million
                except (TypeError, ValueError, OverflowError) as exc:
                    usage_error = exc
                if usage_error:
                    raise usage_error
                received_usage = all(
                    usage.get(key) is not None for key in ("prompt_tokens", "completion_tokens")
                )
                usage_unknown = usage_unknown or not received_usage
                response.raise_for_status()
                choices = body.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    raise ValueError("Invalid response choices")
                message = choices[0].get("message")
                if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                    raise ValueError("Invalid response message")
                result = result_type.model_validate_json(message["content"])
                returned_sources = (
                    result.evidence if isinstance(result, MatchExplanation)
                    else result.sources if isinstance(result, ContentReviewResult) else []
                )
                if any(source not in payload.get("allowed_sources", []) for source in returned_sources):
                    raise ValueError("Unexpected source label")
                notes = []
                if last_error:
                    notes.append(f"retry_error={self._safe_error(last_error)}; attempts=2")
                if usage_unknown:
                    notes.append("usage_unknown")
                self._log_run(
                    purpose=purpose,
                    provider="deepseek",
                    model=self.settings.deepseek_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    cost=cost,
                    status="success",
                    error_summary="; ".join(notes),
                )
                return result
            except (httpx.HTTPError, KeyError, TypeError, ValueError, OverflowError, ValidationError) as exc:
                last_error = exc
                usage_unknown = usage_unknown or not received_usage

        safe_error = f"{self._safe_error(last_error or RuntimeError())}; attempts=2"
        if usage_unknown:
            safe_error += "; usage_unknown"
        self._log_run(
            purpose=purpose,
            provider="deepseek",
            model=self.settings.deepseek_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            cost=cost,
            status="error",
            error_summary=safe_error,
        )
        raise LLMError(safe_error) from None

    def _safe_error(self, error: Exception) -> str:
        if isinstance(error, httpx.HTTPStatusError):
            return f"HTTPStatusError (status={error.response.status_code})"
        return type(error).__name__

    def _log_run(
        self,
        *,
        purpose: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        elapsed_ms: float,
        cost: float,
        status: str,
        error_summary: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO model_runs (
                purpose, provider, model, mode, input_tokens, output_tokens,
                elapsed_ms, estimated_cost_usd, status, error_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                purpose,
                provider,
                model,
                self.settings.llm_provider,
                input_tokens,
                output_tokens,
                elapsed_ms,
                cost,
                status,
                error_summary,
            ),
        )
        self.connection.commit()
