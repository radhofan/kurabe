import time
import requests
from db_adapters.base import BaseDBAdapter
from config import SURREALDB_URI, SURREALDB_USER, SURREALDB_PASSWORD, SURREALDB_NS, SURREALDB_DB

class SurrealDBAdapter(BaseDBAdapter):
    def __init__(self):
        super().__init__('SurrealDB')
        self.url = f"{SURREALDB_URI.rstrip('/')}/sql"
        self.auth = (SURREALDB_USER, SURREALDB_PASSWORD)
        self.headers = {
            'NS': SURREALDB_NS,
            'DB': SURREALDB_DB,
            'Accept': 'application/json'
        }

    def connect(self):
        sql = "DEFINE INDEX idx_person_id ON person FIELDS id UNIQUE; DEFINE INDEX idx_person_filter ON person FIELDS age, region;"
        self._send_sql(sql)

    def _send_sql(self, sql_query):
        t0 = time.time()
        res = requests.post(self.url, auth=self.auth, headers=self.headers, data=sql_query, timeout=30)
        elapsed = (time.time() - t0) * 1000.0
        if res.status_code != 200:
            raise RuntimeError(f"SurrealDB Query Error [{res.status_code}]: {res.text}")
        return elapsed, res.json()

    def clear_database(self):
        """Full database wipe: deletes all tables, records, and indexes."""
        self._send_sql("REMOVE TABLE person; REMOVE TABLE connected_to;")

    def load_data(self, nodes, edges, batch_size=1000):
        start_time = time.time()
        self.connect()
        self._send_sql("DEFINE INDEX idx_person_id ON TABLE person COLUMNS id UNIQUE; DEFINE INDEX idx_person_filter ON TABLE person COLUMNS age, region;")

        for i in range(0, len(nodes), batch_size):
            batch = nodes[i:i + batch_size]
            statements = []
            for n in batch:
                region_escaped = str(n['region']).replace("'", "\\'")
                statements.append(
                    f"CREATE person:{n['id']} SET id = {n['id']}, name = '{n['name']}', "
                    f"gender = {n['gender']}, age = {n['age']}, region = '{region_escaped}';"
                )
            self._send_sql("\n".join(statements))

        for i in range(0, len(edges), batch_size):
            batch = edges[i:i + batch_size]
            statements = []
            for e in batch:
                statements.append(
                    f"RELATE person:{e['source']}->connected_to->person:{e['target']} SET weight = {e['weight']};"
                )
            self._send_sql("\n".join(statements))

        total_time = time.time() - start_time
        return {
            'total_time_sec': total_time,
            'nodes_per_sec': len(nodes) / total_time if total_time > 0 else 0,
            'edges_per_sec': len(edges) / total_time if total_time > 0 else 0
        }

    def run_1hop(self, node_id):
        sql = f"SELECT ->connected_to->person.id AS target FROM person:{node_id};"
        elapsed, _ = self._send_sql(sql)
        return elapsed

    def run_2hop(self, node_id):
        sql = f"SELECT ->connected_to->person->connected_to->person.id AS target FROM person:{node_id};"
        elapsed, _ = self._send_sql(sql)
        return elapsed

    def run_3hop(self, node_id):
        sql = f"SELECT ->connected_to->person->connected_to->person->connected_to->person.id AS target FROM person:{node_id};"
        elapsed, _ = self._send_sql(sql)
        return elapsed

    def point_lookup(self, node_id):
        sql = f"SELECT name, region FROM person:{node_id};"
        elapsed, _ = self._send_sql(sql)
        return elapsed

    def filtered_lookup(self, age, region):
        region_escaped = str(region).replace("'", "\\'")
        sql = f"SELECT id, name FROM person WHERE age = {age} AND region = '{region_escaped}';"
        elapsed, _ = self._send_sql(sql)
        return elapsed

    def aggregation_query(self):
        sql = "SELECT region, count(), math::mean(age) FROM person GROUP BY region;"
        elapsed, _ = self._send_sql(sql)
        return elapsed

    def write_single_edge(self, source_id, target_id):
        sql = f"RELATE person:{source_id}->connected_to->person:{target_id} SET weight = 1.0;"
        elapsed, _ = self._send_sql(sql)
        return elapsed

    def get_footprint(self):
        ram_val = "Not observable"
        storage_val = "Not observable"
        if self.url:
            try:
                sql = "SELECT count() FROM person GROUP ALL; SELECT count() FROM connected_to GROUP ALL;"
                elapsed, res = self._send_sql(sql)
                if res and isinstance(res, list) and len(res) >= 2:
                    p_res = res[0].get('result', [])
                    c_res = res[1].get('result', [])
                    p_count = p_res[0].get('count', 0) if p_res and isinstance(p_res, list) and len(p_res) > 0 else 0
                    c_count = c_res[0].get('count', 0) if c_res and isinstance(c_res, list) and len(c_res) > 0 else 0
                    if p_count or c_count:
                        storage_val = f"{p_count} nodes / {c_count} rels"
            except Exception:
                pass
        return {
            'allocated_ram': ram_val,
            'allocated_cpu': '0.25 vCPU cap',
            'max_storage': storage_val
        }

    def close(self):
        pass
