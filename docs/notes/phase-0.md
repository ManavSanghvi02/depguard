# Phase 0 — Spec and Design

> Branch: `docs/phase-0-design` · Dates: 2026-10-28 · Documents only, no code.
> Goal: decide **what** DepGuard is and **how** it will work, with every decision written down and defensible.

---

## 1. Concepts learned

| Concept | One-line takeaway |
|---|---|
| **Problem statement** | Name the pain (alert overload, "where am I affected?"), not the feature. |
| **Personas and non-goals** | Saying who you're *not* building for makes the scope defensible. |
| **User stories + "done when"** | Each story's check becomes a test. |
| **Success metrics** | Every metric needs "how measured"; a proxy metric must be labelled as a proxy. |
| **Branch / pull request** | Work on a copy (`docs/phase-0-design`), merge to `main` only after review. |
| **Client / server, REST** | Clients ask, servers answer; REST = resources as URLs + HTTP verbs + status codes. |
| **FastAPI vs. REST** | REST is the design style; FastAPI is the Python tool used to build it. |
| **Relational vs. graph databases** | Tables for records; nodes and relationships for paths of unknown depth. |
| **Background and scheduled jobs** | Slow work gets a ticket (`202` + ID + polling); timed work runs on a schedule. |
| **Environment variables and secrets** | Config comes from the environment; secrets never enter Git; rotate on leak. |
| **AI agent** | An LLM in a loop with tools; ours can only read and explain. |
| **MCP** | A standard "USB port" letting AI assistants call DepGuard's tools. |
| **CVE, CVSS, EPSS, KEV** | Licence plate, damage rating, weather forecast, police report of real attacks. |
| **Graceful degradation** | When the LLM is down, everything except explanations still works. |
| **Correct by construction** | Prefer designs where the mistake can't happen (per-service graph nodes). |
| **Least privilege, RLS, threat model** | Narrow access everywhere; list assets → threats → controls. |

All terms: [glossary.md](../glossary.md).

---

## 2. Documents created

| File | What it contains |
|---|---|
| [`docs/spec.md`](../spec.md) | Problem (incl. Log4Shell and `ua-parser-js` examples), comparison with Dependabot, users, definitions (service, reach), 8 user stories (MVP = 1–7), scope and lockfile table, the 3 tiers, non-goals, success metrics, constraints with free-tier limits and the graph-capacity formula, open questions |
| [`docs/architecture.md`](../architecture.md) | System diagram, components, scan sequence diagram + 11 steps, daily refresh, fix-PR sequence diagram, decision summary, Neo4j model with indexes and queries, Postgres ER diagram and tables, database roles and RLS, API endpoints, folder structure, known limits |
| [`docs/adr/README.md`](../adr/README.md) | ADR index, statuses and template |
| `docs/adr/0001` – `0015` | One file per major decision (section 4 below) |
| [`docs/security.md`](../security.md) | Threat model (assets, threats T1–T5, prevention), secrets inventory, GitHub access, database roles and RLS, user isolation, untrusted code and text, Actions hardening, abuse limits, stored personal data, open items |
| [`docs/glossary.md`](../glossary.md) | Every technical term in plain English |
| `docs/notes/phase-0.md` | This file |

---

## 3. How a request flows (one scan)

1. **Web app** → `POST /v1/repos/{id}/scans` with the login token (JWT).
2. **API** checks the user owns the repo → creates the scan as `queued` → replies `202 {scan_id}`.
3. **Background task:** fetch lockfiles (GitHub tree + blob API) → parse → match against **OSV** → cache
   advisories → write each service's graph to **Neo4j** → add **KEV/EPSS** + reach → compute tier and score → save in
   **Postgres** → status `done` or `partial`.
4. **Web app** polls `GET /v1/scans/{id}`, then loads the ranked findings.
5. **Agent** explains the top 5; the fact checker verifies them; if the LLM fails, they're marked unavailable.

Fix PRs and the daily refresh run on **GitHub Actions** (architecture §3.1–3.2).

---

## 4. Decisions made and why

