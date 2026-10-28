# DepGuard — Product Spec

> Status: Phase 0 draft · Last updated: 2026-10-28
> This document says **what** we build and **why**. The **how** lives in
> [architecture.md](architecture.md) and the decisions behind it live in [adr/](adr/).

---

## 1. Problem

### 1.1 Too many alerts, ranked the wrong way
Tools like `npm audit`, `pip-audit` and Dependabot can list dozens or hundreds of
vulnerability advisories for one repository. They are mostly ordered by **CVSS
severity**, which measures how bad an attack *would* be, not how *likely* it is.
Only a small share of published vulnerabilities are ever exploited in practice. So
teams either ignore the whole list (alert fatigue) or spend time on items that do not
matter, while the few that are actively exploited get lost in the noise.

### 1.2 "Where am I affected?" takes days
A vulnerable package usually is not something you installed on purpose. It sits deep
in the **transitive** dependency tree (a dependency of a dependency), and often in
**several repositories** at once. When a major vulnerability is announced, the first
question is "where am I affected?", and answering it means opening lockfiles repo by
repo.

- **Log4Shell (December 2021)** is the best-known example: organisations spent days
  finding every place a vulnerable `log4j` sat inside their software. Log4Shell was a
  **Java** problem, so DepGuard (npm and PyPI only) would *not* have caught it. It is
  here only to illustrate the pattern.
- **The same pattern in npm:** in October 2021 the widely used package `ua-parser-js`
  was hijacked and malicious versions were published. Most projects pulled it in
  transitively, so teams had to search their lockfiles to learn whether they had
  installed a bad version.

### 1.3 Who suffers most
Small teams **without a dedicated security engineer**. Security is someone's
part-time job, so there is no time to triage long alert lists or trace dependency trees
by hand.

### 1.4 What DepGuard does about it
DepGuard ranks findings by **real-world risk**, answers "where am I affected?" across
all of a user's repos, explains the top risks in plain language, and opens a
**minimal fix pull request** so that acting on a finding is cheap.

Real-world risk combines four signals:

| Signal | Question it answers | Source |
|---|---|---|
| **CISA KEV** | Is this being exploited *right now*? | CISA Known Exploited Vulnerabilities catalog |
| **EPSS** | How *likely* is exploitation in the next 30 days? | FIRST EPSS |
| **CVSS** | How *bad* would an attack be? | The advisory (via OSV) |
| **Reach** | How many of *my* services include it? | DepGuard's dependency graph |

### 1.5 How DepGuard differs from Dependabot
Dependabot is good, free and already on GitHub. DepGuard is meant to sit **beside** it,
not replace it. As of 2026-10-28, per GitHub's docs, Dependabot alerts can be filtered
by auto-triage rules on criteria such as severity, EPSS score, package, ecosystem,
dependency scope and patch availability, and Dependabot can open security-update PRs.

| | Dependabot | DepGuard |
|---|---|---|
| Unit of work | One repository at a time | All of a user's repos together ("where am I affected?" across repos) |
| Prioritisation | Severity order plus rules *you* write (EPSS is one filter) | Fixed, documented tiers combining KEV, EPSS, CVSS and reach, with the breakdown shown |
| Actively exploited (KEV) | Not one of the auto-triage rule criteria we found in the docs | A first-class signal: KEV findings in production are "fix now" |
| Reach | Not a signal | Number of services containing the vulnerable version |
| Explanation | Advisory text | Plain-English explanation of the top 5, every fact checked against stored data |
| Fix PRs | Security-update PRs | Minimal-change PRs with strict diff rules and a major-version warning |
| AI assistants | — | Read-only MCP server |

