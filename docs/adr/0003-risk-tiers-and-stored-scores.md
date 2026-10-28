# ADR-0003: Deterministic tiers and scoring, not LLM scoring; scores stored daily
- Status: Accepted (the within-tier score weights are **Proposed** until checked on the benchmark repos)
- Date: 2026-10-28

## Context
Ranking is the heart of DepGuard. Users must be able to trust the order, and the success metrics require it to be
**deterministic** (same inputs → same order) and **testable** ("every fix-now finding ranks above every other
finding"). EPSS and KEV change daily, so scores must stay current, and story 8 needs history.

## Options

### Who decides the ranking?
**Option A: deterministic code.** Fixed rules and a formula over KEV, EPSS, CVSS, reach and dev/prod.
- Same input → same output; every rule is unit-tested; the score breakdown can be shown and explained.
- Rules must be designed and tuned by hand.

**Option B: an LLM ranks or scores findings.**
- Could weigh context we didn't code for.
- Not repeatable (output varies between runs and model versions), can't be tested exactly, can invent facts,
  costs LLM calls per finding, and fails completely when the free LLM is unavailable.

### When are scores computed?
**Option C: compute on every read** from the latest data. Always fresh, but there's no record of past scores.
**Option D: recompute after each daily refresh and store**, tagged with the data date. Every score is **recorded**
with the data it was based on, which gives story 8 its history; costs storage. (This is a record, not full
reproducibility: only the latest KEV/EPSS snapshot is kept and OSV data changes, so an old scan can't be re-run
identically.)

## Decision
**A + D.** Code computes tiers and scores; the LLM only explains results afterwards. Scores are recomputed after each
daily refresh and stored with their `data_date`, with **a new row only when an input changed** (saves the 500 MB
Supabase limit).

### Tiers
| Tier | Rule |
|---|---|
| **Fix now** | Known malicious (OSV `MAL-`) in **any** dependency, **or** (in KEV **or** EPSS ≥ 0.1) in a **production** dependency |
| **Fix soon** | (In KEV **or** EPSS ≥ 0.1) in a **dev-only** dependency, **or** CVSS ≥ 7 in production |
| **Monitor** | Everything else |

Why malicious packages are "fix now" even in dev dependencies: they often run code at **install** time (e.g. npm
install scripts), which harms developer machines and CI. KEV or a high EPSS in a dev-only package is less urgent
because that code doesn't run in production.

### Sort order (one sort key)
`(tier_rank, subgroup_rank, -risk_score, advisory_id, package_name)`
- `subgroup_rank` applies inside "fix now": malicious → KEV → EPSS-only.
- `advisory_id` then `package_name` are the **deterministic tie-breakers**.
- A test asserts that tiers are always in order.

### Risk score within a tier (*Proposed*)
```
risk_score = 0.5 × EPSS  +  0.3 × (CVSS / 10)  +  0.2 × min(reach, 10) / 10        (range 0–1)
```
- KEV and malicious status are **not** in the formula, because the tiers and subgroups already rank them first.
- Missing CVSS (common for `MAL-` advisories) counts as 0 in the formula; missing EPSS counts as 0.
- CVSS version: prefer v3.x, so advisories are comparable; use v4.0 only when no v3.x score exists.
- Weights to be checked against the noise-reduction metric on the benchmark repos before acceptance.

## Trade-offs
- **Gain:** repeatable, testable, explainable ranking; works when the LLM is down; history for story 8.
- **Give up:** hand-tuned thresholds (EPSS 0.1, CVSS 7) and weights that are judgement calls, documented here so they
  can be challenged; extra storage for score history.
- **Revisit if:** the benchmark shows "fix now" is still too large to act on, or that important findings land in "monitor".
