#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

agent_v2_provider=mock
if [[ "${1:-}" == "--deepseek" && $# == 1 ]]; then
  if [[ ! -f .env ]]; then
    echo "缺少私有 .env。先用不带参数的命令免费练习；不要把 Key 写进脚本。" >&2
    exit 1
  fi
  set -a
  source .env
  set +a
  agent_v2_provider=deepseek
  if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
    echo ".env 未配置 DEEPSEEK_API_KEY；停止启动，不发起付费调用。" >&2
    exit 1
  fi
elif [[ $# != 0 ]]; then
  echo "用法：./run-agent-v2.sh（免费mock）或 ./run-agent-v2.sh --deepseek" >&2
  exit 2
fi

if [[ ! -d .venv ]]; then
  python3 -c 'import sys; assert sys.version_info >= (3, 11), "需要 Python 3.11 或更高版本"'
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, httpx, pydantic, uvicorn, jinja2' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi

export LLM_PROVIDER="$agent_v2_provider"
export AGENT_V2_DB_PATH="${AGENT_V2_DB_PATH:-data/agent_v2.db}"
exec .venv/bin/uvicorn app.agent_main:app --host 127.0.0.1 --port "${AGENT_V2_PORT:-8010}"
