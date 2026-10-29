# Phase 3 — Vulnerabilities and scoring

> Branch: `feat/phase-3-vulns` · Date: 2026-10-28

## Files
- `apps/api/alembic/`, `alembic.ini`: migrations as the owner (`MIGRATION_DATABASE_URL`); `0001` = 11 tables, two roles, RLS + grants + policies.
- `db/models.py`: SQLAlchemy tables. `db/postgres.py`: asyncpg engine/session, 503 if not configured.
- `db/set_role_passwords.py`: sets `depguard_api` / `depguard_refresh` passwords from their own URLs (`make migrate`).
- `versions/`: `normalize`, `first_fixed`, `highest`, `is_major_bump` (npm: `semver`; PyPI: `packaging`).
- `parsers/poetry_constraints.py`: `allows()` now uses poetry-core, so `^` / `~` / `||` narrow edges.
- `advisories/osv.py`: querybatch (≤1,000 per request, page tokens) and `get_vuln`, with retries.
- `advisories/cache.py`: advisory cache; refetch only if missing, never fetched, or modified since.
- `advisories/aliases.py`: merge advisories sharing IDs/aliases (transitively); representative ID.
- `advisories/cvss.py`: base score from vectors (`cvss` library), v3.x before v4.0.
- `advisories/feeds.py`: KEV JSON and EPSS CSV parsers, size checks, 3-decimal rounding.
- `scoring/score.py`: tier, subgroup, risk score, sort key (pure, `Decimal`). `scoring/rescore.py`: reach, insert-on-change.
- `scan/match.py`: steps 4–6; `build_findings` has no I/O (the comparison script reuses it).
- `scan/pipeline.py`: start/run a scan, status, partial reasons, startup cleanup of interrupted scans.
- `routes/scans.py`: dev `POST /v1/dev/scans`, `GET /v1/dev/scans/{id}`, `GET /v1/dev/scans/{id}/findings?tier=`.
- `routes/dev.py` (was `ingest.py`): shared dev pieces, fixed dev user. `routes/graph.py`: Postgres service IDs.
- `graph/*`: `Dep.norm_version`, index `dep_package_norm` replaces `dep_package`.
- `jobs/daily_refresh.py`: `make refresh`. `scripts/compare_osv_scanner.py`: `make compare [ARGS="--repo o/n"]`.
- `docs/osv-scanner-comparison.md`: comparison results and every difference explained.
- `.github/workflows/daily-refresh.yml`: manual trigger only, not usable until deploy. `ci.yml`: Postgres service.
- Tests: `tests/fake_osv.py` + recorded OSV/KEV/EPSS fixtures; integration tests for roles, pipeline, refresh.

## Main flow
`POST /v1/dev/scans {owner, repo}` → upsert dev profile + repo, `scans(queued)`, 202 → background: ingest →
upsert services → unique package versions to OSV querybatch → fetch uncached advisory details → per entry, merge
advisories, compute fixed version → findings + skipped rows → Neo4j graph → `rescore(user)` (reach, KEV/EPSS by
CVE alias, tier, score; row only on change) → `done` / `partial` / `failed`.
`make refresh` → download + check KEV and EPSS → TRUNCATE + insert in one transaction → `rescore(all)` → `refresh_runs`.

## Decisions
- Score weights (ADR-0003, now Accepted): `0.5 × EPSS percentile + 0.3 × CVSS/10 + 0.2 × min(reach,10)/10`.
  The percentile, because raw EPSS is < 0.1 outside "fix now" and barely moved the score. Worked example on
  nodejs-goof in the ADR; a unit test checks it, and the real scan gives the same numbers.
- EPSS and percentile rounded to 3 decimals on load: otherwise ~1 new score row per finding per day.
- The API connects as `depguard_api`, never the owner (a superuser ignores RLS, so tests would prove nothing).
  Tests use `SET ROLE` on a separate `depguard_test` database, so they need no role passwords and never touch dev data.
- asyncpg instead of psycopg (the plan said psycopg): psycopg's async mode can't run on Windows' default event loop.
  One driver everywhere, including Alembic.
- RLS forbids `COPY`, so EPSS (~397,000 rows) is loaded with one `INSERT … SELECT FROM unnest(arrays)`: ~11 s for the whole refresh.
- Database URLs use `127.0.0.1`: on this machine `localhost` tries IPv6 first and each connection waited ~5 s.
- Merging: representative GHSA → PYSEC → MAL → other; highest CVSS; the highest of the members' first fixed
  versions; malicious if any `MAL-` ID. An ID whose details failed stays as an ID-only finding (scan `partial`).
