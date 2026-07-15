# Design: Topology-Aware Incident Merge (Blast-Radius Deduplication)

**Date:** 2026-07-15
**Status:** Approved — ready for implementation
**Related:** Multi-anomaly concurrency fixes A (all candidates per tick) + D (deterministic
same-ms ordering), already shipped in `pipeline.py` / `rca/engine.py`. This is "Fix C".

---

## 1. Problem

When a single shared upstream component fails, every downstream node that depends on it
crosses the anomaly threshold in the same correlation window. After Fix A, the pipeline
now raises a *separate* incident for each such node — an incident storm for one real
cause. Example: Postgres goes down → `orders` service and `api-gateway` both light up →
two (or more) incidents, none of which names the actual root.

The challenge statement explicitly requires using *"topology or dependency data to
understand impact paths across network or system components."* This feature satisfies that:
collapse the fan-out into **one** incident centered on the shared upstream, with the
affected dependents recorded as its blast radius.

## 2. Goal & Non-Goals

**Goal:** Before raising incidents, cluster concurrent candidate nodes by their shared
direct upstream dependency and raise one merged incident per cluster (focal = the shared
upstream, downstream candidates = blast radius).

**Non-goals (YAGNI for this pass):**
- No transitive/multi-hop ancestor search (deep cascades A→B→C). Explicitly deferred; see
  §8 Future Work. We look **one hop** up from candidates only.
- No hub-guard heuristics / tunable thresholds — the 1-hop rule makes them unnecessary.
- No change to detection, scoring weights, the agent pipeline, or the UI contract beyond
  populating the existing `Incident.blast_radius` field.

## 3. Decision Record

- **Focal election:** Elect the common upstream dependency as focal **even if it shows no
  anomaly signals of its own.** Its hypothesis is honestly labeled `CORRELATED` (inferred
  from fan-out), never `CONFIRMED`, unless the focal also has direct signals.
- **Reach:** Approach 1 — **direct-parent, lowest common ancestor (1 hop)**. Chosen over
  transitive blast-radius because it is structurally immune to *hub collapse* (a core
  router several hops up can never be elected unless a candidate depends on it directly)
  and needs no magic thresholds. Safe for a live demo.

## 4. Architecture & Data Flow

A new **pure method** `RCAEngine.cluster_candidates(candidates)` sits between candidate
finding and the raise loop. It lives in the engine because it is RCA domain logic and uses
`self.topology`, mirroring `find_incident_candidates`. `pipeline` stays orchestration-only.

```
_maybe_incident:
    candidates = rca.find_incident_candidates(window, min_signals=6)   # unchanged
    clusters   = rca.cluster_candidates(candidates)                    # NEW
    for cluster in clusters[:cap]:            # Fix A per-tick cap, now per-cluster
        raise ONE incident on cluster.focal
        incident.blast_radius = cluster.downstream (+ topology.blast_radius)
```

**Safe degradation:** if Neo4j is unavailable (`topology.driver is None`),
`upstream_dependencies` returns `[]`, no clustering occurs, and behavior is identical to
today's per-node raise. No new hard dependency is introduced.

## 5. Clustering Algorithm (1-hop LCA)

Input: `candidates: list[(node, signals)]`, sorted strongest-first (as returned today).

```
for each candidate node c:
    parents(c) = set(topology.upstream_dependencies(c))          # direct, 1 hop
invert:  by_parent[p] = { c : p in parents(c) }
elected focal := any p with |by_parent[p]| >= 2
```

Rules:
1. **Lowest common ancestor** is automatic: because we only look 1 hop up from
   *candidates*, a deeper hub node never appears as a shared parent unless a candidate
   depends on it directly. When two shared parents both qualify, drop the one that is
   itself an upstream dependency of the other (keep the lower / more specific parent).
2. **Greedy assignment:** process elected focals by descending group size; each downstream
   candidate joins its largest cluster exactly once.
