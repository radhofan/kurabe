from abc import ABC, abstractmethod

class BaseDBAdapter(ABC):
    def __init__(self, name):
        self.name = name

    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def clear_database(self):
        """Deletes all nodes, relationships, and collections from the database."""
        pass

    @abstractmethod
    def load_data(self, nodes, edges, batch_size=1000):
        """
        Loads SNAP Pokec dataset into database in batches.
        Returns dict with total_time_sec, nodes_per_sec, edges_per_sec.
        """
        pass

    @abstractmethod
    def run_1hop(self, node_id):
        """Runs 1-hop traversal query from node_id. Returns latency in ms."""
        pass

    @abstractmethod
    def run_2hop(self, node_id):
        """Runs 2-hop traversal query from node_id. Returns latency in ms."""
        pass

    @abstractmethod
    def run_3hop(self, node_id):
        """Runs 3-hop traversal query from node_id. Returns latency in ms."""
        pass

    @abstractmethod
    def point_lookup(self, node_id):
        """Runs point lookup for single node by ID. Returns latency in ms."""
        pass

    @abstractmethod
    def filtered_lookup(self, age, region):
        """Runs indexed/filtered lookup query on Pokec attributes (age, region). Returns latency in ms."""
        pass

    @abstractmethod
    def aggregation_query(self):
        """Runs group-by aggregation query over Pokec regions. Returns latency in ms."""
        pass

    @abstractmethod
    def write_single_edge(self, source_id, target_id):
        """Inserts single relationship for mixed read/write workload. Returns latency in ms."""
        pass

    @abstractmethod
    def get_footprint(self):
        """Returns storage size, memory usage, and instance specs."""
        pass

    @abstractmethod
    def close(self):
        pass
