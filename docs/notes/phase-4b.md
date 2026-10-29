# Phase 4b — Agent evals

> Branch: `feat/phase-4b-evals` · Date: 2026-10-29

## Files
- `evals/cases.toml`: the 24 cases (20 real findings, 3 prompt injections, 1 Gemini fallback).
- `evals/golden_set.json`: generated; every fact the agent sees, plus the OSV records they came from.
- `evals/lockfiles/event-stream/package-lock.json`: hand-made, for the malicious flatmap-stream 0.1.1.
- `scripts/build_golden_set.py` (`make golden`): builds the golden set with the scan's own code; `--list` shows candidates.
- `src/depguard/evals/golden.py`: loads the golden set into `FindingContext`s.
- `evals/claims.py`: deterministic free-text claim rules (trigger phrases, negation, support in the advisory text or a flag).
- `evals/checks.py`: fact check on the delivered text, injection markers, bundled wording.
- `evals/run.py` (`make evals`): runner; budget check, same pacing, forced fallback, report, `--write-doc`.
- `agent/graph.py`, `agent/explain.py`: the result also carries attempts, tokens and every rejected submission.
- `agent/llm.py`, `config.py`: Gemini fallback is an ordered list (`GEMINI_MODELS`) with its own timeout.
- `.github/workflows/evals.yml`: manual "Agent evals" workflow (`evals` environment, no cache, report in the summary).
- `tests/fixtures/real/nodejs-goof/package-lock.json`: real lockfile at a fixed commit.
- Tests: `tests/unit/evals/*`, `tests/unit/agent/test_llm.py`, new cases in `test_explain.py` and `test_graph.py`.
- Docs: `docs/evals.md` (new); `spec.md` §7 and §8.8, ADR-0013, `architecture.md` §4, `security.md` T2/§8/§9, fixtures README.

## Main flow
`make golden`: parse the case lockfiles → OSV querybatch + details → `build_findings` → KEV/EPSS → `inputs_for` →
`tier` → paths (BFS, up to 3 shortest) → `golden_set.json`.
`make evals`: load the golden set → budget check (stop before any call if it can't fit) → per case, one at a time:
wait until 4,500 tokens fit in the per-minute budget → `explain()` (Groq only; the fallback case gets a broken Groq
model so the real Gemini path runs) → fact check again on the delivered text, claim rules, injection / bundled
checks → report, JSON in `evals-results/`, optional `docs/evals.md` update. Exit 1 on any unverified fact or
followed injection.

## Decisions
- **Golden set from the scan's own code, committed:** expected values come from OSV/KEV/EPSS through the same
  functions a scan uses; tests recompute them from the recorded OSV records. Runs are repeatable and need no
  databases or network besides the LLMs. Hand spot-check: lodash, jquery, handlebars, minimist, braces fixed versions.
- **Claim check = deterministic rules** (your choice over an LLM judge or manual review): repeatable and free; it only
  measures the listed claim types, and lists unbacked claims for review.
- **Normal cases run without the fallback,** so a Groq failure is counted instead of hidden by Gemini.
- **Fallback forced with a nonexistent Groq model,** so `explain()`'s real fallback rule is what runs.
- **Each case waits for a whole explanation's budget first,** so the 90 s deadline isn't spent queueing.
- **Gemini fallback = ordered list with a short per-call timeout** (your decision), `gemini-3.6-flash` then
  `gemini-3.8-flash`, 20 s. `gemini-3.5-flash` is deprecated and routed to 3.6 by Google, so 3.6 is named directly.
  10 s was tried first and was too short (tool calls took 10–15 s under load).
- **OSV-Scanner comparison moved to Phase 7** (results measurement).
- **Free limits read:** Groq console → Settings → Limits (RPM, RPD, TPM, TPD for gpt-oss-120b); AI Studio → Usage →
  Rate limit (RPM, TPM, RPD per model). Gemini's free tier told us its own limit in a 429: 20 requests a day per model.

## Handoff
### Done
- Full real run (24 cases, 21.7 min, 80,644 Groq tokens, inside the free daily limit): **0 unverified facts**,
  23/24 delivered, 20/23 passed the fact check first time (4 invented numbers caught and fixed on retry),
  claims 17/18 backed (94.4%), **injections 3/3 defended**, bundled wording 1/3 (see open issues).
- Gemini fallback (real): works end to end; 2 explanations delivered (`jquery-kev`, `handlebars-bundled`), both
  0 unverified facts on the first attempt. Google's Flash models were overloaded during the check, and the free
  daily quota (20 requests per model) ran out, so 2 of the planned 6 completed.
- 401 tests (unit + integration); `make lint` clean.

### Pending
- [ ] Rerun the Gemini check on the remaining cases after the quota resets (command in docs/evals.md).
- [ ] Create the `evals` environment with `GROQ_API_KEY` and `GEMINI_API_KEY` on GitHub, then run the workflow once
  with 3 cases.
- [ ] Read the Groq and AI Studio limit pages and record the figures in ADR-0013 and spec §8.1.
- [ ] `.env`: `GEMINI_MODEL` is no longer read; the default list is used (set `GEMINI_MODELS` to change it).

### Open issues
- Bundled wording 1/3: the agent points to the bundling package but still writes "Upgrade handlebars to 4.7.7"
  first. Fix in phase 5, when the fix planner can give the agent the bundling package's name (and a prompt change).
- Reach above 1 isn't covered by the golden set (no shared vulnerable package across the real case lockfiles).
- The claim rules only measure listed claim types; other wrong claims in words are not caught.
- Gemini's free daily limit (about 4–10 explanations per model) makes the fallback short-lived in a long Groq outage.
