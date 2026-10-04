"""Separate local entry point for V2; V1 routes and database are untouched."""
from contextlib import asynccontextmanager
from dataclasses import replace
import os
from pathlib import Path
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.agent_v2 import (
    AgentError, TaskRequest, approve_run, get_run, init_agent_db, list_runs, run_agent,
    MAX_MODEL_CALLS, MAX_TOOL_CALLS, DEADLINE_SECONDS,
)
from app.config import Settings
from app.db import connect


EXAMPLES = [
    "推荐三位美国健身创作者，比较报价、检索交付风险依据，并准备英文邀约草稿。",
    "统计当前合格候选的报价中位数和价格区间。",
    "查询 LumaSip 产品知识和广告披露要求。",
]


def default_agent_settings() -> Settings:
    return replace(Settings.from_env(), db_path=Path(os.getenv("AGENT_V2_DB_PATH", "data/agent_v2.db")))


def create_agent_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or default_agent_settings()
    v1_path = Path(__file__).parent.parent / "data" / "app.db"
    if Path(resolved.db_path).resolve() == v1_path.resolve():
        raise ValueError("V2 不允许使用第一版 data/app.db；请指定独立数据库。")
    # ponytail: one local worker, one active task; use a queue only for real multi-user deployment.
    execution_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(application):
        connection = connect(Path(resolved.db_path))
        try:
            init_agent_db(connection)
        finally:
            connection.close()
        yield

    application = FastAPI(title="Creator Research Agent V2", lifespan=lifespan)
    application.state.settings = resolved
    templates = Jinja2Templates(directory=Path(__file__).with_name("templates"))
    application.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")

    @application.get("/health")
    def health():
        return {"status": "ok", "llm_provider": resolved.llm_provider}

    @application.get("/")
    def home(request: Request):
        connection = connect(Path(resolved.db_path))
        try:
            count = connection.execute("SELECT COUNT(*) FROM creators").fetchone()[0]
        finally:
            connection.close()
        return templates.TemplateResponse(request=request, name="agent_v2.html", context={
            "provider": resolved.llm_provider, "model": resolved.deepseek_model if resolved.llm_provider == "deepseek" else "deterministic-demo",
            "examples": EXAMPLES, "creators_count": count,
            "limits": {"max_model_calls": MAX_MODEL_CALLS, "max_tool_calls": MAX_TOOL_CALLS, "deadline_seconds": DEADLINE_SECONDS},
        })

    @application.get("/api/runs")
    def history():
        connection = connect(Path(resolved.db_path))
        try:
            return list_runs(connection)
        finally:
            connection.close()

    @application.post("/api/runs")
    def execute(payload: TaskRequest):
        if not execution_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="已有任务正在执行，请等待完成；不会替你重复发起付费调用。")
        try:
            connection = connect(Path(resolved.db_path))
            try:
                return run_agent(connection, resolved, payload)
            finally:
                connection.close()
        finally:
            execution_lock.release()

    @application.get("/api/runs/{run_id}")
    def detail(run_id: int):
        connection = connect(Path(resolved.db_path))
        try:
            return get_run(connection, run_id)
        except LookupError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        finally:
            connection.close()

    @application.post("/api/runs/{run_id}/approve")
    def approve(run_id: int):
        connection = connect(Path(resolved.db_path))
        try:
            return approve_run(connection, run_id)
        except LookupError:
            raise HTTPException(status_code=404, detail="任务不存在") from None
        except AgentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        finally:
            connection.close()

    return application


app = create_agent_app()
