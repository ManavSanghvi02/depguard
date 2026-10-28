# ADR-0006: Separate graph nodes per service
- Status: Accepted
- Date: 2026-10-28

## Context
Neo4j stores each service's dependency tree so DepGuard can show paths like `my-app → mkdirp → minimist`. Two
lockfiles can resolve the **same parent** to **different child versions**, e.g. service S1 has `A@1 → B@2` and S2 has
`A@1 → B@3`. The graph must never show a path that doesn't exist in that service's lockfile. AuraDB Free also limits
nodes and relationships (about 200k / 400k under current limits).

## Options

**Option A: shared `PackageVersion` nodes** (one `lodash@4.17.21` node for everyone), with edges tagged by `service_id`
- Fewer nodes.
- Paths are correct **only if every query filters every edge** by `service_id`. One forgotten filter mixes S1's and
  S2's edges and shows a path that exists in neither.

**Option B: separate `Dep` nodes per service** (one node per lockfile entry)
- **Correct by construction:** a service's nodes only connect to its own nodes, so a cross-service path can't exist.
- Simpler queries (no per-hop filter).
- More nodes.

**The math that settles it** (N = entries per service, d = average dependencies per entry, assumed 2–4 until measured):
- Relationships per service = **N × d in both options**. Sharing nodes doesn't reduce edges.
- At N = 2,000 under current limits: by nodes ~99 services fit; by relationships ~100 (d = 2) to ~50 (d = 4).
  At d ≈ 2 both limits are about equal; above that, **relationships run out first**. Either way option A's node savings
  buy little capacity. (Full table in [spec §8.1](../spec.md).)

## Decision
**Option B.**
- npm entries are keyed by their **lockfile install path** (`node_modules/a/node_modules/b`), so even two copies of
  the same package *inside one lockfile* stay distinct.
- Python entries are keyed by normalised name (one version per environment).
- Indexes: unique `(service_id, key)`; composite `(ecosystem, name, version)` for "which services contain X?".
- Only the latest scan's graph is kept per service; writes stop at 90% of either limit (the scan is then `partial`).

## Trade-offs
- **Gain:** correctness by design; simpler queries; the same capacity as option A in practice.
- **Give up:** some duplication of nodes across services; a "which services contain X?" query needs an index
  (provided) instead of a single shared node.
- **Revisit if:** measured `d` is far lower than assumed, making nodes the binding limit.