| ADR | Decision | Main reason |
|---|---|---|
| [0001](../adr/0001-github-app-over-oauth-repo-scope.md) | GitHub App, not OAuth `repo` scope | Per-repo, fine-grained, short-lived access (least privilege) |
| [0002](../adr/0002-lockfiles-only-no-version-guessing.md) | Lockfiles only; "skipped: version unknown" | Exact versions → trustworthy, deterministic matches |
| [0003](../adr/0003-risk-tiers-and-stored-scores.md) | Deterministic tiers and scores; stored daily | Repeatable, testable ranking; history for story 8 |
| [0004](../adr/0004-vulnerability-data-sources.md) | OSV `querybatch`; KEV/EPSS bulk; `partial` on failure | Little code, same data as OSV-Scanner, never silently incomplete |
| [0005](../adr/0005-postgres-and-neo4j-split.md) | Postgres for records, Neo4j for the graph | Core question is a path query; graph is rebuildable |
| [0006](../adr/0006-per-service-graph-nodes.md) | Per-service graph nodes | Correct by construction; shared nodes saved almost no capacity |
| [0007](../adr/0007-free-tier-hosting-vercel-and-render.md) | Vercel + Render + Supabase + AuraDB | $0; fast website; real Python process |
| [0008](../adr/0008-background-scans-in-process.md) | Background scans inside the API | Free and simple; lost scans visible as `failed` |
| [0009](../adr/0009-daily-refresh-on-github-actions.md) | Daily refresh on Actions, restricted role | Memory for EPSS, no load on Render, least privilege |
| [0010](../adr/0010-fix-prs-built-in-github-actions.md) | Fix PRs in two isolated Actions jobs | Untrusted build code never shares a machine with the App key |
| [0011](../adr/0011-mcp-in-api-with-user-tokens.md) | MCP in the API, per-user tokens | Parity by design; strict isolation |
| [0012](../adr/0012-fetch-lockfiles-via-tree-api.md) | Tree API + blobs with a read token | Few requests, low memory, 5,000 req/h |
| [0013](../adr/0013-explanation-agent-and-llm.md) | LangGraph agent (LLM provider *Proposed*) | Visible, testable flow with a fact-check retry |
| [0014](../adr/0014-language-and-framework.md) | Python + FastAPI; Next.js + TypeScript | Best libraries for versions, agents, data; easy Vercel deploy |
| [0015](../adr/0015-npm-and-pypi-scope.md) | npm and PyPI only | Depth over breadth in 10–12 days |

Decisions changed during review (worth telling in interviews):
- **Shared → per-service graph nodes** after the capacity math showed relationships, not nodes, were the limit.
- **Lock regeneration moved from Render to GitHub Actions**, and then the **App key moved off Render entirely**,
  after noticing that a same-user process can read its parent's environment.
- **"Fix now" for malicious packages applies to dev dependencies too**, because install scripts run at install time.

Fixed after the `reviewer` subagent's review:
- **Confused deputy:** anyone could add a public repo by URL and ask for a fix PR on it. Ownership is now checked
  **live** when a fix is requested: the App installation's account must match the requester's **numeric GitHub
  ID**. Personal repos only; no webhooks (they could be forged, and a sleeping server misses them).
- **Two missing database grants** (`repo_id` for the fixer role; reading `finding_scores` for the refresh role).
- **Cache poisoning:** no caching in the fix workflow; `publish` also checks that the untrusted output changes only the
  manifest and lockfile, within a size limit.
- **Honest wording:** RLS limits *jobs*, not users; scores are *recorded*, not fully reproducible.
- **Facts:** Poetry dev/prod is detected from fields, not lock versions; npm `devOptional` counts as production; OSV
  batches hold at most 1,000 queries and may be paged.

---

## 5. Ten interview questions with model answers

**1. How is DepGuard different from Dependabot?**
Dependabot works one repo at a time and ranks by severity plus rules you write (EPSS is one filter). DepGuard
looks across all of a user's repos, ranks with fixed, documented tiers combining KEV, EPSS, CVSS and reach,
explains the top risks with checked facts, and exposes everything to AI assistants through MCP. It's meant to sit
beside Dependabot, not replace it.

**2. Why not just sort by CVSS?**
CVSS measures how bad an attack *would* be, not how *likely* it is. Most high-CVSS vulnerabilities are never
exploited. KEV tells us what's being exploited now and EPSS how likely exploitation is soon, so combining them cuts
noise. We measure that with a noise-reduction metric against a severity-only ranking.