Sources: [GitHub Docs — auto-triage rules](https://docs.github.com/en/enterprise-cloud@latest/code-security/how-tos/secure-your-supply-chain/manage-your-dependency-security/customizing-auto-triage-rules-to-prioritize-dependabot-alerts),
[GitHub Blog — prioritising Dependabot alerts](https://github.blog/security/application-security/cutting-through-the-noise-how-to-prioritize-dependabot-alerts/).
GitHub changes these features often; re-check before quoting this table.

---

## 2. Users

### 2.1 Primary user
A developer or tech lead on a **small team (about 2–20 engineers)**. The team owns a
handful of GitHub repos with npm and/or Python services and has **no dedicated
security engineer**. They want to answer, in **under 10 minutes a week**: *what must I
fix now, where is it, and what is the smallest change that fixes it?*

### 2.2 Secondary user
A developer who works inside an **AI assistant** (Claude, Cursor, and similar) and asks
"am I affected by CVE-X?" or "what should I patch first?", answered through DepGuard's
**MCP server** without opening the web app.

### 2.3 Not our users
- Large companies with a security team and enterprise security tools such as Snyk.
- Teams on ecosystems other than npm and PyPI.

---

## 3. Definitions used in this spec

- **Service:** one lockfile = one service. An npm workspace monorepo with a single
  root lockfile therefore counts as **one** service.
- **Reach:** the number of services, across **all** of the user's repos, that contain
  the vulnerable version.
- **Production vs. dev dependency:** taken from the lockfile when it records it. If the
  lockfile cannot tell, the package is treated as **production** (the safe choice:
  it can only over-report, never hide, a risk).
- **Known malicious:** a package version with an OSV `MAL-` advisory.
- **Owned repo (for fix PRs):** a **personal** repo (not an organization's) whose GitHub App
  installation belongs to the requesting user. This is checked **live** when a fix is requested, by comparing
  **numeric GitHub user IDs** (usernames can change). Organization repos come later.

All terms are explained in plain English in [glossary.md](glossary.md).

---

## 4. User stories

Format: **As a** *who*, **I want** *what*, **so that** *why*. Each story has a "done when"
check that becomes a test. **MVP = stories 1–7. Story 8 is next after the MVP.**

| # | Story | Done when |
|---|---|---|
| 1 | **As a** tech lead, **I want** to sign in with GitHub and add repos to scan, **so that** I don't upload files by hand. *MVP: public repos and repos added by URL. Private repos come later via the GitHub App.* | A user can sign in and add up to 10 public repos. |
| 2 | **As a** tech lead, **I want** to see every vulnerable npm/PyPI package in my repos, direct and transitive, with the installed and first fixed version, **so that** I know my real exposure. | Results agree with **OSV-Scanner** on the same lockfiles, and every difference is explained in a documented list. |
| 3 | **As a** tech lead, **I want** findings ranked by tier and risk score, with the KEV / EPSS / CVSS / reach breakdown, **so that** I trust the order. | Every finding shows its tier, score and four inputs; tiers are always in order. |
| 4 | **As a** tech lead, **I want** to search a CVE ID or package name and see every affected service with its dependency path (`my-app → B → vulnerable C`), **so that** I answer "where am I affected?" in minutes. | Search returns every affected service and, where the lockfile allows, its path. |
| 5 | **As a** developer without security training, **I want** a plain-English explanation of the top 5 risks, **so that** I can act without looking up jargon. | Each explanation passes the automated fact check (section 7). |
| 6 | **As a** tech lead, **I want** one click to open a PR with the smallest change that fixes the vulnerability, **so that** fixing is cheap. I review and merge it myself. | The PR follows the diff rules in section 7 and is never auto-merged. |
| 7 | **As a** developer in an AI assistant, **I want** to ask "am I affected by CVE-X?" or "what are my top risks?" through MCP, **so that** I don't switch tools. | MCP answers equal the web API's answers for the same scan. |
| 8 | *(Next)* **As a** tech lead, **I want** to see what changed since my last scan and be alerted when a vulnerability affecting my repos is newly added to KEV, **so that** my weekly check stays short. | Each scan shows new and fixed findings; a new KEV entry that matches a user's service triggers an alert. |

---

## 5. MVP scope

### 5.1 Inputs
| Ecosystem | Lockfile | Dependency paths | Dev vs. prod |
|---|---|---|---|
| npm | `package-lock.json` (v2, v3) | Yes | Yes: `"dev": true` = dev. `"devOptional": true` (optional in the production tree) → production |
| PyPI | `poetry.lock` | Yes | The parser checks **which fields are present**, not the lock-version number: `category = "dev"` = dev (older Poetry, can appear even in lock-version 2.0); `groups = [...]` without "main" = dev (Poetry 2.1+); neither field → production |
| PyPI | `uv.lock` | Yes | Yes |
| PyPI | `requirements.txt` with pinned `==` versions (also `requirements-*.txt` files) | No (flat list) | No (→ production, even for files named like `requirements-dev.txt`: file names aren't reliable) |

- **No version guessing.** An unpinned requirement such as `requests>=2.0` is reported
  as **"skipped: version unknown"**, never matched against a guessed version.
- **Limits:** at most **10 repos per user** and **2,000 dependencies per service**.

### 5.2 Features
1. **Sign-in** with GitHub through Supabase Auth, used for **identity only** (no
   repository access).
2. **Add repos:** public github.com repos, by picking from the user's list or by URL.
3. **Scan:** fetch the supported lockfiles, match every package version against OSV
   advisories, enrich with KEV and EPSS, compute reach, tier and score.
4. **Ranked findings list** with the score breakdown.
5. **"Where am I affected?" search** by CVE ID or package name.
6. **AI explanations** for the top 5 findings of each scan.
7. **Fix PRs** through a **GitHub App used for writes only**: permissions *Contents:
   write*, *Pull requests: write*, *Metadata: read*, installed only on repos the user
   picks. A PR is opened **only on a repo the user owns** (see §3); for any other repo,
   DepGuard shows the **patch** to copy instead.
   If the smallest fix is a **major** version bump, the PR says so clearly.
8. **MCP server, read-only:** `list_top_risks`, `am_i_affected`, `explain_finding`.
9. **Daily data refresh:** KEV and EPSS are refreshed daily and scores recomputed, even
   though scans themselves are on demand.

### 5.3 Priority tiers
Ranking uses three tiers. Within a tier, findings are ordered by risk score. The full
reasoning and the score formula are in the scoring ADR.

| Tier | Rule | Order within tier |
|---|---|---|
| **Fix now** | Known malicious in **any** dependency, **or** (KEV **or** EPSS ≥ 0.1) in a **production** dependency | Malicious → KEV → EPSS-only, then by risk score |
| **Fix soon** | (KEV **or** EPSS ≥ 0.1) in a **dev-only** dependency, **or** CVSS ≥ 7 in production | By risk score |
| **Monitor** | Everything else | By risk score |

Ties are broken deterministically (advisory ID, then package name) so the same input
always gives the same order. Malicious packages are "fix now" even in dev dependencies
because they often run code at **install** time, which harms developer machines and CI.

---

## 6. Non-goals

**Out of scope** means not this product; **later** means not in the MVP.

| Non-goal | Label |
|---|---|
| Ecosystems other than npm and PyPI (Maven, Go, Cargo, RubyGems, NuGet, container images, OS packages) | Out of scope |
| **Code-level reachability** (does my code *call* the vulnerable function?). DepGuard's "reach" counts services, not call paths. | Out of scope |
| Detecting **new or unknown** malware or typosquats. *Known* malicious packages with OSV `MAL-` advisories **are** reported like any other advisory. | Out of scope |
| License compliance, secrets scanning, static analysis of the user's own code (SAST) | Out of scope |
| Auto-merge, fixes without human review, write actions through MCP | Out of scope |
| Rewriting user code to handle breaking changes in a major bump (DepGuard warns instead) | Out of scope |
| Creating our own vulnerability data, versions or scores (all come from OSV, KEV and EPSS) | Out of scope |
| Hosts other than github.com (GitLab, Bitbucket, GitHub Enterprise Server) | Out of scope |
| Enterprise features: SSO, organisations/teams, role-based access, billing, SLAs | Out of scope |
| Scheduled scans and alerts (data still refreshes daily in the MVP) | Later (story 8) |
| Scanning private repos | Later (GitHub App with read access) |
| `yarn.lock`, `pnpm-lock.yaml`, `Pipfile.lock`; partial paths for `requirements.txt` from pip-tools `# via` comments | Later |

---

## 7. Success metrics

| Area | Metric | Target | How measured |
|---|---|---|---|
| Correctness | Agreement with OSV-Scanner on ~10 real public repos (npm + Python) | Every difference explained and documented | Automated comparison script |
| Determinism | Same lockfile + same data snapshot → same findings, tiers, scores and order | 100% | Unit tests |
| Ranking | Every "fix now" finding ranks above every other finding; tiers always in order | 100% | Automated test |
| 10 min/week (proxy) | Timed walkthrough: sign in → add repo → scan → read top 5 → open fix PR | Under 10 minutes | Manual timing on a benchmark repo. **This is a proxy**, not a user study. |
| Speed | Scan of a repo with ≤ 2,000 dependencies, **excluding cold start** | Under 2 minutes | Timer in scan logs; cold start reported separately |
| Fix PR quality | Manifest change touches only the target package (or its parent for transitive fixes); lockfile changes stay within that package's subtree; no unrelated package changes version; major bumps labelled | 100% | Tests on generated diffs |
| AI faithfulness | Unverified IDs, versions or numbers in explanations | 0 on every run | Automated check against stored data |
| AI faithfulness | Free-text claims judged correct | Reported as a % | Manual review of an evaluation set |
| Noise reduction | Unique findings (GHSA / PYSEC / CVE aliases merged) vs. findings in "fix now", compared with a severity-only ranking | Reported per benchmark repo | Script over the benchmark repos |
| MCP parity | MCP answers equal web API answers for the same scan | 100% | Automated test |
| Freshness | Age of KEV and EPSS data | Under 48 hours | Timestamp shown in UI and API |
| Cost | Monthly hosting bill | $0 | Provider dashboards |

---

## 8. Constraints

### 8.1 Cost and hosting — free tiers only ($0/month)
Figures checked on 2026-10-28; free tiers change often, so re-check before relying on them.

| Service | Relevant limits | Consequence for DepGuard |
|---|---|---|
| **Render** (API) | Free web services spin down after 15 min idle; spin-up takes about a minute; 750 free instance hours/month. Cron jobs are billed (minimum $1/month). | Cold start is measured separately. The daily job does **not** run on Render. |
| **Neo4j AuraDB Free** | About 200,000 nodes and 400,000 relationships; pauses after about 3 days without activity; no backups. | The node cap is shared by all users → limits of 10 repos per user and 2,000 deps per service. The daily job writes to Neo4j. |
| **Supabase Free** | 500 MB database per project; projects pause after 1 week of inactivity. | Store a new score row only when inputs change. The daily job touches Supabase. |
| **Vercel Hobby** (web) | For non-commercial use. | Fits a portfolio project. |
| **GitHub Actions** | Scheduled workflows are disabled after 60 days without repo activity in public repos; minutes are limited while a repo is private. | The daily job also has a manual "run now" trigger. |

Sources: [Neo4j Aura quotas and limits](https://neo4j.com/docs/aura/quotas-and-limits/),
[Neo4j AuraDB Free](https://neo4j.com/free-graph-database/),
[Render — hosting costs](https://render.com/articles/how-much-does-cloud-application-hosting-cost-for-small-businesses),
[Supabase pricing](https://supabase.com/pricing.md),
[Supabase changelog — database size](https://supabase.com/changelog/33121-relaxing-database-size-limit-on-free-plan-0-5-gb-database-size-per-project).

#### Graph capacity (Neo4j AuraDB Free)
Each service gets its own dependency nodes (see [ADR-0006](adr/0006-per-service-graph-nodes.md)), so capacity
is set by the per-service size:

```
nodes per service          = N + 1            (N lockfile entries + 1 Service node)
relationships per service  = N × d            (d = average dependencies per entry)
services that fit          ≈ min( node_limit / (N + 1),  relationship_limit / (N × d) )
```

`d` is an **assumption (2–4)** until it is measured on the benchmark repos. For a maximum-size service
(N = 2,000), **under current limits**:

| Published limits | By nodes | By relationships (d = 2 … 4) | Services that fit |
|---|---|---|---|
| 200,000 nodes / 400,000 relationships (current docs) | ~99 | ~100 … ~50 | **~50–99** |
| 50,000 nodes / 175,000 relationships (older Neo4j pages) | ~24 | ~43 … ~21 | **~21–24** |

At d ≈ 2, nodes and relationships run out at about the same point; for higher `d`, relationships run out first.

Neo4j has published different free-tier limits over time; the real numbers will be confirmed in the Aura
console and this table updated. Either way, at the maximum of 10 repos per user, DepGuard on the free tier serves
**a handful of users**, which is acceptable for a portfolio project. Typical services are far smaller than 2,000
entries, so real capacity is higher. Before writing a graph, DepGuard checks that current + new stays under 90% of
both limits; otherwise the graph step is skipped, findings are still stored, and the scan is marked `partial`.

### 8.2 The daily job
A scheduled GitHub Actions workflow, with a manual "run now" trigger, that:
1. Downloads the KEV catalog and the EPSS scores as **daily bulk files**.
2. Recomputes and **stores** scores, tagged with the data date (a new row only when an
   input changed), so every score is **recorded** with the data it was based on and story 8 has
   history. (Old scans can't be re-run identically: only the latest KEV/EPSS snapshot is kept, and OSV
   data changes over time.)
3. **Writes to Neo4j** (for example a "last refreshed" node) and **touches Supabase**, so
   neither free database pauses.

### 8.3 External data and APIs
- **GitHub:** fetch **only lockfiles**, using the repository file-tree API with
  DepGuard's own **read-only token** (5,000 requests/hour), instead of cloning. The design
  must handle truncated trees for very large repos and lockfiles over 1 MB.
- **OSV:** batch queries return advisory **IDs only**, so advisory details are cached.
- **KEV and EPSS:** bulk downloads, never one request per vulnerability.
- **LLM:** a free model with tight rate limits. **DepGuard must work fully without
  it:** if the LLM is down, findings, tiers, scores and fix PRs still work; only the
  explanations are missing.
- **Real data only:** public APIs and real public repos. Small hand-made test fixtures are
  the only exception.
- Data sources are credited as their terms require.

### 8.4 Security
- Secrets live only in `.env` (gitignored) and hosting secret stores, never in the
  repo or in chat. `.env.example` holds placeholders.
- The **GitHub App private key** is the most sensitive secret. It and the read-only
  token are covered in [security.md](security.md).
- Least privilege everywhere: narrow App permissions, an identity-only login, read-only MCP.

### 8.5 Engineering
- Matching, version comparison, tiering and scoring are **deterministic code**, never the LLM.
- Tests for every feature. One phase = one branch = one pull request; CI must pass.
- Simple, readable code over clever code.

### 8.6 People and time
- About **10–12 days** total, solo. Claude writes the code; the owner must be able to
  explain every file, which rules out clever but obscure solutions.

---

## 9. Open questions
Answered during Phase 0:
- Risk score within tiers, missing CVSS, CVSS version → [ADR-0003](adr/0003-risk-tiers-and-stored-scores.md)
  (weights still *Proposed*).
- Fixing a vulnerable **transitive** dependency → [ADR-0010](adr/0010-fix-prs-built-in-github-actions.md)
  (parent bump first, then overrides).
- How LangGraph structures the agent → [ADR-0013](adr/0013-explanation-agent-and-llm.md).
- "First fixed version" → the smallest fixed version above the installed one in the advisory's
  affected ranges ([architecture §3](architecture.md)).

Still open:
- Which free LLM provider (ADR-0013, decided in the agent phase).
- The average dependencies per entry (`d`) and the real Aura Free limits (§8.1).