3. **No shared parent →** candidate stays **standalone** (focal = itself; today's behavior).
4. **Focal that is also a candidate** (has its own signals) → `focal_has_signals = True`,
   eligible for a `CONFIRMED` hypothesis via the normal path. Otherwise `CORRELATED` only.

Output:
```python
@dataclass
class CandidateCluster:
    focal: str
    downstream: list[str]          # affected dependents (blast radius); [] when standalone
    focal_has_signals: bool
```
Clusters are returned ordered by strength (max downstream signal severity, then group size)
so the per-tick cap keeps raising the most important incidents first.

## 6. Elected-Focal Hypothesis (honest labeling)

When a focal is elected but has no anomalies, the existing `build_incident` would produce
no hypothesis for it. Add `RCAEngine._shared_dependency_hypothesis(focal, downstream_nodes,
window_events, history)`:

- **kind:** `shared_dependency`
- **Confirmed evidence:** none (this is the point).
- **Correlated evidence:** *"N downstream dependents ({orders, api-gateway}) crossed the
  anomaly threshold within the same window; {focal} is their common upstream dependency"* —
  attaching the real `topology.dependency_path(dependent, focal)` for each dependent.
- **Missing evidence:** *"No direct signal (log/alert/metric) observed on {focal} itself —
  would confirm vs. rule out the shared-dependency hypothesis."*
- **Scoring (reuses existing weights, honestly):**
  `W_DIRECT_UPSTREAM_DEP` (a real dependency path exists) + `W_INDEPENDENT_SIGNAL` per
  corroborating dependent, capped so the total stays within the CORRELATED tier. **Never**
  awards `confirmed_match` / `config_change_within_5s`.
- If `focal_has_signals`, the standard hypotheses (attack/config/behavioral) are *also*
  built for the focal and ranked alongside — the shared-dependency hypothesis simply adds
  the fan-out evidence.

## 7. Cooldown, Cap, and Incident Shape

- A merged cluster counts as **one** incident against `max_incidents_per_tick`.
- On raise, set `_recent_incident_at` for the **focal and every downstream node**, so the
  dependents do not separately re-fire as standalone incidents on the next tick.
- `related` events passed to the agents = focal's own events ∪ all downstream candidates'
  events ∪ config changes in the window.
- `incident.blast_radius` = merge of the actual downstream candidate nodes with
  `topology.blast_radius(focal)` levels (already structured as `{impacted, count, depth,
  levels}`).

## 8. Testing

New `backend/tests/test_topology_merge.py`, fully stubbed (no Neo4j/Qdrant/Gemini). Uses a
fake topology exposing `upstream_dependencies` / `dependency_path` / `blast_radius`.

1. `cluster_candidates`: two dependents sharing parent P → one cluster (focal P, downstream
   both, `focal_has_signals=False`).
2. `cluster_candidates`: candidates with no shared parent → each standalone.
3. `cluster_candidates`: two shared parents where P1 depends on P2 → the lower parent P1 is
   elected (LCA tie-break).
4. `cluster_candidates`: focal also a candidate → `focal_has_signals=True`.
5. `_shared_dependency_hypothesis`: kind `shared_dependency`, confidence in CORRELATED tier
   (no confirmed points), correlated + missing evidence present, dependency paths attached.
6. `_maybe_incident` end-to-end (stubbed `_run_agents`/store): three dependents of one
   parent → **1** merged incident (not 3); `blast_radius` names the dependents; each
   downstream node is cooldown-suppressed afterward.
7. Degradation: topology returning `[]` for all parents → no merge, N standalone incidents
   (identical to pre-C behavior).

## 9. Future Work (out of scope)

- **Transitive reach (Approach 2):** multi-hop `blast_radius`-based ancestor election with a
  hub guard, for deep cascades. Documented but deferred.
- Merging *across* ticks (an incident that grows as more dependents fail later).

## 10. Files Touched

- `backend/app/rca/engine.py` — add `CandidateCluster`, `cluster_candidates`,
  `_shared_dependency_hypothesis`; wire the shared hypothesis into `build_incident` when a
  downstream group is supplied.
- `backend/app/pipeline.py` — call `cluster_candidates` in `_maybe_incident`; raise per
  cluster; set cooldown for focal + downstream; populate blast radius.
- `backend/tests/test_topology_merge.py` — new.
- `README.md` — document the merge under §5 (RCA core) and the multi-anomaly handling.
