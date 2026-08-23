import time
from neo4j import GraphDatabase
from db_adapters.base import BaseDBAdapter
from config import AURADB_URI, AURADB_USER, AURADB_PASSWORD

class AuraDBAdapter(BaseDBAdapter):
    def __init__(self):
        super().__init__('AuraDB')
        self.uri = AURADB_URI
        self.user = AURADB_USER
        self.password = AURADB_PASSWORD
        self.driver = None

    def connect(self):
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))

    def clear_database(self):
        """Full database wipe: deletes ALL nodes/edges and drops indexes."""
        with self.driver.session() as session:
            while True:
                result = session.run('MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(n) as deleted')
                record = result.single()
                if not record or record['deleted'] == 0:
                    break

            try:
                session.run('DROP INDEX person_id_idx IF EXISTS')
                session.run('DROP INDEX person_filter_idx IF EXISTS')
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

            session.run('CREATE INDEX person_id_idx IF NOT EXISTS FOR (p:Person) ON (p.id)')
            session.run('CREATE INDEX person_filter_idx IF NOT EXISTS FOR (p:Person) ON (p.age, p.region)')

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
        ram_val = "not observable"
        storage_val = "not observable"
        if self.driver:
            try:
                with self.driver.session() as session:
                    res = session.run("CALL apoc.meta.stats() YIELD nodeCount, relCount RETURN nodeCount, relCount")
                    rec = res.single()
                    if rec:
                        storage_val = f"{rec['nodeCount']} nodes / {rec['relCount']} rels"
            except Exception:
                pass
        return {
            'allocated_ram': ram_val,
            'allocated_cpu': '0.25 vCPU cap',
            'max_storage': storage_val,
            'info': 'Neo4j AuraDB Free Instance'
        }

    def close(self):
        if self.driver:
            self.driver.close()
