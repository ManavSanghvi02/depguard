# ADR-0014: Python + FastAPI backend, Next.js + TypeScript frontend
- Status: Accepted
- Date: 2026-10-28

## Context
DepGuard needs a backend that parses lockfiles, compares versions, calls GitHub and OSV, processes a large
daily EPSS file, runs an AI agent and serves both a REST API and an MCP server. It also needs a web UI. The owner
must be able to explain every file, so mainstream, readable tools matter more than novelty.

## Options

### Backend
**Option A: Python + FastAPI**
- Python's `packaging` library implements PEP 440 version comparison, the official PyPI rules.
- LangGraph, Langfuse and the MCP SDK all have first-class Python support.
- FastAPI checks input with type hints (Pydantic), generates interactive docs at `/docs`, and handles many
  waiting network calls at once (async).

**Option B: TypeScript + Node (Express or NestJS)**
- One language across frontend and backend.
- npm's own `semver` library is native here.
- LangGraph and the MCP SDK also exist for TypeScript, but Python's data-processing tools are stronger for the EPSS file.

### Frontend
**Option A: Next.js + TypeScript**: routing, server rendering and simple deployment on Vercel (which makes
Next.js); Supabase provides Next.js auth helpers; TypeScript catches mistakes before they run.

**Option B: a plain React app (Vite) + TypeScript**: simpler, with fewer concepts, but routing, auth handling and
deployment details are all up to us.

## Decision
**Backend: Python + FastAPI.** **Frontend: Next.js + TypeScript.**

## Trade-offs
- **Gain:** the best libraries for each job (PEP 440, LangGraph, Langfuse, data processing); automatic input validation and
  API docs; an easy Vercel deploy for the web app.
- **Give up:** two languages and two toolchains (`uv` for Python, `npm` for the web app), and CI must run both.
  npm version comparison in Python needs a well-tested library or our own small module, covered by tests.
- **Revisit if:** the web app needed heavy server-side logic, where sharing code with a TypeScript backend would matter.
