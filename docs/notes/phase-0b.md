# Phase 0b — Skeleton and CI

> Branch: `chore/project-skeleton` · Date: 2026-10-28

## Files
- `apps/api/pyproject.toml`: dependencies (fastapi, uvicorn; dev: pytest, httpx, ruff, mypy, pre-commit) and ruff/mypy/pytest settings.
- `apps/api/uv.lock`: exact versions; CI fails if it is out of date (`uv sync --locked`).
- `apps/api/src/depguard/main.py`: FastAPI app with `GET /health`.
- `apps/api/tests/test_health.py`: `/health` returns ok; unknown paths return 404.
- `apps/web/README.md`: placeholder until the web phase.
- `docker-compose.yml`: local Postgres 17 (matches Supabase) and Neo4j 2026.10 community (matches Aura), with healthchecks.
- `Makefile`: `setup`, `dev`, `db-up`, `db-down`, `test`, `lint`, `format`.
- `.env.example`: all variable names from security.md §4 plus the local database settings.
- `.pre-commit-config.yaml`: secret/large-file/whitespace checks, then ruff and mypy through uv.
- `.github/workflows/ci.yml`: lint, format check, mypy and tests on every PR and push to `main`.
- `.github/dependabot.yml`: weekly updates for action pins and Python dependencies.
- `.gitattributes`: LF line endings in the repo.
- `.claude/settings.json` + `.claude/hooks/format_python.py`: format a `.py` file after each Claude edit.

## Main flow
`make setup` → `make db-up` → `make dev`. Commit → pre-commit checks. PR → CI runs the same checks as `make lint` + `make test`.

## Decisions
- `/health` is liveness only (no database calls), so a sleeping free-tier database can't make Render restart the API.
- mypy `strict` from the start; untyped libraries get per-module ignores later.
- Ruff and mypy run from `uv.lock` in pre-commit, CI and the hook, so there is one version everywhere.
- CI runs explicit steps instead of `pre-commit run --all-files`, for readable logs.
- Actions pinned to full commit SHAs, `permissions: contents: read`, `persist-credentials: false`.
- `uvicorn` directly instead of `fastapi[standard]`: fewer dependencies, and Render needs uvicorn anyway.
- Layout follows architecture.md §7 (`apps/api`, `apps/web`); MCP will live in the API (ADR-0011).

## Handoff
### Done
- Skeleton, compose, Makefile, pre-commit, CI, Dependabot, format hook.
- Verified locally: `make setup`, `make lint`, `make test`; hook reformats a live edit.

### Pending
- [ ] Open Docker Desktop and run `make db-up`; check http://localhost:7474 accepts the `.env` password.
- [ ] Fill the real secret values in `.env` when each integration is built.

### Open issues
- pytest shows a Starlette warning suggesting `httpx2` instead of `httpx`; kept `httpx` for now (warning only).
- Carried from Phase 0: LLM provider, risk-score weights, AuraDB limits, benchmark repos, phase plan.
