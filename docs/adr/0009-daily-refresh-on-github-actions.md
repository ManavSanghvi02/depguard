# ADR-0009: Daily refresh on GitHub Actions with a restricted database role
- Status: Accepted
- Date: 2026-10-28

## Context
KEV and EPSS change daily, and scores must be no older than 48 hours. Supabase Free pauses after about 1 week idle;
AuraDB Free after about 3 days without activity. Render's cron jobs are billed, and its free instance has 512 MB RAM and
sleeps when idle. The EPSS file covers every published CVE (hundreds of thousands of rows).

## Options

**Option A: a scheduled GitHub Actions workflow runs the refresh script and connects to the databases directly**
- Runners have far more memory than Render's free instance; no HTTP timeout; doesn't wake Render.
- Database credentials must also be stored in GitHub Actions.

**Option B: the workflow calls a protected `POST /internal/refresh` endpoint on Render**
- Database credentials stay only on Render.
- The heavy EPSS processing competes for 512 MB; a long-running request; a cold start first.

## Decision
**Option A**, made safe with least privilege:
- **Schedule:** daily at 03:00 UTC, plus a manual **"run now"** trigger (`workflow_dispatch`). GitHub disables
  scheduled workflows after 60 days without repo activity in public repos, so the manual trigger is the recovery path.
- **Postgres role `depguard_refresh`:** full access to `kev_entries`, `epss_scores`; `INSERT, SELECT` on
  `refresh_runs`; `SELECT` only on `findings`, `scans`, `services`, `advisories` and `repos(id, user_id)` (needed to
  rescore); `SELECT, INSERT` on `finding_scores` (it reads the latest score to know whether an input changed); **no access** to `profiles`, `api_tokens`, `explanations`, `fixes`. Row-level security stays on;
  the role gets explicit policies, **not `BYPASSRLS`** ([architecture §5.3](../architecture.md)).
- **Neo4j:** the Aura Free credential is **full-access** (a free-tier limit). It's stored on Render (the API
  needs it) and, for this job, only in the protected `daily-refresh` environment; the job runs a single `MERGE`
  to stay active.
- **Workflow hardening:** every action pinned to a full commit SHA; `permissions: contents: read`.
- **Keep-alive:** writing `refresh_runs` and the `SystemStatus` node keeps both databases from pausing.

## Trade-offs
- **Gain:** enough memory for EPSS; no load on Render; a single place for scheduled work.
- **Give up:** database credentials in a second place (limited by the role design); a full-access Aura credential
  in Actions (documented risk; rotate if exposed).
- **Revisit if:** we move to a paid host with cheap cron and enough memory.
