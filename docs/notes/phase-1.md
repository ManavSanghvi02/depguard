# Phase 1 — Ingestion

> Branch: `feat/phase-1-ingestion` · Date: 2026-10-28

## Files
- `apps/api/src/depguard/config.py`: settings from env / repo-root `.env` (read token, dev-endpoint switch, limits).
- `apps/api/src/depguard/http.py`: requests with a 10 s timeout and 3 retries (backoff, `Retry-After`, short rate-limit waits).
- `apps/api/src/depguard/github/client.py`: `GitHubReader`: public-repo check, commit SHA, recursive tree, raw blobs.
- `apps/api/src/depguard/github/cache.py`: size-limited in-memory LRU for trees and blobs (keyed by SHA).
- `apps/api/src/depguard/parsers/models.py`: `Entry`, `Edge`, `SkippedPackage`, `ParsedService`, `ParseError`.
- `apps/api/src/depguard/parsers/__init__.py`: file name → lockfile type.
- `apps/api/src/depguard/parsers/names.py`: PEP 503 names; Python key `name==version`.
- `apps/api/src/depguard/parsers/common.py`: TOML loading, sorted edges.
- `apps/api/src/depguard/parsers/npm_lock.py`: `package-lock.json` v2/v3, using npm's lookup rule for edges.
- `apps/api/src/depguard/parsers/poetry_lock.py`: `poetry.lock` + sibling `pyproject.toml` for direct deps.
- `apps/api/src/depguard/parsers/uv_lock.py`: `uv.lock`; dev = not reachable from production.
- `apps/api/src/depguard/parsers/requirements_txt.py`: exact pins only; the rest is skipped.
- `apps/api/src/depguard/scan/ingest.py`: select lockfiles, apply limits, download, parse → `IngestResult`.
- `apps/api/src/depguard/routes/ingest.py`: dev-only `POST /v1/ingest`.
- `apps/api/tests/unit/…`: parser, HTTP, client, ingest and route tests; `fake_github.py` is the fake GitHub API.
- `apps/api/tests/fixtures/real/` + `README.md`: real lockfiles from 3 repos at pinned commits.

## Main flow
`POST /v1/ingest {owner, repo}` → repo is public? → default-branch SHA → tree → pick lockfiles (skip
`node_modules` and test folders; ≤ 25; ≤ 10 MB) → download blobs (cached) → parse each → `IngestResult` with
services, failed services and partial reasons.

## Decisions
- Python key `name==version` (ADR-0006 updated): uv/poetry locks can hold two versions of one package.
- Lockfiles in `test`, `tests`, `__tests__`, `fixtures`, `testdata` folders are skipped. This is a known difference
  from OSV-Scanner's recursive mode.
- `poetry.lock` direct deps come from the sibling `pyproject.toml`. Without one they are guessed (packages nothing
  depends on), and a partial reason is added.
- New skip reason `not_from_registry` for git, URL and local packages; OSV can't match them.
- One bad lockfile (parse error, over 10 MB, over 2,000 entries) fails only its service.
- `POST /v1/ingest` returns 404 unless `ENABLE_DEV_ENDPOINTS=true`, because it has no auth. It is replaced by
  the scans endpoint.
- Cache in memory, keyed by git SHA (never stale); downloads run one at a time (simple; fast enough).
- Tests use `httpx.MockTransport` and `asyncio.run`: no network and no extra test libraries.

## Handoff
### Done
- Four parsers, GitHub reader with retries and cache, ingest step, dev endpoint; 60 tests; `make lint` clean.
- Real run on 4 benchmark repos (2–11 s each). Textual: 2 services. poetry: 1 (13 fixture locks skipped).
  superset: 5 services plus 1 failed (`superset-frontend`, 3,037 entries > 2,000). vscode: hit the 25-lockfile limit.
- Benchmark list and phase plan recorded in spec §8.7–8.8.

### Pending
- [ ] Put a fine-grained, read-only `GITHUB_READ_TOKEN` in `.env` (public repos only) to use `/v1/ingest` locally.

### Open issues
- The 2,000-entry limit excludes real frontends (superset-frontend has 3,037). Revisit with the measured Aura numbers in phase 2.
- vscode keeps the first 25 lockfiles alphabetically, which are mostly small `.vscode/extensions` ones.
- `requirements/*.txt` folders (e.g. superset's `requirements/base.txt`) aren't picked up. This is a documented gap.
- poetry dependencies name a package, not a version. When a lock holds two versions, edges go to both.
- Starlette `httpx2` warning in tests (carried from 0b).
- Still open from Phase 0: LLM provider, risk-score weights, AuraDB limits.
