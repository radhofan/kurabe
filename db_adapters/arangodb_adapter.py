import time
from arango import ArangoClient
from db_adapters.base import BaseDBAdapter
from config import ARANGODB_URI, ARANGODB_USER, ARANGODB_PASSWORD, ARANGODB_DATABASE

class ArangoDBAdapter(BaseDBAdapter):
    def __init__(self):
        super().__init__('ArangoDB')
        self.uri = ARANGODB_URI
        self.user = ARANGODB_USER
        self.password = ARANGODB_PASSWORD
        self.db_name = ARANGODB_DATABASE
        self.client = None
        self.db = None
        self.graph = None
        self.persons = None
        self.connected_to = None

    def connect(self):
        self.client = ArangoClient(hosts=self.uri)
        sys_db = self.client.db('_system', username=self.user, password=self.password)
        if not sys_db.has_database(self.db_name):
            sys_db.create_database(self.db_name)
        self.db = self.client.db(self.db_name, username=self.user, password=self.password)

        if not self.db.has_collection('persons'):
            self.persons = self.db.create_collection('persons')
        else:
            self.persons = self.db.collection('persons')

        if not self.db.has_collection('connected_to'):
            self.connected_to = self.db.create_collection('connected_to', edge=True)
        else:
            self.connected_to = self.db.collection('connected_to')

        if not self.db.has_graph('social_graph'):
            self.graph = self.db.create_graph('social_graph')
            self.graph.create_edge_definition(
                edge_collection='connected_to',
                from_vertex_collections=['persons'],
                to_vertex_collections=['persons']
            )
        else:
            self.graph = self.db.graph('social_graph')

        self.persons.add_persistent_index(fields=['id'], unique=True)
        self.persons.add_persistent_index(fields=['age', 'region'])

    def clear_database(self):
        """Full database wipe: drops graph and collections."""
        if self.db:
            if self.db.has_graph('social_graph'):
                self.db.delete_graph('social_graph', drop_collections=True)
            if self.db.has_collection('persons'):
                self.db.delete_collection('persons')
            if self.db.has_collection('connected_to'):
                self.db.delete_collection('connected_to')
            self.connect()

    def load_data(self, nodes, edges, batch_size=1000):
        start_time = time.time()

        for i in range(0, len(nodes), batch_size):
            batch = nodes[i:i + batch_size]
            docs = [
                {
                    '_key': str(n['id']),
                    'id': n['id'],
                    'name': n['name'],
                    'gender': n['gender'],
                    'age': n['age'],
                    'region': n['region']
                } for n in batch
            ]
            self.persons.insert_many(docs)

        for i in range(0, len(edges), batch_size):
            batch = edges[i:i + batch_size]
            edge_docs = [
                {
                    '_from': f"persons/{e['source']}",
                    '_to': f"persons/{e['target']}",
                    'weight': e['weight']
                } for e in batch
            ]
            self.connected_to.insert_many(edge_docs)

        total_time = time.time() - start_time
        return {
            'total_time_sec': total_time,
            'nodes_per_sec': len(nodes) / total_time if total_time > 0 else 0,
            'edges_per_sec': len(edges) / total_time if total_time > 0 else 0
        }

    def _execute_aql(self, query, bind_vars=None):
        t0 = time.time()
        cursor = self.db.aql.execute(query, bind_vars=bind_vars or {})
        _ = list(cursor)
        return (time.time() - t0) * 1000.0

    def run_1hop(self, node_id):
        query = 'FOR v IN 1..1 OUTBOUND @startId GRAPH "social_graph" RETURN v._key'
        return self._execute_aql(query, {'startId': f'persons/{node_id}'})

    def run_2hop(self, node_id):
        query = 'FOR v IN 2..2 OUTBOUND @startId GRAPH "social_graph" RETURN DISTINCT v._key'
        return self._execute_aql(query, {'startId': f'persons/{node_id}'})

    def run_3hop(self, node_id):
        query = 'FOR v IN 3..3 OUTBOUND @startId GRAPH "social_graph" RETURN DISTINCT v._key'
        return self._execute_aql(query, {'startId': f'persons/{node_id}'})

    def point_lookup(self, node_id):
        query = 'FOR p IN persons FILTER p.id == @id RETURN {name: p.name, region: p.region}'
        return self._execute_aql(query, {'id': node_id})

    def filtered_lookup(self, age, region):
        query = 'FOR p IN persons FILTER p.age == @age AND p.region == @region RETURN {id: p.id, name: p.name}'
        return self._execute_aql(query, {'age': age, 'region': region})

    def aggregation_query(self):
        # Valid ArangoDB AQL aggregation syntax
        query = 'FOR p IN persons COLLECT reg = p.region AGGREGATE total = COUNT(1), avgAge = AVG(p.age) RETURN {region: reg, total: total, avg_age: avgAge}'
        return self._execute_aql(query)

    def write_single_edge(self, source_id, target_id):
        query = 'INSERT {_from: @from_val, _to: @to_val, weight: 1.0} INTO connected_to'
        return self._execute_aql(query, {'from_val': f'persons/{source_id}', 'to_val': f'persons/{target_id}'})

    def get_footprint(self):
        ram_val = "Not observable"
        storage_val = "Not observable"
        try:
            if hasattr(self, 'persons') and hasattr(self, 'connected_to') and self.persons and self.connected_to:
                p_stats = self.persons.statistics()
                c_stats = self.connected_to.statistics()
                p_size = p_stats.get('dataSize', 0) or p_stats.get('size', 0) or p_stats.get('figures', {}).get('dataSize', 0)
                c_size = c_stats.get('dataSize', 0) or c_stats.get('size', 0) or c_stats.get('figures', {}).get('dataSize', 0)
                bytes_sum = p_size + c_size
                if bytes_sum > 0:
                    storage_val = f"{bytes_sum / (1024**2):.2f} MB"
                else:
                    p_count = self.persons.count()
                    c_count = self.connected_to.count()
                    if p_count or c_count:
                        storage_val = f"{p_count} nodes / {c_count} rels"
        except Exception:
            pass

        try:
            stats = self.db.statistics()
            mem = stats.get('system', {}).get('virtualSize', 0)
            if mem > 0:
                ram_val = f"{mem / (1024**2):.1f} MB"
        except Exception:
            pass

        return {
            'allocated_ram': ram_val,
            'allocated_cpu': '0.25 vCPU cap',
            'max_storage': storage_val
        }

    def close(self):
        pass
