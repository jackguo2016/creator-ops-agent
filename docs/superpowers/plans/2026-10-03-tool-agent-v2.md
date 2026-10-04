# Tool Agent V2 Implementation Plan

> **For agentic workers:** Use tests before behavior changes, scoped parallel work and independent review. User authorizes continuous execution through final delivery.

**Goal:** Deliver an isolated, explainable creator research Agent with a complete beginner guide.

**Architecture:** Three allowlisted read-only tools, bounded model-tool loop, validated report and persistent run trace. Independent FastAPI entry point shares existing low-level helpers, never the live database.

**Tech Stack:** Existing FastAPI/SQLite/Pydantic/httpx/Jinja/native HTML CSS JS; no new dependency.

**Spec:** docs/superpowers/specs/2026-10-03-tool-agent-v2.md

## Global Constraints

Do not read/copy private .env or mutate original app.db. No paid API test in implementation. Default mock; 5 model requests, 8 tool calls, 60-second deadline. Report confirmation does not send email. All human-facing output Chinese except draft and factual sample data. No login/queue/vector DB/new frameworks.

## Execution checklist

- [x] Task 1 (root): tests/test_agent_v2.py RED for allowlisted tools, hard filters, source validation, limits and failed state; implement app/agent_v2.py; GREEN. Literal fixture expectations: budget1000 fitness excludes Premium Pat and Maya950 remains; finite budget enforced.
- [x] Task 2 (root): tests/test_agent_v2_web.py RED for distinct defaultDB, request validation, history, approve, interrupted recovery; implement app/agent_main.py and run-agent-v2.sh; GREEN.
- [x] Task 3 (UI worker): only app/templates/agent_v2.html and app/static/agent_v2.css/js. Consume spec API verbatim. Accessible task form, examples, busy/failed states, readable trace/report/evidence/history, safe text rendering and explicit mode/billing/confirmation boundaries.
- [x] Task 4 (docs worker): only docs/AGENT_V2_GUIDE_CN.md and docs/AGENT_V2_DEMO_CN.md. Full start/click/expected-result walkthrough, code-reading path, five hands-on exercises, failure handling and actual limitations; verified interface names from spec. No product edits or paid calls.
- [x] Task 5 (root + independent reviewer): full pytest, local browser successful and no-result runs, review new V2 files only, repair findings. Copy guides to outputs, link root entry, package tracked+V2 allowlist without .env/DB/venv; expose local demo and self-contained handoff.

## Progress / decisions

- Design accepted directly by user; no further approval ceremonies.
- Reuse current checkout to preserve uncommitted first-version fixes; all behavior additions in new V2 files. No commits or external publication in this delivery.
- UI and prose work have separate file ownership and a stable JSON contract; safe to parallelize while root builds backend. Review verifies integrated behavior, not just worker reports.
- Independent review closed two P2 findings with RED/GREEN tests: malformed choice response cannot strand a run as running; unknown usage persists before an in-flight paid request.
- Browser MOCK acceptance: creator research, evidence anchor, manual confirmation, quote-only, knowledge-only, empty shortlist at budget500 and history reopening. No console errors. No paid model requests.
- Final regression: 94 passed; detailed delivery evidence in docs/AGENT_V2_DELIVERY_CN.md.
