# DepGuard
DepGuard finds vulnerable open-source dependencies in GitHub repos, ranks them by
real-world risk (CISA KEV, EPSS, CVSS, and how many services each one reaches),
explains the top risks with an AI agent, and opens minimal fix pull requests. It
also exposes an MCP server. Scope: npm and PyPI only.

## Tech stack
Python + FastAPI backend, Neo4j (dependency graph), Postgres (users, scans,
findings), LangGraph agent with a free LLM, Langfuse tracing, Next.js +
TypeScript frontend, Supabase Auth, GitHub Actions CI, Docker. Hosting: Render
(API), Vercel (web), Neo4j AuraDB Free, Supabase. Free tiers only.

## About me
I don't write code. I must be able to defend every file and decision in
interviews. I'll ask when I want something explained.

## How to work with me
- Be concise. No analogies, Insight blocks, recaps or quizzes unless I ask.
- Explain only decisions with real trade-offs and non-obvious code.
- Ask approval only for design decisions, not routine steps.
- One phase = one branch = one PR. Never commit to main.
- Never ask me to paste secrets into chat. Secrets go in .env (gitignored);
  keep .env.example updated.
- Tests for every feature. Matching, version comparison and scoring are
  deterministic code, never the LLM.
- Simple, readable code. No unnecessary features. Real data only, except
  small test fixtures.
- Read only the files a task needs. docs/architecture.md and the ADRs are
  the source of truth for design.

## Documentation to keep updated
- docs/spec.md, docs/architecture.md, docs/adr/, docs/security.md: update
  only when a decision changes them.
- docs/notes/phase-N.md, short: files (one line each), main flow, decisions,
  Handoff (done / pending / open issues).

## Commands
Run from the repo root. One-time: `winget install ezwinports.make`, `copy .env.example .env`, `make setup`.
- `make dev`: API with auto-reload at http://localhost:8000 (`/health`, `/docs`)
- `make db-up` / `make db-down`: local Postgres + Neo4j (open Docker Desktop first)
- `make test`: pytest
- `make lint`: ruff check, ruff format --check, mypy (same as CI)
- `make format`: auto-fix lint and formatting
- Python dependencies: `uv add <pkg>` (or `uv add --dev <pkg>`) inside `apps/api`; commit `uv.lock`.
