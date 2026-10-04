import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect


@pytest.fixture
def agent_client(tmp_path):
    from app.agent_main import create_agent_app
    settings = Settings(db_path=tmp_path / "v2.db", llm_provider="mock")
    with TestClient(create_agent_app(settings)) as client:
        yield client, settings


def test_default_database_does_not_inherit_v1_db_path(monkeypatch):
    from app.agent_main import default_agent_settings
    monkeypatch.setenv("DB_PATH", "data/app.db")
    monkeypatch.delenv("AGENT_V2_DB_PATH", raising=False)
    assert str(default_agent_settings().db_path) == "data/agent_v2.db"


def test_task_history_and_confirmation_never_send_or_write_business_tables(agent_client):
    client, settings = agent_client
    result = client.post("/api/runs", json={"task": "推荐创作者"})
    assert result.status_code == 200
    run = result.json()
    assert run["status"] == "completed" and run["report"]["candidates"]
    assert client.get("/api/runs").json()[0]["id"] == run["id"]
    assert client.get(f"/api/runs/{run['id']}").json()["provider"] == "mock"
    first = client.post(f"/api/runs/{run['id']}/approve").json()
    second = client.post(f"/api/runs/{run['id']}/approve").json()
    assert first["approved"] and first["approved_at"] == second["approved_at"]
    connection = connect(settings.db_path)
    assert connection.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0
    connection.close()


@pytest.mark.parametrize("payload", [{"task": ""}, {"task": "推荐", "max_fee": -1}, {"task": "推荐", "count": 99}, {"task": "推荐", "sql": "DROP TABLE creators"}])
def test_invalid_request_is_rejected_before_creating_a_run(agent_client, payload):
    client, _ = agent_client
    assert client.post("/api/runs", json=payload).status_code == 422
    assert client.get("/api/runs").json() == []


def test_unknown_run_is_404(agent_client):
    client, _ = agent_client
    assert client.get("/api/runs/999").status_code == 404
    assert client.post("/api/runs/999/approve").status_code == 404


def test_restart_preserves_partial_trace_and_marks_interruption(agent_client):
    from app.agent_v2 import init_agent_db
    import json
    client, settings = agent_client
    run = client.post("/api/runs", json={"task": "统计报价"}).json()
    run["status"] = "running"
    run["report"] = None
    connection = connect(settings.db_path)
    connection.execute("UPDATE agent_runs SET status='running',payload=? WHERE id=?", (json.dumps(run), run["id"]))
    connection.commit()
    init_agent_db(connection)
    connection.close()
    interrupted = client.get(f"/api/runs/{run['id']}").json()
    assert interrupted["status"] == "stopped" and interrupted["evidence"]["Q1"]["count"] == 4
    assert interrupted["trace"][-1]["name"] == "restart"
    assert client.post(f"/api/runs/{run['id']}/approve").status_code == 400


def test_v2_home_reports_mode_and_serves_separate_ui(agent_client):
    client, _ = agent_client
    response = client.get("/")
    assert response.status_code == 200
    assert "agent_v2.js" in response.text and "agent_v2.css" in response.text
    assert client.get("/health").json()["llm_provider"] == "mock"
