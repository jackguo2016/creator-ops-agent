#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# An explicit practice mode/database must not be overwritten by saved .env values.
creator_demo_provider_override="${LLM_PROVIDER-}"
creator_demo_db_override="${DB_PATH-}"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --quiet -r requirements.txt

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

if [[ -n "$creator_demo_provider_override" ]]; then
  export LLM_PROVIDER="$creator_demo_provider_override"
fi
if [[ -n "$creator_demo_db_override" ]]; then
  export DB_PATH="$creator_demo_db_override"
fi

exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
