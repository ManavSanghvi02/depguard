# ADR-0008: Background scans inside the API process
- Status: Accepted
- Date: 2026-10-28

## Context
A scan can take about a minute (many GitHub and OSV calls). Holding an HTTP request open that long risks timeouts and
loses the work if the user's connection drops. The API must reply immediately (`202` + scan ID) and run the scan
in the background. Hosting must stay free ([ADR-0007](0007-free-tier-hosting-vercel-and-render.md)).

## Options

**Option A: FastAPI `BackgroundTasks` in the same process**, with the scan's state stored in `scans.status`
- Nothing extra to host; simple to read and test.
- If the API restarts mid-scan, that scan is lost.

**Option B: a job queue (e.g. Redis) and a separate worker process**
- Survives restarts; automatic retries; scales out.
- Render's background workers aren't free; a Redis service to run; more moving parts to explain.

## Decision
**Option A.** Each scan's progress is stored in Postgres (`queued → running → done | partial | failed`). On
startup the API marks any scan still `running` as `failed` ("server restarted"), so a lost scan is visible and the
user can re-run it.

## Trade-offs
- **Gain:** $0, simplicity, fewer components.
- **Give up:** no automatic recovery after a restart; one process does both web requests and scans.
- **Revisit if:** scans are lost often, or traffic grows. Moving to a queue only changes how the pipeline is
  *started*, not the pipeline code.
