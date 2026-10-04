import pytest


def test_health_and_schema(client, db):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "llm_provider": "mock"}

    tables = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "campaigns",
        "creators",
        "matches",
        "drafts",
        "content_reviews",
        "knowledge_docs",
        "model_runs",
    } <= tables


@pytest.mark.parametrize(
    "path, marker",
    [
        ("/", "项目总览"),
        ("/campaigns/1", "项目 Brief"),
        ("/creators", "创作者库"),
        ("/campaigns/1/matches", "智能匹配"),
        ("/campaigns/1/workflow", "沟通与交付"),
        ("/logs", "日志与评测"),
    ],
)
def test_demo_pages_render(client, path, marker):
    response = client.get(path)

    assert response.status_code == 200
    assert marker in response.text


def test_start_script_preserves_explicit_mock_and_practice_database(tmp_path):
    import os
    import shutil
    import subprocess
    from pathlib import Path

    script = tmp_path / "run.sh"
    shutil.copyfile(Path(__file__).parent.parent / "run.sh", script)
    (tmp_path / ".env").write_text("LLM_PROVIDER=deepseek\nDB_PATH=data/old-demo.db\n")
    binaries = tmp_path / ".venv" / "bin"
    binaries.mkdir(parents=True)
    # Replace only the installer/server boundary: no network or service starts.
    for name, content in {
        "python": "#!/usr/bin/env bash\nexit 0\n",
        "uvicorn": '#!/usr/bin/env bash\nprintf \'%s\\n\' "$LLM_PROVIDER" "$DB_PATH"\n',
    }.items():
        stub = binaries / name
        stub.write_text(content)
        stub.chmod(0o755)

    result = subprocess.run(
        ["/bin/bash", str(script)],
        env={"PATH": os.defpath, "LLM_PROVIDER": "mock", "DB_PATH": "data/new-practice.db"},
        capture_output=True, text=True, timeout=5,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["mock", "data/new-practice.db"]
