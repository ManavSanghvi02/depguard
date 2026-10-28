# Glossary

Every technical term used in the DepGuard docs, in plain English. Alphabetical.

| Term | Meaning |
|---|---|
| **202 Accepted** | HTTP status meaning "I've accepted your request and will finish it later". DepGuard returns it when a scan or fix starts. |
| **ADR (Architecture Decision Record)** | A short document recording one design decision: context, options, decision, trade-offs. See [adr/](adr/README.md). |
| **Advisory** | A published notice that a package version has a vulnerability, saying which versions are affected and which are fixed. |
| **Alembic** | A Python tool for **migrations**: versioned, step-by-step changes to a database's structure. |
| **Alert fatigue** | When people get so many alerts that they start ignoring all of them, including the important ones. |
| **Alias (advisory alias)** | Another ID for the same vulnerability. One problem can be `CVE-…`, `GHSA-…` and `PYSEC-…` at once; DepGuard merges them. |
| **API (Application Programming Interface)** | A defined way for one program to ask another for data or actions. |
| **API token (DepGuard)** | A long random string a user creates in DepGuard so an AI assistant can call `/mcp` on their behalf. Stored only as a hash. |
| **Artifact (GitHub Actions)** | A file one workflow job saves so a later job can download it. |
| **Async** | A way of writing code so the program can do other work while waiting for slow things like network calls. |
| **AuraDB** | Neo4j's hosted (cloud) database service; DepGuard uses its free tier. |
| **Background job** | Work that runs after the API has already replied, so the user doesn't wait on an open request. |
| **Benchmark repos** | About 10 real public repos used to measure DepGuard's correctness and ranking. |
| **Blob API** | GitHub API that returns one file's contents by its ID; works for files over 1 MB. |
| **Branch (Git)** | A movable label for a line of commits. Work happens on a branch and is merged into `main` through a pull request. |
| **BYPASSRLS** | A Postgres role attribute that ignores all row-level security policies. DepGuard's roles deliberately don't have it. |
| **Cache poisoning** | Planting bad data in a shared cache so a trusted process later loads it. Why DepGuard's fix workflow uses no cache. |
| **CDN (Content Delivery Network)** | Servers around the world that keep copies of a website's files so pages load fast everywhere. Vercel uses one. |
| **Cold start** | The delay when a sleeping server has to start up before answering (about 1 minute on Render's free tier). |
| **Confused deputy** | A trusted program tricked into using its power for someone who shouldn't have it. Example: DepGuard's App can write to your repo, so a stranger asks DepGuard to open a PR there. Prevented by checking *who is asking*, not only what the program may do. |
| **CORS (Cross-Origin Resource Sharing)** | Browser rules that decide which websites may call an API on a different domain. Doesn't stop scripts outside a browser. |
| **Cron / cron expression** | A schedule format, e.g. `0 3 * * *` = every day at 03:00. |
| **CVE (Common Vulnerabilities and Exposures)** | The standard ID for a publicly known vulnerability, e.g. `CVE-2021-44228`. The "licence plate". |
| **CVSS (Common Vulnerability Scoring System)** | A 0–10 severity score: how bad an attack *would* be. Says nothing about likelihood. |
| **Cypher** | Neo4j's query language. Patterns look like drawings: `(a)-[:DEPENDS_ON]->(b)`. |
| **Data date** | The date of the KEV/EPSS snapshot used to compute a score, recorded so you know what each score was based on. |
| **Defense in depth** | Several independent protections, so one failing doesn't cause harm. |
| **Dependabot** | GitHub's built-in tool that alerts on vulnerable dependencies and opens update PRs. |
| **Dependency (direct / transitive)** | A package your project uses. *Direct*: you listed it. *Transitive*: a dependency of a dependency. |
| **Deterministic** | Same input always gives the same output. Required for matching, version comparison and scoring. |
| **Dev dependency** | A package used only for development or testing, not shipped to production. |
| **devOptional (npm)** | A lockfile flag for a package that's optional in the production tree. DepGuard counts it as production. |
| **Diff checker** | DepGuard code that inspects a proposed fix and refuses it unless only the intended package changed. |
| **Docker / Docker image** | A way to package an app with everything it needs so it runs the same everywhere. An *image* is that package. |
| **Ecosystem (package)** | A language's package world with its own registry and rules, e.g. npm (JavaScript) or PyPI (Python). |
| **Environment (GitHub Actions)** | A named set of secrets and protection rules that only selected workflow jobs can use (e.g. `fix-pr`). |
| **Environment variable** | A setting given to a program from outside its code, e.g. `DATABASE_URL`. |
| **EPSS (Exploit Prediction Scoring System)** | A 0–1 probability that a vulnerability will be exploited in the next 30 days, updated daily by FIRST. The "weather forecast". |
| **Exponential backoff** | Retrying after waits that grow each time (e.g. 1 s, 2 s, 4 s), so a struggling service isn't hammered. |
| **Fact checker** | DepGuard code that rejects an AI explanation containing any ID, version or number not found in stored data. |
| **FastAPI** | A Python framework for building web APIs, with automatic input checking and interactive docs. |
| **Fine-grained token** | A GitHub token limited to specific repositories and permissions. |
| **FIRST** | The organization that maintains CVSS and EPSS. |
| **Fix PR** | A pull request DepGuard opens with the smallest version change that fixes a vulnerability. |
| **GHSA** | GitHub Security Advisory ID, e.g. `GHSA-xxxx-xxxx-xxxx`. |
| **GitHub Actions** | GitHub's built-in automation: runs workflows on events, schedules or manual triggers. |
| **GitHub App** | An integration with its own identity and fine-grained, per-repo permissions, installed by users on repos they choose. |
| **GitHub user ID (numeric)** | The permanent number GitHub gives each account. Unlike a username, it never changes or gets reused, so DepGuard compares these for ownership. |
| **Graceful degradation** | When one part fails, the system keeps working with less instead of failing completely. |
| **GRANT** | A Postgres command giving a role permission on a table or specific columns (e.g. `SELECT`, `INSERT`). Works together with RLS policies. |
| **Graph database** | A database storing **nodes** (things) and **relationships** (connections) directly; good at following paths. |
| **Hash (SHA-256)** | A one-way fingerprint of data. Storing a token's hash lets you check a token without storing the token itself. |
| **HTTP status codes** | Numbers saying what happened: `200` OK, `201` created, `202` accepted, `204` no content, `401` not signed in, `404` not found, `422` invalid input, `429` too many requests. |
| **Index (database)** | A lookup structure that makes searching by certain fields fast, like a book's index. |
| **Installation token** | A short-lived token (about 1 hour) a GitHub App gets for the repos it's installed on. |
| **Job queue (e.g. Redis)** | A waiting line for background work, served by separate worker processes. DepGuard doesn't use one in the MVP (ADR-0008). Redis is a fast in-memory store often used for this. |
| **JWKS (JSON Web Key Set)** | A published list of public keys used to check that a JWT was really signed by the login provider. |
| **JWT (JSON Web Token)** | A signed login token. The API checks the signature to trust who the user is. |
| **KEV (Known Exploited Vulnerabilities)** | CISA's list of vulnerabilities confirmed as exploited by real attackers. The strongest risk signal. |
| **Langfuse** | A tool that records ("traces") each step an AI agent takes, for debugging and evaluation. |
| **LangGraph** | A Python framework that models an AI agent as a graph of steps with shared state. |
| **Least privilege** | Give every person, token or program only the access its job needs. |
| **LLM (Large Language Model)** | An AI model that generates text. In DepGuard it only writes explanations. |
| **Lockfile** | A file recording the exact version of every installed package (e.g. `package-lock.json`, `poetry.lock`, `uv.lock`). |
| **Log4Shell** | A severe 2021 vulnerability in the Java library log4j; the classic "where am I affected?" example. Out of scope (Java). |
| **MAL- advisory** | An OSV entry for a **known malicious** package version. |
| **Manifest** | The file listing what a project wants (often as version ranges), e.g. `package.json`, `pyproject.toml`. |
| **MCP (Model Context Protocol)** | An open standard that lets AI assistants call external tools; the "USB port" for AI apps. |
| **MERGE (Cypher)** | "Find this node or relationship, or create it if missing." The daily job uses it to update one status node. |
| **Mermaid** | A text format for diagrams that GitHub draws automatically in Markdown files. |
| **Migration (database)** | A versioned script that changes the database structure (tables, columns, roles, policies). |
| **Monorepo** | One repository holding several apps (here `apps/api` and `apps/web`). |
| **MVP (Minimum Viable Product)** | The smallest version that delivers real value (stories 1–7). |
| **Neo4j** | The graph database DepGuard uses for dependency trees. |
| **Next.js** | A React framework for websites, made by Vercel. |
| **Node / relationship (graph)** | A *node* is a thing (a service, a package entry); a *relationship* connects two nodes (`DEPENDS_ON`). |
| **npm** | The package manager and registry for JavaScript. |
| **npm workspace** | Several JavaScript packages in one repo sharing a single root lockfile. Counts as one service in DepGuard. |
| **OAuth / scope** | A standard for letting an app act for a user; a *scope* says how much it may do (e.g. `repo` = all repositories). |
| **OSV (Open Source Vulnerabilities)** | A free database and API of advisories for open-source packages. DepGuard's matching source. |
| **OSV-Scanner** | Google's open-source scanner using OSV data; DepGuard's correctness baseline. |
| **Overrides (npm) / override-dependencies (uv)** | Settings that force a transitive dependency to a specific version. |
| **Partial scan** | A scan that finished but couldn't check everything (e.g. OSV was down); the gaps are listed, never hidden. |
| **PEP 440** | The official rules for Python version numbers and comparison. |
| **PEP 503** | The rule for normalizing Python package names (e.g. `Flask_Login` → `flask-login`). |
| **Pinned version** | An exact version (`==2.31.0`) instead of a range (`>=2.0`). |
| **pip-tools** | A Python tool that generates pinned `requirements.txt` files, adding `# via` comments showing why each package is there. |
| **Poetry / uv** | Python package managers that produce `poetry.lock` / `uv.lock`. |
| **Policy (RLS policy)** | A rule attached to a table saying which rows a given role may see or change. |
| **Polling** | Asking repeatedly "is it done yet?" (the web app checks scan status every ~3 s). |
| **Postgres (PostgreSQL)** | A relational database; DepGuard's source of truth, hosted by Supabase. |
| **Prompt injection** | Text that tries to make an AI ignore its instructions, e.g. hidden inside an advisory description. |
| **Proxy metric** | Something measurable that stands in for what you really care about (a timed walkthrough for "under 10 min/week"). |
| **Pull request (PR)** | A request to merge a branch's changes, where they're reviewed and tested first. |
| **Pydantic** | A Python library that checks data against declared types; FastAPI uses it to validate input. |
| **PyPI** | The Python Package Index, the registry for Python packages. |
| **PYSEC** | Advisory IDs from the Python Packaging Advisory Database. |
| **Rate limit** | A cap on how many requests are allowed in a time window. |
| **Reach** | DepGuard's count of how many of a user's services contain a vulnerable version. *Not* code-level reachability. |
| **Reachability (code-level)** | Checking whether your code actually calls the vulnerable function. A non-goal for DepGuard. |
| **Recursive query (CTE)** | A SQL query that repeats itself level by level; Postgres's way of walking a tree. |
| **Relational database** | A database of tables with rows and columns linked by IDs; queried with SQL. |
| **Render** | The hosting platform for DepGuard's API. |
| **REST** | A style for designing APIs: resources as URLs, actions as HTTP verbs (`GET`, `POST`, `DELETE`), stateless requests. |
| **Risk score** | DepGuard's 0–1 number that orders findings *within* a tier, built from EPSS, CVSS and reach (ADR-0003). |
| **Role (database)** | A database login with its own permissions. DepGuard uses `depguard_api`, `depguard_refresh`, `depguard_fixer`. |
| **Rotate (a secret)** | Replace a secret with a new one and revoke the old one. The correct response to a leak. |
| **RLS (row-level security)** | Postgres rules (policies) deciding which rows a role may see or change. |
| **Runner** | The machine GitHub Actions uses to run a job; a fresh one per job, destroyed afterwards. |
| **SAST (Static Application Security Testing)** | Scanning your own source code for security bugs. A non-goal. |
| **Scheduled job** | Work that runs on a timer, e.g. the daily refresh. |
| **Script injection (workflows)** | Untrusted input ending up inside a workflow's shell commands and being executed. |
| **sdist (source distribution)** | A Python package shipped as source that must be built during install, which can run arbitrary code. |
| **Secret** | Sensitive configuration (keys, passwords, tokens) that must never be in the repo. |
| **Semver (semantic versioning)** | Versions as `MAJOR.MINOR.PATCH`; a major bump may break things. npm's version rules. |
| **Serverless function** | Code that starts per request and stops afterwards, with time limits (Vercel's backend model). |
| **Service (DepGuard)** | One lockfile. A repo with three lockfiles has three services. |
| **SHA pinning** | Referencing a GitHub Action by its exact commit hash instead of a movable tag, so it can't be swapped under you. |
| **Snyk** | A commercial security platform for scanning dependencies and code, popular with larger companies. |
| **Source of truth** | The one place whose data is authoritative; other copies (like the Neo4j graph) can be rebuilt from it. |
| **SQLAlchemy** | A Python library for working with SQL databases using Python classes instead of raw SQL strings. |
| **SSO / SLA** | *Single sign-on*: one company login for many tools. *Service-level agreement*: a promised uptime or response time. Both are enterprise features DepGuard doesn't offer. |
| **Subgroup** | The order *inside* the "fix now" tier: malicious first, then KEV, then EPSS-only. |
| **Supabase** | A hosted platform providing Postgres and Auth; DepGuard uses both. |
| **Supabase Data API** | An automatic web API Supabase puts in front of your tables. DepGuard doesn't use it, and RLS keeps it from returning any data. |
| **Threat model** | A list of what you protect, what could harm it and what prevents each threat. See [security.md](security.md). |
| **Tie-breaker** | A rule that orders items with equal scores the same way every time (advisory ID, then package name). |
| **Tier** | DepGuard's priority group: Fix now, Fix soon, Monitor. |
| **Transaction** | A group of database changes that succeed or fail together, so the data is never left half-updated. |
| **Tree API (GitHub)** | GitHub API that lists every file path in a repo at a commit in one call. |
| **TRUNCATE** | A Postgres command that empties a whole table at once. It skips RLS row policies, so DepGuard grants it only on the KEV and EPSS tables. |
| **Typosquatting** | Publishing a malicious package with a name similar to a popular one (e.g. `reqeusts`). |
| **Untrusted code** | Code we didn't write and can't vouch for, e.g. a package's build script. Never run near secrets. |
| **Vercel** | The hosting platform for DepGuard's web app. |
| **Webhook** | A message a service sends to your URL when something happens (e.g. "App installed"). DepGuard uses none in the MVP; any future GitHub webhook must be verified with its `X-Hub-Signature-256` header. |
| **Withdrawn advisory** | An advisory its publisher took back (e.g. it was a mistake). DepGuard ignores these. |
| **workflow_dispatch** | A GitHub Actions trigger that starts a workflow manually or through the API. |
| **XSS (cross-site scripting)** | An attack where injected text runs as code in a web page. Prevented by rendering text as text. |
