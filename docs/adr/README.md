# Architecture Decision Records (ADRs)

An ADR records **one** important decision: the situation (context), the options we compared, what we chose,
and what it costs us. ADRs are numbered in the order they were written and are never deleted. If a decision
changes, a new ADR replaces the old one, and the old one is marked *Superseded*.

**Statuses:** *Proposed* (written, waiting for approval) · *Accepted* · *Superseded by ADR-XXXX*.

## Index

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-github-app-over-oauth-repo-scope.md) | GitHub App with narrow permissions for writes, not the OAuth `repo` scope | Accepted |
| [0002](0002-lockfiles-only-no-version-guessing.md) | Read lockfiles only; never guess versions | Accepted |
| [0003](0003-risk-tiers-and-stored-scores.md) | Deterministic tiers and scoring, not LLM scoring; scores stored daily | Accepted |
| [0004](0004-vulnerability-data-sources.md) | OSV `querybatch` + KEV/EPSS bulk files; `partial` scans on failure | Accepted |
| [0005](0005-postgres-and-neo4j-split.md) | Postgres for records, Neo4j for the dependency graph | Accepted |
| [0006](0006-per-service-graph-nodes.md) | Separate graph nodes per service | Accepted |
| [0007](0007-free-tier-hosting-vercel-and-render.md) | Free-tier hosting: Vercel (web) + Render (API) + Supabase + AuraDB | Accepted |
| [0008](0008-background-scans-in-process.md) | Background scans inside the API process | Accepted |
| [0009](0009-daily-refresh-on-github-actions.md) | Daily refresh on GitHub Actions with a restricted database role | Accepted |
| [0010](0010-fix-prs-built-in-github-actions.md) | Fix PRs built in GitHub Actions with two isolated jobs | Accepted |
| [0011](0011-mcp-in-api-with-user-tokens.md) | MCP mounted in the API, per-user API tokens | Accepted |
| [0012](0012-fetch-lockfiles-via-tree-api.md) | Fetch only lockfiles via the tree API with a read-only token | Accepted |
| [0013](0013-explanation-agent-and-llm.md) | LangGraph for the explanation agent; Groq, Gemini fallback for public repos only | Accepted |
| [0014](0014-language-and-framework.md) | Python + FastAPI backend, Next.js + TypeScript frontend | Accepted |
| [0015](0015-npm-and-pypi-scope.md) | Support npm and PyPI only | Accepted |

## Template

```markdown
# ADR-XXXX: Title
- Status: Proposed | Accepted | Superseded by ADR-YYYY
- Date: YYYY-MM-DD

## Context
What situation forces a decision? What constraints apply?

## Options
### Option A — ...
### Option B — ...

## Decision
What we chose, in one or two sentences.

## Trade-offs
What we gain, what we give up, and what would make us revisit this.
```
