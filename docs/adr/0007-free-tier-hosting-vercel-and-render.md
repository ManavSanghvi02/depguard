# ADR-0007: Free-tier hosting — Vercel (web) + Render (API) + Supabase + AuraDB
- Status: Accepted
- Date: 2026-10-28

## Context
The project must cost **$0/month**. It has a Next.js web app, a Python API that runs minute-long background scans,
a relational database and a graph database. Limits checked on 2026-10-28 are listed in [spec §8.1](../spec.md);
free tiers change often.

## Options

**Option A: web on Vercel, API on Render**
- Vercel serves the Next.js site from a global CDN, so pages load fast even when the API is asleep.
- Render runs a normal long-lived Python process (Docker), which suits background scans.
- Two platforms, two dashboards, and **CORS** configuration (the browser calls an API on another domain).

**Option B: everything on Render**
- One platform, no CORS.
- The free web service **sleeps after 15 minutes idle** and takes about a minute to wake, so the *website itself*
  would show a blank page for a minute to a first visitor (often an interviewer).

**Option C: everything on Vercel**
- One platform; fast pages.
- The backend would run as short-lived serverless functions with time limits, a poor fit for minute-long background
  scans and long-lived database connections.

**Databases:** Supabase Free (Postgres + Auth in one, 500 MB, pauses after 1 week idle) and Neo4j AuraDB Free
(about 200k nodes / 400k relationships under current limits, pauses after about 3 days idle). Paid tiers or self-hosting
would break the $0 constraint or add operations work.

**Scheduled and isolated jobs:** Render's cron jobs are billed, so the daily refresh and fix-PR building run on
**GitHub Actions** ([ADR-0009](0009-daily-refresh-on-github-actions.md), [ADR-0010](0010-fix-prs-built-in-github-actions.md)).

## Decision
**Option A** (Vercel + Render), with Supabase Free, AuraDB Free and GitHub Actions.

## Trade-offs
- **Gain:** $0; a fast website; a real Python process for scans.
- **Give up / accept:**
  - API **cold start** of about 1 minute (measured separately from scan time).
  - Databases that **pause when idle** (the daily job writes to both to prevent it).
  - **Capacity for only a handful of users** (Aura limits).
  - Vercel Hobby is **non-commercial** only.
  - Two platforms plus CORS.
- **Revisit if:** DepGuard needs real users or uptime. The first paid upgrade would be an always-on Render instance.
