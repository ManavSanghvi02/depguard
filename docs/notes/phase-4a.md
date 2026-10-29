# Phase 4a — Explanation agent

> Branch: `feat/phase-4a-agent` · Date: 2026-10-28

## Files
- `agent/context.py`: `FindingContext` (everything the agent may see, loaded before it runs) and `cache_key`.
- `agent/tools.py`: 3 read-only tools (dependency path, advisory details, fixed version), no arguments.
- `agent/schema.py`: `ExplanationDraft` (validated output) and the `submit_explanation` tool definition.
- `agent/fact_check.py`: IDs, versions, numbers and dates must come from the context. Pure code.
- `agent/prompt.py`: system prompt, `PROMPT_VERSION` (part of the cache key).
- `agent/graph.py`: LangGraph graph: agent → tools → agent … → check → done / one retry.
- `agent/llm.py`: Groq and Gemini models from settings; Langfuse handler when keys are set.
- `agent/budget.py`: tokens-per-minute budget, `retry_after` for 429s, token estimate.
- `agent/explain.py`: scan step 10 (top 5), provider choice, cache, retry.
- `scoring/ranking.py`: the ranking query, moved out of `routes/scans.py` so the agent uses it too.
- `alembic/versions/0002_phase4a_agent.py`: `explanations`, `findings.is_bundled`, `repos.is_private`.
- `parsers/npm_lock.py`: `inBundle` → `Entry.bundled`. `github/client.py`: `latest_commit` returns `Head` (SHA + private).
- `routes/scans.py`: `is_bundled` and `explanation` on findings; dev `POST /v1/dev/findings/{id}/explanation`.
- Tests: `tests/fake_llm.py` (scripted chat model), `tests/unit/agent/*`, new integration tests in
  `test_scan_pipeline.py` and `test_postgres_roles.py`.

## Main flow
Scan finishes and is committed → `explain_scan` (own session, errors only logged) → top 5 by the ranking →
per finding: load context (Postgres + Neo4j paths) → cache key → same key with status `ok` in this repo? copy the
row (`cache_hit`) : run the graph with Groq → on an exception (error, timeout, 429) try Gemini only if the repo is
public → store one `explanations` row (`ok` or `unavailable` + `error`) → flush Langfuse.
Graph: the LLM must call a tool every turn (`tool_choice="any"`); after 4 reads only `submit_explanation` is
allowed; the check validates the schema, runs the fact checker, and sends the problems back once.

## Decisions
- **Groq `openai/gpt-oss-120b` primary, Gemini `gemini-3.8-flash` fallback for public repos only** (ADR-0013,
  now Accepted). Repo visibility is stored from GitHub on every scan; null counts as private. A failed fact
  check is not an outage, so it never uses the fallback.
- **The answer is a `submit_explanation` tool call**, not Groq's structured-output mode: Groq can't combine
  that with tool calling, and a tool call works the same on Gemini. Pydantic validates the arguments.
- **Tools take no arguments and read a context loaded beforehand.** The LLM chooses *which* facts to read, never
  *whose*, so injected advisory text can't reach other data. The fact checker accepts everything in the context,
  whichever tools were called.
- **Fact checker:** a date, percentage (12.3%, 12%), ordinal (92nd) or plain number must equal a stored value;
  digits inside package names are ignored. It doesn't check words ("critical", "remote"): numbers and IDs are
  where invented facts are measurable.
- **Rate limits (changed after the first real run, where 3 of 5 hit Groq's 8,000 tokens/min):** one finding at
  a time; each call waits for a 7,500 tokens/min budget first; a 429 is retried as the provider asks, at most twice
  per call and only within the deadline (ADR-0013).
- **Tokens:** tool results sent in full once, compact JSON, 600-character details, all tools then submit-only,
  gpt-oss `reasoning_effort=low`. About 3,100–3,500 tokens per explanation with gpt-oss-120b (was about 3,800).
  The rest is the system prompt and tool definitions, which every call must resend.
- **Model:** Groq's headers for this key give gpt-oss-120b, gpt-oss-20b and qwen3.8-27b the same limits
  (1,000 requests/day, 8,000 tokens/min). On the top 5 of nodejs-goof: 120b passed 5/5 (3,115–3,526 tokens);
  20b passed 5/5 but used more on jquery (4,578); qwen passed 1/5, the rest were 429s it gave no wait for.
  gpt-oss-120b stays.
- **Cache per repo**, not across users: a rescan with unchanged facts makes no LLM call; a daily refresh that
  changes EPSS changes the key.
- **Explanations are insert-only for the API role** (no UPDATE/DELETE grant): a shown explanation can't be
  rewritten afterwards; a retry adds a row.
- `ranked_findings` moved to `scoring/ranking.py`; importing it from the route would have made a cycle.

## Handoff
### Done
- Everything in the plan, plus the public-only Gemini fallback and the rate-limit handling. 286 tests;
  `make lint` clean.
- Real runs on nodejs-goof (433 findings, scan 6.3 s):
  - First run (no budget, no retries): 2 of the top 5 passed; 3 were Groq 429s.
  - Second run: **5 of 5 passed the fact check**, all on Groq. **69 s** from scan start to the 5th explanation
    (two waits of about 58 s for the token budget, no 429s).
  - Langfuse: traces arrive once `LANGFUSE_HOST` matches the project's region (here US); checked through its API.
- ADR-0013 Accepted (provider table, fallback rule, budget); security.md §3 T2, §4, §11, §12 updated.

### Pending
- [x] The Gemini fallback has only been tested with a fake model; the real runs never needed it. (Phase 4b: real runs.)
- [ ] Confirm Gemini's free limits in AI Studio, and Groq's free-plan figures on the console limits page. (Phase 4b
  found Gemini's free limit: 20 requests a day per model; the pages still need reading.)
- [x] Phase 4b: agent evaluation set (faithfulness = 0 unverified facts on every run).

### Open issues
- Explanations run after the scan reports `done`, so for up to a few minutes `explanation` is null ("not yet").
  The web UI (phase 6) should show that state.
- A bundled package's explanation says to upgrade the bundling package, but which package that is comes in
  phase 5 (fix planner).
- The fact checker can't catch a wrong claim in words (e.g. "this is remotely exploitable"); the prompt and the
  untrusted-data block are the only defence there. Phase 4b's eval set should include such cases.
