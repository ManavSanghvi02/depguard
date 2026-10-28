# ADR-0005: Postgres for records, Neo4j for the dependency graph
- Status: Accepted
- Date: 2026-10-28

## Context
DepGuard stores two different kinds of data:
1. **Records:** users, repos, scans, findings, scores, fixes. These are rows with clear columns, history and
   relationships between IDs.
2. **A dependency graph:** which package depends on which, any number of levels deep. The core question,
   "where am I affected, and through which packages?", means following paths of unknown length.

## Options

**Option A: Postgres only.** Store edges in a table and use recursive queries (`WITH RECURSIVE`).
- One database, one free tier, one backup story.
- At DepGuard's scale (≤ 2,000 entries per service) a recursive query would probably be fast enough.
- Path queries are long and hard to read, and get more complex as features grow (shortest paths, several paths).

**Option B: Postgres + Neo4j.** Postgres is the source of truth for records; Neo4j holds only the graph.
- Each database does what it's good at. "Every path from this service to package X" is one Cypher pattern.
- Neo4j can be **rebuilt from lockfiles at any time**, so losing it (e.g. Aura Free deleting an idle database) loses
  no findings.
- Two databases to run and secure; two writes per scan.

**Option C: Neo4j only.**
- One database, but users, scans, history and scores fit tables better, and everything would compete for Aura
  Free's small node and relationship limits.

## Decision
**Option B.** Postgres (Supabase) holds all records and is the source of truth. Neo4j (AuraDB) holds only each
service's dependency graph ([ADR-0006](0006-per-service-graph-nodes.md)).

## Trade-offs
- **Gain:** readable path queries for the product's central question; findings safe even if the graph is lost.
- **Give up:** a second database (connection, credentials, keep-alive, free-tier limits) and keeping the two in step.
- **Honest note for interviews:** Postgres alone could do this at our scale. We chose Neo4j for fit and readability
  of the core query, not because Postgres couldn't do it.
- **Revisit if:** Aura Free's limits become the bottleneck. Moving paths to a Postgres recursive query is then the fallback.
