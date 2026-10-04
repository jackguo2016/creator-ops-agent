from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.campaigns import CampaignNotFoundError, get_campaign, update_campaign
from app.config import Settings
from app.creators import (
    CreatorFilters,
    list_creators,
    parse_creator_csv,
    upsert_creators,
)
from app.db import connect, initialize_demo
from app.evaluation import dashboard_metrics, recent_model_runs, run_evaluation
from app.llm import LLMClient, LLMError
from app.models import Campaign, CampaignInput
from app.matching import list_matches, refresh_rule_matches
from app.outreach import (
    approve_draft,
    create_outreach_draft,
    list_drafts,
    list_selected_creators,
    rank_eligible_matches,
    select_creator,
)
from app.reviews import ReviewSubmission, create_content_review, list_content_reviews


TEMPLATES = Jinja2Templates(directory=Path(__file__).with_name("templates"))


def _campaign_values(campaign: Campaign) -> dict[str, str | int | float]:
    values = campaign.model_dump()
    values["platforms"] = ",".join(campaign.platforms)
    values["categories"] = ",".join(campaign.categories)
    values["deadline"] = campaign.deadline.isoformat()
    return values


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        connection = connect(resolved.db_path)
        try:
            initialize_demo(connection)
        finally:
            connection.close()
        yield

    application = FastAPI(title="Creator Ops Agent", lifespan=lifespan)
    application.state.settings = resolved
    application.mount(
        "/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static"
    )

    @application.exception_handler(CampaignNotFoundError)
    async def missing_campaign(request: Request, exc: CampaignNotFoundError):
        return JSONResponse(status_code=404, content={"detail": "项目不存在"})

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "llm_provider": resolved.llm_provider}

    @application.get("/")
    def dashboard(request: Request):
        connection = connect(resolved.db_path)
        try:
            campaign = get_campaign(connection, 1)
            metrics = dashboard_metrics(connection, campaign.id)
        finally:
            connection.close()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "campaign": campaign,
                "metrics": metrics,
                "llm_provider": resolved.llm_provider,
            },
        )

    def _logs_page(request: Request, report=None):
        connection = connect(resolved.db_path)
        try:
            runs = recent_model_runs(connection)
        finally:
            connection.close()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="logs.html",
            context={
                "runs": runs,
                "report": report,
                "llm_provider": resolved.llm_provider,
            },
        )

    @application.get("/logs")
    def logs_page(request: Request):
        return _logs_page(request)

    @application.post("/evaluate")
    def evaluate(request: Request):
        connection = connect(resolved.db_path)
        try:
            report = run_evaluation(
                connection,
                LLMClient(resolved, connection),
                Path(__file__).parent.parent / "data" / "evaluation_cases.json",
            )
        finally:
            connection.close()
        return _logs_page(request, report)

    @application.get("/campaigns/{campaign_id}")
    def campaign_page(request: Request, campaign_id: int):
        connection = connect(resolved.db_path)
        try:
            campaign = get_campaign(connection, campaign_id)
        finally:
            connection.close()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="campaign.html",
            context={
                "campaign": campaign,
                "values": _campaign_values(campaign),
                "errors": [],
                "llm_provider": resolved.llm_provider,
            },
        )

    @application.post("/campaigns/{campaign_id}")
    async def save_campaign(request: Request, campaign_id: int):
        form = await request.form()
        raw = {key: str(value) for key, value in form.items()}
        payload = {
            **raw,
            "platforms": _split_list(raw.get("platforms", "")),
            "categories": _split_list(raw.get("categories", "")),
        }
        connection = connect(resolved.db_path)
        try:
            current = get_campaign(connection, campaign_id)
            try:
                data = CampaignInput.model_validate(payload)
            except ValidationError as exc:
                errors = [error["msg"] for error in exc.errors()]
                return TEMPLATES.TemplateResponse(
                    request=request,
                    name="campaign.html",
                    context={
                        "campaign": current,
                        "values": raw,
                        "errors": errors,
                        "llm_provider": resolved.llm_provider,
                    },
                    status_code=422,
                )
            update_campaign(connection, campaign_id, data)
        finally:
            connection.close()
        return RedirectResponse(f"/campaigns/{campaign_id}", status_code=303)

    @application.get("/creators")
    def creators_page(
        request: Request,
        country: str = "",
        platform: str = "",
        category: str = "",
    ):
        filters = CreatorFilters(country=country, platform=platform, category=category)
        connection = connect(resolved.db_path)
        try:
            creators = list_creators(connection, filters)
        finally:
            connection.close()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="creators.html",
            context={
                "creators": creators,
                "filters": filters,
                "summary": None,
                "llm_provider": resolved.llm_provider,
            },
        )

    @application.post("/creators/import")
    async def import_creators(request: Request, file: UploadFile):
        if not (file.filename or "").lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="只接受 CSV 文件")
        data = await file.read(resolved.max_upload_bytes + 1)
        if len(data) > resolved.max_upload_bytes:
            raise HTTPException(status_code=413, detail="CSV 文件不能超过 1 MiB")
        try:
            summary = parse_creator_csv(data, date.today())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        connection = connect(resolved.db_path)
        try:
            upsert_creators(connection, summary)
            creators = list_creators(connection)
        finally:
            connection.close()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="creators.html",
            context={
                "creators": creators,
                "filters": CreatorFilters(),
                "summary": summary,
                "llm_provider": resolved.llm_provider,
            },
        )

    @application.get("/campaigns/{campaign_id}/matches")
    def matching_page(request: Request, campaign_id: int):
        connection = connect(resolved.db_path)
        try:
            campaign = get_campaign(connection, campaign_id)
            matches = list_matches(connection, campaign_id)
        finally:
            connection.close()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="matching.html",
            context={
                "campaign": campaign,
                "matches": matches,
                "llm_provider": resolved.llm_provider,
            },
        )

    @application.post("/campaigns/{campaign_id}/matches/refresh")
    def refresh_matches(campaign_id: int):
        connection = connect(resolved.db_path)
        try:
            refresh_rule_matches(connection, campaign_id)
        finally:
            connection.close()
        return RedirectResponse(
            f"/campaigns/{campaign_id}/matches", status_code=303
        )

    @application.post("/campaigns/{campaign_id}/matches/ai")
    def rank_matches(campaign_id: int):
        connection = connect(resolved.db_path)
        try:
            rank_eligible_matches(
                connection, campaign_id, LLMClient(resolved, connection)
            )
        except (LLMError, ValueError) as exc:
            raise HTTPException(status_code=502 if isinstance(exc, LLMError) else 400, detail=str(exc)) from exc
        finally:
            connection.close()
        return RedirectResponse(
            f"/campaigns/{campaign_id}/matches", status_code=303
        )

    @application.post("/campaigns/{campaign_id}/matches/{creator_id}/select")
    def choose_creator(campaign_id: int, creator_id: int):
        connection = connect(resolved.db_path)
        try:
            select_creator(connection, campaign_id, creator_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            connection.close()
        return RedirectResponse(
            f"/campaigns/{campaign_id}/workflow", status_code=303
        )

    @application.get("/campaigns/{campaign_id}/workflow")
    def workflow_page(request: Request, campaign_id: int):
        connection = connect(resolved.db_path)
        try:
            campaign = get_campaign(connection, campaign_id)
            creators = list_selected_creators(connection, campaign_id)
            drafts = list_drafts(connection, campaign_id)
            reviews = list_content_reviews(connection, campaign_id)
        finally:
            connection.close()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="workflow.html",
            context={
                "campaign": campaign,
                "creators": creators,
                "drafts": drafts,
                "reviews": reviews,
                "llm_provider": resolved.llm_provider,
            },
        )

    @application.post("/campaigns/{campaign_id}/drafts/{creator_id}")
    def generate_draft(campaign_id: int, creator_id: int):
        connection = connect(resolved.db_path)
        try:
            create_outreach_draft(
                connection,
                campaign_id,
                creator_id,
                LLMClient(resolved, connection),
            )
        except (LLMError, ValueError) as exc:
            status = 502 if isinstance(exc, LLMError) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        finally:
            connection.close()
        return RedirectResponse(
            f"/campaigns/{campaign_id}/workflow", status_code=303
        )

    @application.post("/drafts/{draft_id}/approve")
    def approve_outreach(draft_id: int):
        connection = connect(resolved.db_path)
        try:
            row = connection.execute(
                "SELECT campaign_id FROM drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="草稿不存在")
            approve_draft(connection, draft_id)
            campaign_id = row["campaign_id"]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            connection.close()
        return RedirectResponse(
            f"/campaigns/{campaign_id}/workflow", status_code=303
        )

    @application.post("/campaigns/{campaign_id}/reviews")
    async def review_content(request: Request, campaign_id: int):
        form = await request.form()
        try:
            submission = ReviewSubmission.model_validate(
                {
                    "content": form.get("content", ""),
                    "link": form.get("link") or None,
                    "planned_publish_at": form.get("planned_publish_at") or None,
                }
            )
            connection = connect(resolved.db_path)
            try:
                review_id = create_content_review(
                    connection,
                    campaign_id,
                    submission,
                    LLMClient(resolved, connection),
                )
            finally:
                connection.close()
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return RedirectResponse(
            f"/campaigns/{campaign_id}/workflow#review-{review_id}", status_code=303
        )

    return application


app = create_app()
