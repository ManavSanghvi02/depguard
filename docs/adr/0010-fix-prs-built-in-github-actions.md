# ADR-0010: Fix PRs built in GitHub Actions with two isolated jobs
- Status: Accepted
- Date: 2026-10-28

## Context
A fix PR needs a correct new lockfile. Editing lockfiles by hand produces broken files, so the ecosystem's own
tool must regenerate them (`npm install --package-lock-only`, `uv lock`, `poetry lock`). That runs **untrusted code**:
npm scripts can be turned off, but Python locking may **build packages from source**, which runs their `setup.py`.
Opening the PR needs the **GitHub App private key**, the most sensitive secret.

**How to fix a transitive vulnerability** is part of this decision: first try bumping the **parent** to a version
that allows the fixed child; otherwise use npm `overrides` or uv `override-dependencies`. Pinned `requirements.txt`
is a plain text edit.

## Options

**Option (a): regenerate on Render** with `--package-lock-only --ignore-scripts`, a temp folder, a timeout, and a
subprocess started without secrets.
- Fast (seconds) and simple.
- **A clean environment isn't enough on the same machine:** on Linux, a process running as the same user can read
  its parent's environment through `/proc/<pid>/environ`, so untrusted build code could still reach the App key.
- Competes for Render's 512 MB; needs npm, uv and Poetry in the API image.

**Option (b): regenerate in a GitHub Actions workflow started by the API.**
- Untrusted code runs on a **fresh virtual machine that's destroyed afterwards** and holds **no secrets**.
- Slower (about 30–90 s for a runner to start); dispatching and tracking a workflow adds complexity; a separate
  token is needed to start it.

## Decision
**Option (b)**, split into two jobs in `fix-lock.yml`, each on its own fresh VM:

1. **`regenerate` (untrusted):** **no secrets**, job token `contents: read`. Fetches the public lockfile and manifest,
   runs the tool (npm scripts disabled), with a timeout, and uploads the changed files as an artifact.
2. **`publish` (trusted):** `needs: regenerate`, `if: always()`, protected **`fix-pr` environment** holding the
   **App private key** and the **`depguard_fixer`** database role. It re-reads the authoritative plan from
   Postgres by `fix_id`, treats the artifact as **data only** (never executes it), checks that it contains **only the planned
   manifest and lockfile paths**, each within a **size limit**, runs the **diff checker**
   (only the target package or its parent changes in the manifest; lockfile changes stay within that package's subtree;
   no unrelated version changes; no package names change; major bumps labelled) and re-checks the target version
   against OSV. It then **checks ownership live**: it looks up the App installation for the repo and opens the PR
   only if the installation's account is the requester's numeric GitHub ID (personal repos only;
   [ADR-0001](0001-github-app-over-oauth-repo-scope.md)). Otherwise it stores a patch. Finally it writes the status.

**Render never holds the App private key.** It plans the fix, dispatches the workflow with a token scoped
**only to the DepGuard repo** (Actions read/write), and reads fix status from Postgres. Fixes unfinished after 20
minutes are reported as timed out.

Further safeguards:
- **No caching** in either job (no `actions/cache`, no setup-action caches). Otherwise the untrusted job could
  plant files in GitHub's shared cache that the trusted job later loads (**cache poisoning**).
- **Input injection:** workflow inputs are passed through `env:` and checked against strict patterns. They're never
  inserted directly into `run:` scripts.
- **Pinned actions:** every action is pinned to a full commit SHA, with minimal `permissions:`.
- **`depguard_fixer` role:** reads `fixes`, `findings`, and only the needed columns of `services` and `repos`; it can
  update only the status and result columns of `fixes`.

## Trade-offs
- **Gain:** untrusted code and the App key never share a machine; the API image stays small; Render's memory is spared.
- **Give up:** latency (fixes are asynchronous anyway); more parts to explain (dispatch, artifacts, environments);
  a dispatch token on Render.
- **Must revisit before private repos:** workflow **logs are public** in a public repo. That's acceptable while
  DepGuard only scans public repos, but not once private code could appear in logs.
- Actions minutes are limited while the DepGuard repo is private.