- Reach counts each repo's latest *fully checked* scan (`scans.osv_complete`), so an OSV outage in one repo
  can't lower other repos' reach. A repo with no complete scan counts its partial one and the score row says
  `reach_complete = false`. Every scan rescores the whole user, so other repos pick up new reach at once.
  (Reviewer #1; your decision.) The two columns went into the unshipped `0001` migration; local databases rebuilt.
- Bundled npm dependencies (`inBundle`) are reported, unlike OSV-Scanner: they are installed and their code runs.
  The comparison script runs OSV-Scanner with `--no-resolve` so neither side guesses requirements.txt versions.
- `refresh_runs` is written now (it's the run record); it becomes the Supabase keep-alive at deploy. The Neo4j
  `SystemStatus` write waits for deploy.
- Tier and score code is one file (`scoring/score.py`) instead of the planned `tiers.py` + `score.py`: ~70 lines together.
- `POST /v1/ingest` and `POST /v1/dev/graph` removed; the dev scan endpoint does both.

## Handoff
### Done
- Everything in the plan; 230 tests (unit + integration on real Postgres and Neo4j); `make lint` clean.
- Real runs (local databases, real GitHub/OSV/KEV/EPSS):
  - `make refresh`: 1,762 KEV, 396,966 EPSS, ~11 s; a second run adds 0 score rows.
  - nodejs-goof: `done`, 9.1 s, 433 findings (20 fix now, 149 fix soon, 264 monitor). First: jquery 2.2.4
    (in KEV). The three ADR examples score 0.7540 / 0.7045 / 0.6180.
  - DefectDojo: `done`, 4.1 s, 2 findings. superset: `done`, 10.8 s, 79 findings; packages in both
    `requirements/*.txt` files show reach 2.

- Reviewer findings fixed: ID lists sent as one array (asyncpg's 32,767-parameter limit would have broken the
  refresh at ~33k findings), clearer partial reason for ID-only findings, findings query limited to the scan,
  a failed refresh database step is recorded, npm `0.0.x` bumps flagged as breaking, range-edge tests,
  placeholder passwords refused for non-local databases.

### Pending
- OSV-Scanner comparison ([docs/osv-scanner-comparison.md](../osv-scanner-comparison.md)): the 4 fixture
  lockfiles agree exactly (Textual: 125 = 125). nodejs-goof 314 vs 268 and NodeGoat 315 vs 203: all 158
  differences are bundled npm dependencies (inside nyc, npm, fsevents) that OSV-Scanner skips. Nothing that
  OSV-Scanner found was missed.
- Why goof shows 433 findings in the scan and 314 in the comparison: the scan has one finding per install path,
  the comparison one per distinct package version; 20 package versions are installed at several paths.
- Reach fix (reviewer #1) with two integration tests: an OSV outage in one repo leaves another repo's reach at
  2, and a repo with only a partial scan marks reach incomplete.
- [ ] Phase 5: a bundled npm dependency can only be fixed by bumping the package that bundles it.
- [ ] Phase 4b: run the comparison on all benchmark repos pinned to a commit.
- [ ] Deploy phase: revoke Supabase's default `anon` / `authenticated` grants on our tables (TRUNCATE skips
  RLS; defence in depth); schedule + `daily-refresh` environment + `REFRESH_DATABASE_URL` secret, Neo4j keep-alive,
  run `make migrate` against Supabase. AuraDB limits still to confirm.

### Open issues
- Supabase URLs often end in `?sslmode=require`, which asyncpg doesn't accept (it wants `ssl=require`); handle at deploy.
- npm lockfiles with many nested copies give one finding per copy (goof: lodash 4.17.15 ×10). Correct per the
  spec (different paths), but noisy; the UI may want to group them.
- A merged group whose members have no fix but another member has one reports that fix (highest known).
- Advisory cache rows are written inside the scan's long transaction; two parallel scans sharing advisories
  wait on each other (a rare deadlock fails one scan). A separate short transaction would fix it.
- An ID-only finding (details failed) can't be looked up in KEV/EPSS, so its tier may be too low; the partial
  reason says so.
- Score rows from old scans are kept forever; only latest scans are rescored. Pruning can wait.
- Findings don't say whether an entry is bundled; the UI and fix planner may want that flag.
- LLM provider: Phase 4a.
