# DepGuard vs OSV-Scanner

> Correctness check for story 2 and spec §7: every difference from OSV-Scanner is explained here.
> Run with `make compare` (fixtures) or `make compare ARGS="--repo OWNER/NAME"`; script:
> `apps/api/scripts/compare_osv_scanner.py`. Phase 4b runs it on every benchmark repo pinned to a commit.

## How the comparison works
- Both tools read the same lockfile and both use OSV's data, so a difference means the tools read the lockfile
  differently (which packages, which versions) or group aliases differently.
- One finding = one package version + one problem. DepGuard's merged alias group and OSV-Scanner's group count
  as the same finding if they share any ID or alias (GHSA, PYSEC, CVE…), so different "main" IDs don't count.
- Package versions are compared after normalising (PEP 503 names, PEP 440 / SemVer versions).
- OSV-Scanner runs with `--no-resolve` (see difference 2).
- The counts are distinct (package version, problem) pairs. A scan reports one finding per **install path**, so
  it can show more: nodejs-goof's scan has 433 findings for these 314 pairs, because 20 package versions are
  installed at several paths (lodash 4.17.15 at 10, debug 3.2.6 at 10, semver 6.3.0 at 8…). Each path is a
  separate copy on disk with its own dependency path and fix, so the scan keeps them apart (ADR-0006).

## Results (2026-10-28, OSV-Scanner 2.7.0)

| Lockfile | DepGuard | OSV-Scanner | Differences | Cause |
|---|---|---|---|---|
| DefectDojo `docs/package-lock.json` (fixture) | 1 | 1 | 0 | — |
| DefectDojo `requirements.txt` (fixture) | 1 | 1 | 0 | — (4 vs 1 without `--no-resolve`: difference 2) |
| full-stack-fastapi-template `uv.lock` (fixture) | 1 | 1 | 0 | — |
| Textual `poetry.lock` (fixture) | 125 | 125 | 0 | — |
| snyk-labs/nodejs-goof @ `add14ba` `package-lock.json` | 314 | 268 | 46, all DepGuard only | 1 |
| OWASP/NodeGoat @ `c5cb68a` `package-lock.json` | 315 | 203 | 112, all DepGuard only | 1 |

OSV-Scanner found nothing that DepGuard missed.

## Explained differences

### 1. Bundled npm dependencies: DepGuard reports them, OSV-Scanner skips them
- **What:** entries marked `"inBundle": true` in package-lock.json. These packages ship *inside* another
  package's tarball (its `bundleDependencies`) instead of being downloaded from the registry on their own.
- **Where:** all 46 goof differences are inside `nyc` (e.g. handlebars 4.0.11, lodash 4.17.10, set-value 2.0.0,
  8 copies of kind-of 6.0.2). All 112 NodeGoat differences are inside `nyc`, `npm` and `fsevents`. Checked one by
  one: every DepGuard-only package version is bundled at every path where it appears.
- **Why DepGuard keeps them:** npm extracts bundled packages into `node_modules` like any other, and their code
  runs. The vulnerable version really is installed, so dropping it would hide a real risk.
- **Consequence for fixes (phase 5):** a bundled package can't be upgraded or overridden on its own. The only
  fix is a newer version of the package that bundles it (here `nyc`). The fix planner must handle this.

### 2. requirements.txt: OSV-Scanner guesses transitive versions by default
- **What:** for DefectDojo's `requirements.txt`, OSV-Scanner reports anyio 4.9.0 and idna 3.9.0, which the file
  doesn't list. By default it resolves a requirements file's transitive dependencies and picks versions for them.
- **Why DepGuard differs:** DepGuard reads only what the lockfile pins and never guesses versions (ADR-0002); a
  plain requirements file has no transitive versions to read. With `--no-resolve` OSV-Scanner reports exactly
  the same as DepGuard, so the script uses that flag to compare like with like.
