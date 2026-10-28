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
I am a new-grad engineer. I will NOT write code. My goal is to understand and
defend every file, design decision and technology in job interviews.

## How to work with me
- Before any change: explain WHAT you will do, WHY, and what ALTERNATIVES exist,
  then wait for my approval.
- Teach new concepts with a simple analogy first, then the technical detail.
- Keep changes small. One phase = one branch = one pull request. Never commit
  directly to main after Session 1.
- Never ask me to paste secrets into chat. Secrets go in .env (gitignored). Keep
  .env.example updated with placeholder values.
- Write tests for every feature. Matching, scoring and version comparison must be
  deterministic code, never the LLM.
- Prefer simple, readable code over clever code. No unnecessary features.
- Use real data (public APIs, real public repos). No Kaggle or made-up datasets
  except small test fixtures.

## Documentation to keep updated
- docs/spec.md: what we build and why
- docs/architecture.md: diagrams (Mermaid), data flow, data model, API
- docs/adr/: one file per major decision (context, options, decision, trade-offs)
- docs/notes/phase-N.md: per phase: concepts, every file and what it does, how a
  request flows through them, decisions, 10 interview questions with answers,
  and a Handoff section (done / pending / open issues)
- docs/glossary.md: every technical term in plain English

## Commands
(fill in as the project grows: how to run, test, lint)
