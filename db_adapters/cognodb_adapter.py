import time
from neo4j import GraphDatabase
from neo4j.exceptions import TransientError, ServiceUnavailable, SessionExpired, DriverError
from db_adapters.base import BaseDBAdapter
from config import COGNODB_URI, COGNODB_USER, COGNODB_PASSWORD, CpuFairnessRegulator

class CognoDBAdapter(BaseDBAdapter):
    def __init__(self, apply_cpu_throttling=True):
        super().__init__('CognoDB')
        self.uri = COGNODB_URI
        self.user = COGNODB_USER
        self.password = COGNODB_PASSWORD
        self.driver = None
        self.cpu_regulator = CpuFairnessRegulator(platform_vcpu=0.5, target_vcpu=0.25, enabled=apply_cpu_throttling)

    def connect(self):
        if self.driver:
            try:
                self.driver.close()
            except Exception:
                pass
        self.driver = GraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password),
            max_connection_lifetime=30,
            max_connection_pool_size=5,
            connection_timeout=30
        )

    def clear_database(self):
        """Full database wipe: deletes ALL nodes/edges and drops indexes."""
        self.connect()
        while True:
            try:
                with self.driver.session() as session:
                    result = session.run('MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(n) as deleted')
                    record = result.single()
                    if not record or record['deleted'] == 0:
                        break
            except Exception:
                self.connect()

        try:
            with self.driver.session() as session:
                session.run('DROP INDEX person_id_idx IF EXISTS')
                session.run('DROP INDEX person_filter_idx IF EXISTS')
        except Exception:
            pass

    def load_data(self, nodes, edges, batch_size=1000):
        start_time = time.time()
        self.connect()

        # 1. Insert nodes in batches of 1000
        print("   [CognoDB] Ingesting nodes...")
        for i in range(0, len(nodes), batch_size):
            batch = nodes[i:i + batch_size]
            self._execute_batch_with_reconnect(
                'UNWIND $batch AS row '
                'CREATE (:Person {id: row.id, name: row.name, gender: row.gender, age: row.age, region: row.region})',
                {'batch': batch}
            )

        # 2. Build and sync node indexes
        print("   [CognoDB] Building and syncing node indexes...")
        self._execute_batch_with_reconnect('CREATE INDEX person_id_idx IF NOT EXISTS FOR (p:Person) ON (p.id)')
        self._execute_batch_with_reconnect('CREATE INDEX person_filter_idx IF NOT EXISTS FOR (p:Person) ON (p.age, p.region)')
        try:
            self._execute_batch_with_reconnect('CALL db.awaitIndexes(300)')
        except Exception:
            pass

        # 3. Insert relationships using batches of 1000 items
        print(f"   [CognoDB] Ingesting {len(edges):,} relationships...")
        edge_batch_size = batch_size
        for i in range(0, len(edges), edge_batch_size):
            batch = edges[i:i + edge_batch_size]
            self._execute_batch_with_reconnect(
                'UNWIND $batch AS row '
                'MATCH (src:Person {id: row.source}), (dst:Person {id: row.target}) '
                'CREATE (src)-[:CONNECTED_TO {weight: row.weight}]->(dst)',
                {'batch': batch}
            )

        total_time = time.time() - start_time
        return {
            'total_time_sec': total_time,
            'nodes_per_sec': len(nodes) / total_time if total_time > 0 else 0,
            'edges_per_sec': len(edges) / total_time if total_time > 0 else 0
        }

    def _execute_batch_with_reconnect(self, cypher, params=None, max_retries=5):
        """Executes Cypher batch with driver pool re-initialization on defunct TCP sockets."""
        for attempt in range(max_retries):
            try:
                if not self.driver:
                    self.connect()
                with self.driver.session() as session:
                    result = session.run(cypher, params or {})
                    _ = list(result)
                    return
            except (TransientError, ServiceUnavailable, SessionExpired, DriverError, Exception) as e:
                err_str = str(e).lower()
                if attempt < max_retries - 1:
                    time.sleep(1.0)
                    try:
                        self.connect()
                    except Exception:
                        pass
                else:
                    raise

    def _execute_cypher(self, cypher_query, params=None):
        t0 = time.time()
        self._execute_batch_with_reconnect(cypher_query, params)
        elapsed = (time.time() - t0) * 1000.0
        self.cpu_regulator.throttle(elapsed / 1000.0)
        return elapsed

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
            'allocated_cpu': '0.5 vCPU burst (throttled to 0.25 vCPU cap)',
            'max_storage': storage_val,
            'info': 'CognoDB Cloud Free Tier'
        }

    def close(self):
        if self.driver:
            try:
                self.driver.close()
            except Exception:
                pass