**3. Why two databases? Couldn't Postgres do it all?**
Postgres could. At our scale a recursive query would probably be fast enough. We use Postgres as the source of
truth for records and Neo4j only for dependency paths, because "every path from my service to package X" is one
readable Cypher pattern. The cost is a second database; the graph can be rebuilt from lockfiles, so losing it
loses nothing.

**4. Two lockfiles resolve the same parent to different child versions. How do you keep paths correct?**
Each service has its own graph nodes, and edges only connect nodes of the same service, so a path can't cross
lockfiles. That's correct by construction. Shared nodes would need a filter on every edge in every query. I also
did the math: edges are N × d per service either way, so sharing nodes wouldn't have saved real capacity.

**5. Why doesn't the LLM do the scoring?**
Scoring must be deterministic and testable: the same input always gives the same order, and "every fix-now finding
ranks above every other finding" is a unit test. An LLM varies between runs, can invent facts and fails when the
free API is down. So code ranks and the LLM only explains, with a fact checker rejecting any ID or number not in our data.

**6. How do you defend against prompt injection in advisory text?**
The agent can't *do* anything: its tools are read-only lookups of our own data. Tiers, scores and fixes never come
from the LLM. Its output passes a deterministic fact checker and is shown as plain text. The worst case is a bad
explanation that fails the check and is replaced by "unavailable".

**7. Why do fix PRs run on GitHub Actions instead of your API server?**
Regenerating a lockfile can run untrusted code (Python source builds). On the same machine, even a subprocess
with a clean environment could read the parent process's environment and steal the App key. So the untrusted step
runs on a throwaway VM with no secrets, and a second job on another fresh VM, holding the key, treats the output
as data, checks the diff and opens the PR. The API server never holds the key.

**8. A scan takes a minute. How does the API handle that?**
It replies `202 Accepted` with a scan ID and runs the scan as a background task; the web app polls the status
endpoint. That avoids timeouts and survives the user closing the tab. On the free tier it runs in-process; a
restart marks the scan `failed` so the user can re-run it.

**9. What happens if OSV is down?**
Each call has a timeout and retries with exponential backoff. If a batch still fails, those packages are recorded
as unchecked and the scan is marked `partial` with the reason, never `done` with fewer findings. The UI says so
and offers a re-run.

**10. How do you stop one user from seeing another's data, including through MCP?**
Every query is filtered by the user from the verified JWT or API token; another user's IDs return 404. MCP tools
take no `user_id` argument; they work out the user from the token. Graph queries receive the user's service IDs
from Postgres, and tests check cross-user access for every endpoint and tool. Row-level security is on for every
table, but its job is different: it keeps Supabase's Data API out and limits what each background job can touch.
It doesn't separate users; the API code does, and the tests prove it.

---

## 6. Handoff

### Done
- Spec interview completed; [spec.md](../spec.md) written, incl. graph-capacity formula.
- [architecture.md](../architecture.md) with system, scan-flow, fix-flow and data-model diagrams.
- 15 ADRs + index; [security.md](../security.md) with threat model; [glossary.md](../glossary.md); these notes.
- Branch `docs/phase-0-design` created (renamed from `phase-0-spec-design`).
- `reviewer` subagent run; all findings fixed (section 4).

### Pending
- [ ] Commit and open the Phase 0 PR (after approval).
- [ ] **Confirm AuraDB Free limits in the Aura console** and update spec §8.1.
- [ ] Explain the architecture back in your own words (exercise skipped for now).
- [ ] Approve or adjust the *Proposed* risk-score weights (ADR-0003).
- [ ] Create `.env.example` with placeholders in the first code phase (names listed in security.md §4).

### Open issues
- **Time budget vs. scope:** MVP stories 1–7 (including fix PRs via Actions and MCP) in 10–12 days is tight.
  A phase plan should order work so a useful product exists early (scan → ranked findings → paths), with fix
  PRs and MCP last. A cut list is needed if time runs short.
- **Assumption `d` (average dependencies per entry)** must be measured on the benchmark repos; capacity numbers depend on it.
- **LLM provider** not chosen (ADR-0013); data-use terms to check.
- **Benchmark repo list** (~10 real public npm + Python repos) not chosen yet.
- **Public workflow logs** must be revisited before private repos are supported.
- **Per-user isolation in Postgres policies** (vs. API code + tests only) is undecided (security.md §12).
- **Organization repos** need their own ownership checks (members, roles) before fix PRs can support them.
