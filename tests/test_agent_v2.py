import json

import httpx
import pytest

from app.config import Settings
from app.db import connect


@pytest.fixture
def v2_db(tmp_path):
    from app.agent_v2 import init_agent_db
    connection = connect(tmp_path / "agent.db")
    init_agent_db(connection)
    yield connection
    connection.close()


def response(message, usage=None):
    return httpx.Response(200, json={"choices": [{"message": message}], "usage": usage or {"prompt_tokens": 100, "completion_tokens": 20}})


def tool_message(name, arguments=None, call_id="call_1"):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments or {})}}]}


def sequence_transport(responses, requests):
    def handle(request):
        requests.append(json.loads(request.content))
        return responses.pop(0)
    return httpx.MockTransport(handle)


def test_tools_enforce_budget_category_and_usd_without_business_writes(v2_db):
    from app.agent_v2 import TaskRequest, execute_tool
    task = TaskRequest(task="推荐三个美国健身创作者")
    result = execute_tool(v2_db, task, "search_creators", {})
    assert {item["name"] for item in result["creators"]} == {"Maya Moves Updated", "Wellness Amy", "Fit Drew", "Lift Lina"}
    assert all(item["currency"] == "USD" and item["estimated_fee"] <= 1000 for item in result["creators"])
    stats = execute_tool(v2_db, task, "quote_stats", {})
    assert (stats["count"], stats["min"], stats["median"], stats["max"]) == (4, 720, 890, 990)
    assert v2_db.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0
    assert v2_db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0
    v2_db.execute("UPDATE creators SET currency='EUR' WHERE normalized_handle='mayamoves'")
    assert len(execute_tool(v2_db, task, "search_creators", {})["creators"]) == 3


@pytest.mark.parametrize("name,args", [("run_sql", {"query": "DELETE FROM creators"}), ("search_creators", {"max_fee": 2400}), ("search_knowledge", {"query": "x" * 301}), ("quote_stats", {"path": "/etc/passwd"})])
def test_unknown_tools_and_unexpected_parameters_cannot_execute(v2_db, name, args):
    from app.agent_v2 import TaskRequest, execute_tool, AgentError
    with pytest.raises(AgentError):
        execute_tool(v2_db, TaskRequest(task="查询"), name, args)
    assert v2_db.execute("SELECT COUNT(*) FROM creators").fetchone()[0] == 26


def test_nonfinite_budget_is_rejected():
    from app.agent_v2 import TaskRequest
    with pytest.raises(ValueError):
        TaskRequest(task="查询", max_fee=float("nan"))


@pytest.mark.parametrize("task,want", [("推荐三位创作者并解释风险", ["search_creators", "quote_stats", "search_knowledge"]), ("统计报价中位数", ["quote_stats"]), ("查询产品知识和广告披露", ["search_knowledge"])])
def test_mock_has_distinct_paths_and_cited_reports(v2_db, task, want):
    from app.agent_v2 import TaskRequest, run_agent
    run = run_agent(v2_db, Settings(db_path="unused"), TaskRequest(task=task))
    assert run["status"] == "completed"
    assert [event["name"] for event in run["trace"] if event["kind"] == "tool"] == want
    assert run["report"] is not None and run["cost_usd"] == 0
    assert run["provider"] == "mock" and not run["approved"]
    for finding in run["report"]["findings"]:
        assert finding["sources"] and set(finding["sources"]) <= run["evidence"].keys()


def test_empty_pool_is_completed_without_invented_creators(v2_db):
    from app.agent_v2 import TaskRequest, run_agent
    run = run_agent(v2_db, Settings(db_path="unused"), TaskRequest(task="推荐", max_fee=500))
    assert run["status"] == "completed" and run["report"]["candidates"] == []
    assert run["evidence"]["Q1"]["count"] == 0


def test_real_protocol_executes_readonly_tool_and_preserves_tool_call_id(v2_db):
    from app.agent_v2 import TaskRequest, run_agent
    requests = []
    final = {"summary": "四位合格候选，报价中位数890美元", "candidates": [], "findings": [{"claim": "中位数890美元", "sources": ["Q1"]}], "risks": ["报价需要核实"], "draft": ""}
    transport = sequence_transport([response(tool_message("quote_stats")), response({"role": "assistant", "content": json.dumps(final)})], requests)
    settings = Settings(db_path="unused", llm_provider="deepseek", deepseek_api_key="test-only")
    run = run_agent(v2_db, settings, TaskRequest(task="统计报价"), transport=transport)
    assert run["status"] == "completed" and run["model_calls"] == 2
    assert requests[0]["tools"][0]["type"] == "function"
    assert requests[1]["messages"][-1]["tool_call_id"] == "call_1"
    assert requests[1]["messages"][-1]["role"] == "tool"
    assert run["input_tokens"] == 200 and run["output_tokens"] == 40


def test_forged_evidence_is_failed_not_approved_report(v2_db):
    from app.agent_v2 import TaskRequest, run_agent
    final = {"summary": "假的依据", "candidates": [], "findings": [{"claim": "世界第一", "sources": ["K9999"]}], "risks": [], "draft": ""}
    transport = sequence_transport([response({"role": "assistant", "content": json.dumps(final)})], [])
    run = run_agent(v2_db, Settings(db_path="unused", llm_provider="deepseek", deepseek_api_key="test-only"), TaskRequest(task="查知识"), transport=transport)
    assert run["status"] == "failed" and run["report"] is None
    assert "K9999" not in run["evidence"]


