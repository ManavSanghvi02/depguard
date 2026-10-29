# Test fixtures

Real lockfiles from public repos, copied unchanged at a fixed commit so tests are repeatable.
Small hand-made lockfiles for edge cases live inline in the tests.

| Folder | Source repo | Commit | License | Files (original path) |
|---|---|---|---|---|
| `real/defectdojo` | [DefectDojo/django-DefectDojo](https://github.com/DefectDojo/django-DefectDojo) | `4ac58d79e70039e6cf0d8ff913758a7744ce343a` | BSD-3-Clause | `docs/package-lock.json` (v3), `requirements.txt` |
| `real/full-stack-fastapi-template` | [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) | `f4bcfaba7c85be3c6332cc74a20819f586dcdbc6` | MIT | `uv.lock` |
| `real/textual` | [Textualize/textual](https://github.com/Textualize/textual) | `5e5b7ef58b8c5572c13a3ff9027d756623661495` | MIT | `poetry.lock`, `pyproject.toml`, `uv.lock` (empty) |

Downloaded on 2026-10-28 with `gh api -H "Accept: application/vnd.github.raw" repos/<repo>/contents/<path>?ref=<commit>`.
