# Phase 2 — Dependency graph

> Branch: `feat/phase-2-graph` · Date: 2026-10-28

## Files
- `apps/api/src/depguard/db/neo4j.py`: one async driver per process (created at startup, doesn't connect).
- `apps/api/src/depguard/graph/schema.py`: constraints and indexes, `IF NOT EXISTS`, run before each write.
- `apps/api/src/depguard/graph/capacity.py`: `has_room` (90% rule) and node/relationship counts.
- `apps/api/src/depguard/graph/writer.py`: `write_service` (check room, replace in one transaction, batches of 1,000), `remove_stale_services`.
- `apps/api/src/depguard/graph/queries.py`: `service_tree`, `shortest_paths` (up to 3), `services_containing`, `repo_services`.
- `apps/api/src/depguard/scan/graph.py`: scan step 7; full or unreachable graph → partial reasons, never a failed scan.
- `apps/api/src/depguard/routes/graph.py`: dev-only `POST /v1/dev/graph` and `GET` tree / paths / services.
- `apps/api/src/depguard/parsers/poetry_constraints.py`: picks which locked version(s) a Poetry dependency points to.
- `apps/api/src/depguard/parsers/__init__.py`: `.txt` files in a `requirements/` folder now count.
- `apps/api/tests/integration/`: tests against real Neo4j (skipped locally if it's down; required in CI).
- `.github/workflows/ci.yml`: Neo4j service container for the integration tests.

## Main flow
`POST /v1/dev/graph {owner, repo}` → ingest (phase 1) → for each service: capacity check → replace its graph
in one transaction → delete graphs of the repo's services that are gone or failed → return ingest result,
per-service graph status and partial reasons. Reads: `GET /v1/dev/services/{id}/tree`,
`GET /v1/dev/services/{id}/paths?key=…`, `GET /v1/dev/repos/{owner}/{repo}/services?ecosystem=&name=&version=`.

## Decisions
- Entry cap raised from 2,000 to 5,000 so real frontends fit. Cost: ~36 maximum-size services fit on Aura
  Free instead of ~99 (spec §8.1).
- Measured `d` = 1.0–2.23 (superset-frontend is the highest), so nodes and relationships run out at about the
  same point.
- Poetry: version constraint, then markers, narrow the candidates. A step that would leave nothing is skipped,
  so edges are never lost. If several are still possible, each edge is `ambiguous` and paths show it.
  Markers are checked against fixed test environments (Python 2.7 and 3.6–3.14 × Linux/Windows/macOS, plus each extra a marker names), so the result
  doesn't depend on the server.
- Service and repo IDs are `uuid5` of the GitHub URL and lockfile path until Postgres exists; only the dev
  route builds them.
- A service refused for space keeps its old graph. Services gone or failed this scan are removed *before*
  writing (so a moved lockfile's old copy doesn't block the capacity check), but only when the file list was
  complete: a truncated tree or the 25-lockfile cap leaves unlisted graphs alone (`all_lockfiles_seen`).
- The graph step never fails a scan: a failed write affects only that service ("graph write failed"); an
  unreachable Neo4j stops the step ("graph database unreachable"). Both are logged.
- Extra indexes beyond §5.1: `dep_service` on `Dep.service_id` (every "this service's nodes" lookup; the
  two-property `dep_key` index isn't used for it) and `service_repo` on `Service.repo_id`.
- Equally short paths are sorted by the keys along them in Cypher before the limit, so results are stable.
- The capacity check isn't atomic across concurrent writes; the 10% headroom covers it.

## Handoff
### Done
- Graph writer, the 3 queries, capacity check, dev endpoints, the three phase-1 fixes; 112 tests (12 against
  Neo4j); `make lint` clean.
- Reviewer findings fixed: missing `service_id` index, uncaught graph errors, stale deletion on incomplete
  file lists, unstable paths, malformed poetry.lock / pyproject tables crashing ingest (now `ParseError`),
  versions for Python < 3.8 dropped, `extra` markers blocking narrowing, cleanup order, diagram, naming.

- Real run through the dev endpoints (GitHub + local Neo4j), ingest and graph write together:
  - Textual: 2 services, 6.9 s. full-stack-fastapi-template: 1 service, 2.5 s.
  - superset: 9 services, all written, no partial reasons, 8.1 s. superset-frontend (3,037 entries, 6,772
    edges) now fits; `requirements/base.txt`, `development.txt` and `translations.txt` are picked up.
  - Queries on superset-frontend: full tree 2.8 s; paths 0.01–0.07 s (e.g. antd → @ant-design/cssinjs →
    nested @emotion/hash); "which services contain it" correct.
  - No ambiguous Poetry edges in real locks so far.

### Pending
- [ ] Confirm the real AuraDB Free limits in the Aura console; update `GRAPH_MAX_*` and spec §8.1 if they differ.

### Open issues
- Poetry constraints in `^` / `~` form aren't parsed, so they don't narrow (edges may stay ambiguous).
- Poetry 2's per-package `markers` field in poetry.lock isn't used yet.
- Junk `.txt` files in a `requirements/` folder become `version_unknown` skips.
- Empty lockfiles (Textual's `uv.lock`, superset's `RELEASING/requirements.txt`) become services with no
  entries; harmless, but they count towards the 25-lockfile limit.
- The full-tree query takes ~3 s for a 3,000-entry service (mostly response size); fine for a dev endpoint.
- Versions are matched as exact strings in `services_containing`; normalisation comes with `versions/` (phase 3).
- vscode's 25-lockfile limit, the Starlette `httpx2` warning, and the Phase 0 open items (LLM provider, score
  weights) are still open.
