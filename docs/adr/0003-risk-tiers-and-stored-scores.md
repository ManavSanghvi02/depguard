# ADR-0003: Deterministic tiers and scoring, not LLM scoring; scores stored daily
- Status: Accepted (weights decided in phase 3; revisit with the noise-reduction metric in phase 4b)
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

### Risk score within a tier
```
risk_score = 0.5 × EPSS percentile  +  0.3 × (CVSS / 10)  +  0.2 × min(reach, 10) / 10   (range 0–1)
```
- **EPSS percentile, not the raw EPSS probability.** Outside "fix now", raw EPSS is below 0.1 by definition,
  so `0.5 × EPSS` would add at most 0.05 while CVSS adds up to 0.3: EPSS would barely count. The percentile
  spreads the same ranking over 0–1. The tier rule still uses raw EPSS ≥ 0.1.
- KEV and malicious status are **not** in the formula, because the tiers and subgroups already rank them first.
- Missing CVSS (common for `MAL-` advisories) counts as 0 in the formula; missing EPSS counts as 0.
- CVSS version: prefer v3.x, so advisories are comparable; use v4.0 only when no v3.x score exists. OSV gives
  vectors; the `cvss` library computes the base score. A merged advisory group uses its highest score.
- Computed with exact decimals and rounded to 4 places, so the score is identical on every machine.

**Worked example** (snyk-labs/nodejs-goof @ `add14ba`, production dependencies, one lockfile so reach = 1;
EPSS data of 2026-10-28; none are in KEV and all have EPSS < 0.1, so all three are "fix soon"):

| Finding | CVSS | EPSS | Percentile | Raw-EPSS formula (rejected) | Percentile formula |
|---|---|---|---|---|---|
| lodash 4.17.4, GHSA-jf85-cpcp-j695 / CVE-2019-10744 | 9.1 | 0.050 | 0.922 | 0.318 (1st) | **0.7540** (1st) |
| lodash 4.17.4, GHSA-p6mc-m468-83gw / CVE-2020-8203 | 7.4 | 0.052 | 0.925 | 0.268 (3rd) | **0.7045** (2nd) |
| dustjs-linkedin 2.5.0, GHSA-c6rp-wrp9-qr4q / CVE-2021-4264 | 8.8 | 0.012 | 0.668 | 0.290 (2nd) | **0.6180** (3rd) |

With raw EPSS, CVE-2020-8203 ranks below CVE-2021-4264 although it is 4.5× more likely to be exploited. A unit
test checks these three scores exactly.

### Reach
Reach = how many of the user's services contain the same package version (normalised) with the same merged
advisory, counted from **each repo's latest fully checked scan** (a scan where OSV answered for every package).
A scan with OSV-unavailable packages still gets its own findings scored, but it doesn't replace its repo's last
complete scan in the count; otherwise one OSV outage would lower the reach of the user's *other* repos while
they still say `done`. If a repo has no fully checked scan yet, its partial scan is counted and the score is
stored with `reach_complete = false` (reach may be too low). A finding's own service always counts.

### When a new score row is stored
A row is added only when an input changes: KEV membership, EPSS, EPSS percentile, CVSS, reach or
`reach_complete`. EPSS and its
percentile are **rounded to 3 decimals when loaded**: both are published with 5 decimals and nearly every value
moves slightly every day, which would add about one row per finding per day (~440 MB a year at 10,000
findings, against Supabase's 500 MB). Rounding moves a score by at most 0.0005.

## Trade-offs
- **Gain:** repeatable, testable, explainable ranking; works when the LLM is down; history for story 8.
- **Give up:** hand-tuned thresholds (EPSS 0.1, CVSS 7) and weights that are judgement calls, documented here so they
  can be challenged; extra storage for score history.
- **Revisit if:** the benchmark shows "fix now" is still too large to act on, or that important findings land in "monitor".