def test_repeating_tool_loop_stops_without_sixth_request(v2_db):
    from app.agent_v2 import TaskRequest, run_agent
    requests = []
    responses = [response(tool_message("quote_stats", call_id=f"call_{i}")) for i in range(5)]
    run = run_agent(v2_db, Settings(db_path="unused", llm_provider="deepseek", deepseek_api_key="test-only"), TaskRequest(task="统计报价"), transport=sequence_transport(responses, requests))
    assert run["status"] == "stopped" and run["report"] is None
    assert len(requests) <= 5 and run["evidence"]["Q1"]["count"] == 4
    assert run["trace"][-1]["kind"] == "guard"


def test_http_failure_does_not_leak_exception_and_keeps_partial_evidence(v2_db):
    from app.agent_v2 import TaskRequest, run_agent
    calls = 0
    def handle(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return response(tool_message("quote_stats"))
        raise httpx.ReadTimeout("private-key-secret in URL and prompt", request=request)
    run = run_agent(v2_db, Settings(db_path="unused", llm_provider="deepseek", deepseek_api_key="private-key-secret"), TaskRequest(task="统计报价"), transport=httpx.MockTransport(handle))
    assert run["status"] == "failed" and run["evidence"]["Q1"]["median"] == 890
    assert "private-key-secret" not in json.dumps(run)
    assert run["usage_unknown"] and run["model_calls"] == 2


def test_timeout_cancels_entire_request_instead_of_waiting_for_slow_response(v2_db):
    import asyncio
    from app.agent_v2 import TaskRequest, run_agent
    async def slow_response(request):
        await asyncio.sleep(0.1)
        return response(tool_message("quote_stats"))
    run = run_agent(v2_db, Settings(db_path="unused", llm_provider="deepseek", deepseek_api_key="test-only", request_timeout_seconds=0.01), TaskRequest(task="统计报价"), transport=httpx.MockTransport(slow_response))
    assert run["status"] == "failed" and "TimeoutError" in run["error"]
    assert run["elapsed_ms"] < 100 and run["usage_unknown"]


def test_model_batch_cannot_execute_more_than_tool_limit(v2_db):
    from app.agent_v2 import TaskRequest, run_agent
    message = tool_message("quote_stats")
    message["tool_calls"] = [dict(message["tool_calls"][0], id=f"call_{i}") for i in range(9)]
    run = run_agent(v2_db, Settings(db_path="unused", llm_provider="deepseek", deepseek_api_key="test-only"), TaskRequest(task="统计报价"), transport=sequence_transport([response(message)], []))
    assert run["status"] == "stopped" and run["tool_calls"] == 0 and not run["evidence"]


def test_invalid_model_tool_is_failed_without_executing_arbitrary_sql(v2_db):
    from app.agent_v2 import TaskRequest, run_agent
    run = run_agent(v2_db, Settings(db_path="unused", llm_provider="deepseek", deepseek_api_key="test-only"), TaskRequest(task="查询"), transport=sequence_transport([response(tool_message("run_sql", {"sql": "DELETE FROM creators"}))], []))
    assert run["status"] == "failed" and run["report"] is None
    assert run["trace"][-2]["status"] == "rejected"
    assert v2_db.execute("SELECT COUNT(*) FROM creators").fetchone()[0] == 26


def test_malformed_choice_is_persisted_as_failure_not_stuck_running(v2_db):
    from app.agent_v2 import TaskRequest, run_agent, get_run
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [None], "usage": {"prompt_tokens": 10, "completion_tokens": 2}}))
    run = run_agent(v2_db, Settings(db_path="unused", llm_provider="deepseek", deepseek_api_key="test-only"), TaskRequest(task="查询"), transport=transport)
    assert run["status"] == "failed" and run["trace"][-1]["kind"] == "guard"
    assert get_run(v2_db, run["id"])["status"] == "failed"
    assert run["input_tokens"] == 10


def test_inflight_paid_request_persists_unknown_usage_before_response(v2_db):
    from app.agent_v2 import TaskRequest, run_agent
    saved = []
    def observe_inflight(request):
        payload = v2_db.execute("SELECT payload FROM agent_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
        saved.append(json.loads(payload))
        return response(tool_message("quote_stats"))
    run_agent(v2_db, Settings(db_path="unused", llm_provider="deepseek", deepseek_api_key="test-only"), TaskRequest(task="统计报价"), transport=httpx.MockTransport(observe_inflight))
    assert saved[0]["usage_unknown"] is True and saved[0]["model_calls"] == 1


@pytest.mark.parametrize("field", ["prompt_tokens", "completion_tokens"])
@pytest.mark.parametrize("value", [2**63, 10**400], ids=["int64-overflow", "float-overflow"])
def test_oversized_usage_remains_unknown_without_stuck_run(v2_db, field, value):
    from app.agent_v2 import TaskRequest, run_agent, get_run
    usage = {"prompt_tokens": 100, "completion_tokens": 20, field: value}
    final = {"summary": "报价需核实", "candidates": [], "findings": [{"claim": "合格候选4人", "sources": ["Q1"]}], "risks": [], "draft": ""}
    transport = sequence_transport([
        response(tool_message("quote_stats"), usage),
        response({"role": "assistant", "content": json.dumps(final)}),
    ], [])

    run = run_agent(v2_db, Settings(db_path="unused", llm_provider="deepseek", deepseek_api_key="test-only"), TaskRequest(task="统计报价"), transport=transport)

    assert run["status"] == "completed" and run["usage_unknown"]
    assert get_run(v2_db, run["id"])["status"] == "completed"
    assert (run["input_tokens"], run["output_tokens"]) == ((100, 40) if field == "prompt_tokens" else (200, 20))
