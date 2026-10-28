# ADR-0015: Support npm and PyPI only
- Status: Accepted
- Date: 2026-10-28

## Context
Every package ecosystem has its own lockfile formats, version rules and fix mechanics. The project has about
10–12 days and one developer. The spec values depth (dependency paths, minimal fix PRs, explanations) over a
long list of supported languages.

## Options

**Option A: npm and PyPI only**
- The two ecosystems most used by small web and data teams (the target user).
- Six lockfile formats in total (`package-lock.json`; `poetry.lock` in three formats; `uv.lock`; pinned
  `requirements.txt`), and two version rule sets (npm semver, PEP 440).
- Leaves time for the hard features: paths, tiers, fix PRs and MCP.

**Option B: many ecosystems from the start** (adding Maven, Go, Cargo and others)
- Wider appeal; would cover cases like Log4Shell (Java).
- Each ecosystem adds parsers, version rules and fix logic, which leaves shallow support everywhere within the time budget.

## Decision
**npm and PyPI only.** Other ecosystems are an explicit non-goal (spec §6).

## Trade-offs
- **Gain:** depth and correctness in two ecosystems, with every parser tested against real lockfiles.
- **Give up:** users on other ecosystems; Log4Shell-style Java incidents aren't covered (the spec says so).
- **Keep the door open:** parsers and version comparators sit behind small interfaces (`parsers/`, `versions/`), so
  adding an ecosystem later means adding a parser, a version comparator and a fix strategy, without changing scoring or the graph.
- **Revisit if:** users ask for a specific ecosystem after the MVP.
