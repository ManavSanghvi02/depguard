# ADR-0002: Read lockfiles only; never guess versions
- Status: Accepted
- Date: 2026-10-28

## Context
Whether a vulnerability applies depends on the **exact installed version**. A manifest (`package.json`,
`pyproject.toml`) usually holds **ranges** like `^4.17.0` or `>=2.0`. A lockfile records the exact versions that were
actually installed, plus (in most formats) the full dependency tree.

## Options

**Option A: read manifests and resolve ranges ourselves** (e.g. assume the newest version that matches)
- Works for repos without lockfiles.
- The guess is often wrong, which produces **false alarms** or **missed vulnerabilities**, and the result changes over
  time as new versions are published, so it isn't deterministic.

**Option B: read lockfiles only; report anything without an exact version as skipped**
- Exact versions → exact matches; repeatable results; dependency paths where the format records them.
- Repos without lockfiles (or with unpinned `requirements.txt` lines) get less coverage.

## Decision
**Option B.** Supported in the MVP: `package-lock.json` (v2/v3), `poetry.lock`, `uv.lock`, and
`requirements.txt` (and `requirements-*.txt`) with `==` pins.
- **Dev vs. production is read from fields, not version numbers.** npm: `"dev": true` = dev; `"devOptional": true`
  (optional in the production tree) counts as production. `poetry.lock`: `category = "dev"` = dev (older Poetry,
  which can appear even in lock-version 2.0); `groups = [...]` without "main" = dev (Poetry 2.1+); neither → production.
  `requirements-dev.txt` and similar still count as production, because file names aren't reliable. Anything unpinned is shown as **"skipped: version unknown"**. When a lockfile
can't tell dev from production, the package is treated as **production**, which can only over-report a risk, never hide one.

## Trade-offs
- **Gain:** trustworthy, deterministic findings; DepGuard honestly says "I don't know" instead of guessing.
- **Give up:** coverage for repos without lockfiles; flat (pathless) results for `requirements.txt`.
- **Later:** `yarn.lock`, `pnpm-lock.yaml`, `Pipfile.lock`; partial paths from pip-tools `# via` comments.
