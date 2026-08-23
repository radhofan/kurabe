import time
from neo4j import GraphDatabase
from db_adapters.base import BaseDBAdapter
from config import MEMGRAPH_URI, MEMGRAPH_USER, MEMGRAPH_PASSWORD

class MemgraphAdapter(BaseDBAdapter):
    def __init__(self):
        super().__init__('Memgraph')
        self.uri = MEMGRAPH_URI
        self.user = MEMGRAPH_USER
        self.password = MEMGRAPH_PASSWORD
        self.driver = None

    def connect(self):
        auth = (self.user, self.password) if self.user else None
        self.driver = GraphDatabase.driver(self.uri, auth=auth)

    def clear_database(self):
        """Full database wipe: deletes ALL nodes/edges and drops indexes."""
        with self.driver.session() as session:
            session.run('MATCH (n) DETACH DELETE n')
            try:
                session.run('DROP INDEX ON :Person(id)')
                session.run('DROP INDEX ON :Person(age, region)')
            except Exception:
                pass

    def load_data(self, nodes, edges, batch_size=1000):
        start_time = time.time()
        with self.driver.session() as session:
            for i in range(0, len(nodes), batch_size):
                batch = nodes[i:i + batch_size]
                session.run(
                    'UNWIND $batch AS row '
                    'CREATE (:Person {id: row.id, name: row.name, gender: row.gender, age: row.age, region: row.region})',
                    batch=batch
                )

            try:
                session.run('CREATE INDEX ON :Person(id)')
                session.run('CREATE INDEX ON :Person(age, region)')
            except Exception:
                pass

            for i in range(0, len(edges), batch_size):
                batch = edges[i:i + batch_size]
                session.run(
                    'UNWIND $batch AS row '
                    'MATCH (src:Person {id: row.source}), (dst:Person {id: row.target}) '
                    'CREATE (src)-[:CONNECTED_TO {weight: row.weight}]->(dst)',
                    batch=batch
                )

        total_time = time.time() - start_time
        return {
            'total_time_sec': total_time,
            'nodes_per_sec': len(nodes) / total_time if total_time > 0 else 0,
            'edges_per_sec': len(edges) / total_time if total_time > 0 else 0
        }

    def _execute_cypher(self, cypher_query, params=None):
        t0 = time.time()
        with self.driver.session() as session:
            result = session.run(cypher_query, params or {})
            _ = list(result)
        return (time.time() - t0) * 1000.0

    def run_1hop(self, node_id):
        query = 'MATCH (p:Person {id: $id})-[:CONNECTED_TO]->(m) RETURN m.id'
        return self._execute_cypher(query, {'id': node_id})

    def run_2hop(self, node_id):
        query = 'MATCH (p:Person {id: $id})-[:CONNECTED_TO*2]->(m) RETURN DISTINCT m.id'
        return self._execute_cypher(query, {'id': node_id})

    def run_3hop(self, node_id):
        query = 'MATCH (p:Person {id: $id})-[:CONNECTED_TO*3]->(m) RETURN DISTINCT m.id'
        return self._execute_cypher(query, {'id': node_id})

    def point_lookup(self, node_id):
        query = 'MATCH (p:Person {id: $id}) RETURN p.name, p.region'
        return self._execute_cypher(query, {'id': node_id})

    def filtered_lookup(self, age, region):
        query = 'MATCH (p:Person {age: $age, region: $region}) RETURN p.id, p.name'
        return self._execute_cypher(query, {'age': age, 'region': region})

    def aggregation_query(self):
        query = 'MATCH (p:Person) RETURN p.region, count(p) as total, avg(p.age) as avg_age'
        return self._execute_cypher(query)

    def write_single_edge(self, source_id, target_id):
        query = (
            'MATCH (src:Person {id: $src}), (dst:Person {id: $dst}) '
            'CREATE (src)-[:CONNECTED_TO {weight: 1.0}]->(dst)'
        )
        return self._execute_cypher(query, {'src': source_id, 'dst': target_id})

    def get_footprint(self):
        ram_val = "Not observable"
        storage_val = "Not observable"
        if self.driver:
            try:
                with self.driver.session() as session:
                    res = session.run("CALL mg.memory() YIELD * RETURN *")
                    rec = res.single()
                    if rec and rec.get('allocator_allocated') is not None:
                        ram_val = f"{rec['allocator_allocated'] / (1024**2):.1f} MB"
            except Exception:
                pass
        return {
            'allocated_ram': ram_val,
            'allocated_cpu': '0.25 vCPU cap',
            'max_storage': storage_val
        }

    def close(self):
        if self.driver:
            self.driver.close()
