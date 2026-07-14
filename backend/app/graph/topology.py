"""Live dependency graph, built from REAL observed communication and backed by Neo4j.

Edge semantics: an edge ``src -> dst`` means "src was observed communicating to
dst" (client -> server) — i.e. **src depends on dst** for that service. From this
we derive:

* ``upstream_dependencies(n)``  = servers n calls (successors) — what n relies on.
* ``downstream_dependents(n)``  = clients calling n (predecessors) — who relies on n.
* ``blast_radius(n)``           = everything transitively depending on n (if n fails).
* ``dependency_path(a, b)``     = a dependency chain from a to b, if one exists.
"""
from __future__ import annotations

import time
from collections import Counter
from neo4j import GraphDatabase, Driver
import pandas as pd

from ..core.config import settings
from ..ingestion.schema import infer_service_role, to_int


class TopologyGraph:
    def __init__(self) -> None:
        self.driver: Driver | None = None

    def initialize(self) -> None:
        """Initialize connection to Neo4j container."""
        for attempt in range(15):
            try:
                self.driver = GraphDatabase.driver(
                    settings.neo4j_uri,
                    auth=(settings.neo4j_user, settings.neo4j_password)
                )
                self.driver.verify_connectivity()
                break
            except Exception as e:
                print(f"[Neo4j] Connection attempt {attempt + 1}/15 failed: {e}")
                time.sleep(2)
        else:
            raise RuntimeError("[Neo4j] Failed to connect to Neo4j database container.")

        # Ensure index/constraint
        with self.driver.session() as session:
            session.run("CREATE CONSTRAINT UNIQUE_NODE_ID IF NOT EXISTS FOR (n:Node) REQUIRE n.id IS UNIQUE")

    def close(self) -> None:
        if self.driver:
            self.driver.close()

    # ---- construction ----
    def build_from_unsw(self, df: pd.DataFrame) -> "TopologyGraph":
        """Add nodes/edges from real UNSW flows to Neo4j. Node role = majority server role."""
        if self.driver is None:
            self.initialize()

        # Clear existing graph
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

        server_roles: dict[str, Counter] = {}
        edges_to_create = []

        for _, r in df.iterrows():
            src, dst = str(r["srcip"]), str(r["dstip"])
            dport = r.get("dsport_i", to_int(r.get("dsport")))
            role = infer_service_role(dport, r.get("service"))
            server_roles.setdefault(dst, Counter())[role] += 1
            sbytes = float(r.get("sbytes") or 0) + float(r.get("dbytes") or 0)
            is_attack = int(r.get("Label", 0)) == 1

            edges_to_create.append({
                "src": src,
                "dst": dst,
                "bytes": sbytes,
                "is_attack": is_attack,
                "port": dport,
                "service": r.get("service")
            })

        # Calculate final roles for target nodes
        roles_dict = {node: counter.most_common(1)[0][0] for node, counter in server_roles.items()}

        # Batch insert using cypher query
        batch_size = 2000
        with self.driver.session() as session:
            for start_idx in range(0, len(edges_to_create), batch_size):
                batch = edges_to_create[start_idx : start_idx + batch_size]
                
                # Pre-populate roles for batch
                for edge in batch:
                    edge["src_role"] = roles_dict.get(edge["src"], "host")
                    edge["dst_role"] = roles_dict.get(edge["dst"], "host")

                session.run("""
                UNWIND $batch AS edge
                MERGE (s:Node {id: edge.src})
                ON CREATE SET s.role = edge.src_role, s.flows = 0
                MERGE (d:Node {id: edge.dst})
                ON CREATE SET d.role = edge.dst_role, d.flows = 0

                WITH s, d, edge
                MERGE (s)-[r:DEPENDS_ON]->(d)
                ON CREATE SET 
                    r.flows = 1, 
                    r.bytes = edge.bytes, 
                    r.attack_flows = CASE WHEN edge.is_attack THEN 1 ELSE 0 END,
                    r.port = edge.port,
                    r.service = edge.service
                ON MATCH SET 
                    r.flows = r.flows + 1, 
                    r.bytes = r.bytes + edge.bytes,
                    r.attack_flows = r.attack_flows + CASE WHEN edge.is_attack THEN 1 ELSE 0 END
                
                SET s.flows = s.flows + 1
                SET d.flows = d.flows + 1
                """, {"batch": batch})

        return self

    # ---- traversal (spec: upstream/downstream/blast radius/path) ----
    def upstream_dependencies(self, node: str) -> list[str]:
        if self.driver is None:
            return []
        with self.driver.session() as session:
            result = session.run(
                "MATCH (n:Node {id: $id})-[:DEPENDS_ON]->(dep:Node) RETURN dep.id AS id",
                {"id": node}
            )
            return [row["id"] for row in result]

    def downstream_dependents(self, node: str) -> list[str]:
        if self.driver is None:
            return []
        with self.driver.session() as session:
            result = session.run(
                "MATCH (client:Node)-[:DEPENDS_ON]->(n:Node {id: $id}) RETURN client.id AS id",
                {"id": node}
            )
            return [row["id"] for row in result]

    def blast_radius(self, node: str, max_depth: int = 4) -> dict:
        """All nodes that transitively depend on `node` (transitive predecessors)."""
        if self.driver is None:
            return {"impacted": [], "count": 0, "depth": 0}
        with self.driver.session() as session:
            # Query all paths of length up to max_depth ending in `node`
            result = session.run(
                """
                MATCH path = (client:Node)-[:DEPENDS_ON*1..4]->(n:Node {id: $id})
                WHERE client.id <> $id
                RETURN client.id AS id, length(path) AS depth
                """,
                {"id": node}
            )
            
            impacted_map = {}
            max_d = 0
            for row in result:
                cid = row["id"]
                cd = row["depth"]
                impacted_map[cid] = min(impacted_map.get(cid, cd), cd)
                max_d = max(max_d, cd)

            # Sort levels based on distance
            levels = [[] for _ in range(max_d)]
            for cid, depth in impacted_map.items():
                levels[depth - 1].append(cid)
            
            levels = [sorted(lvl) for lvl in levels if lvl]

            return {
                "impacted": sorted(impacted_map.keys()),
                "count": len(impacted_map),
                "depth": max_d,
                "levels": levels
            }

    def dependency_path(self, source: str, target: str) -> list[str]:
        if source == target:
            return [source]
        if self.driver is None:
            return []
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH p = shortestPath((source:Node {id: $src})-[:DEPENDS_ON*]->(target:Node {id: $dst}))
                RETURN [n IN nodes(p) | n.id] AS path
                """,
                {"src": source, "dst": target}
            )
            row = result.single()
            return row["path"] if row else []

    def has_dependency(self, a: str, b: str) -> bool:
        return bool(self.dependency_path(a, b) or self.dependency_path(b, a))

    # ---- serialization for the UI (React Flow) ----
    def node_view(self, node: str) -> dict:
        if self.driver is None:
            return {"id": node, "role": "host", "flows": 0, "upstream": [], "downstream": []}
        with self.driver.session() as session:
            result = session.run(
                "MATCH (n:Node {id: $id}) RETURN n.role AS role, n.flows AS flows",
                {"id": node}
            )
            row = result.single()
            role = row["role"] if row else "host"
            flows = row["flows"] if row else 0

        return {
            "id": node, "role": role, "flows": flows,
            "upstream": self.upstream_dependencies(node),
            "downstream": self.downstream_dependents(node)
        }

    def to_cytoscape(self, top_n: int = 60) -> dict:
        """Return the busiest sub-graph as nodes/edges for visualization."""
        if self.driver is None:
            return {"nodes": [], "edges": []}
        with self.driver.session() as session:
            nodes_res = session.run(
                "MATCH (n:Node) RETURN n.id AS id, n.role AS role, n.flows AS flows ORDER BY n.flows DESC LIMIT $limit",
                {"limit": top_n}
            )
            nodes = [{"id": r["id"], "role": r["role"], "flows": r["flows"]} for r in nodes_res]
            keep_ids = {n["id"] for n in nodes}

            edges_res = session.run(
                """
                MATCH (u:Node)-[r:DEPENDS_ON]->(v:Node)
                WHERE u.id IN $keep AND v.id IN $keep
                RETURN u.id AS source, v.id AS target, r.flows AS flows, r.attack_flows AS attack_flows, r.service AS service
                """       ,
                {"keep": list(keep_ids)}
            )
            edges = [{
                "source": r["source"], "target": r["target"], "flows": r["flows"],
                "attack_flows": r["attack_flows"], "service": r["service"]
            } for r in edges_res]

        return {"nodes": nodes, "edges": edges}

    @property
    def stats(self) -> dict:
        if self.driver is None:
            return {"nodes": 0, "edges": 0}
        with self.driver.session() as session:
            n_count = session.run("MATCH (n:Node) RETURN count(n) AS c").single()["c"]
            e_count = session.run("MATCH ()-[r:DEPENDS_ON]->() RETURN count(r) AS c").single()["c"]
        return {"nodes": n_count, "edges": e_count}
