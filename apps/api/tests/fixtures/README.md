# Test fixtures

Real lockfiles from public repos, copied unchanged at a fixed commit so tests are repeatable.
Small hand-made lockfiles for edge cases live inline in the tests.

| Folder | Source repo | Commit | License | Files (original path) |
|---|---|---|---|---|
| `real/defectdojo` | [DefectDojo/django-DefectDojo](https://github.com/DefectDojo/django-DefectDojo) | `4ac58d79e70039e6cf0d8ff913758a7744ce343a` | BSD-3-Clause | `docs/package-lock.json` (v3), `requirements.txt` |
| `real/full-stack-fastapi-template` | [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) | `f4bcfaba7c85be3c6332cc74a20819f586dcdbc6` | MIT | `uv.lock` |
| `real/textual` | [Textualize/textual](https://github.com/Textualize/textual) | `5e5b7ef58b8c5572c13a3ff9027d756623661495` | MIT | `poetry.lock`, `pyproject.toml`, `uv.lock` (empty) |

Downloaded on 2026-10-28 with `gh api -H "Accept: application/vnd.github.raw" repos/<repo>/contents/<path>?ref=<commit>`.

The agent evals (docs/evals.md) also use two lockfiles under `apps/api/evals/lockfiles/`:
- `nodejs-goof/package-lock.json` from [snyk-labs/nodejs-goof](https://github.com/snyk-labs/nodejs-goof)
  (Apache-2.0) at `add14ba59e98240d9e00a235dd7d42cd61ae9912`. At 760 KB it is over the 500 KB
  pre-commit limit, so it isn't committed: `make golden` downloads it and checks its SHA-256
  (`apps/api/evals/cases.toml`).
- `event-stream/package-lock.json`, hand-made: event-stream 3.3.6 and the malicious flatmap-stream
  0.1.1 it pulled in (the 2018 incident), with event-stream's other dependencies left out.

## Recorded API responses

| Folder | Source | Recorded | What |
|---|---|---|---|
| `osv/` | [api.osv.dev](https://google.github.io/osv.dev/api/) (CC-BY 4.0 / per-advisory licenses) | 2026-10-28 | `querybatch.json`: one real querybatch request and answer (lodash 4.17.4, dustjs-linkedin 2.5.0, express-fileupload 0.0.5 from snyk-labs/nodejs-goof; jinja2 2.10; the malicious flatmap-stream 0.1.1; ms 2.1.3 with no advisories). `vulns/`: `GET /v1/vulns/{id}` for every ID in it. |
| `feeds/` | [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) (public domain), [FIRST EPSS](https://www.first.org/epss/) | 2026-10-28 | `kev-sample.json`: the real catalog cut to 4 entries. `epss-sample.csv`: the real file's header and first 4 rows, plus the 3 CVEs used in ADR-0003's example. |
