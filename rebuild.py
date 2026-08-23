import argparse
import sys
from dataset import generate_benchmark_dataset
from config import ResourceCapEnforcer
from db_adapters.cognodb_adapter import CognoDBAdapter
from db_adapters.auradb_adapter import AuraDBAdapter
from db_adapters.memgraph_adapter import MemgraphAdapter
from db_adapters.surrealdb_adapter import SurrealDBAdapter
from db_adapters.arangodb_adapter import ArangoDBAdapter

ADAPTER_MAP = {
    'cognodb': CognoDBAdapter,
    'auradb': AuraDBAdapter,
    'memgraph': MemgraphAdapter,
    'surrealdb': SurrealDBAdapter,
    'surreal': SurrealDBAdapter,
    'arangodb': ArangoDBAdapter,
    'arango': ArangoDBAdapter
}

def rebuild_single_service(db_key, nodes, edges, batch_size=1000):
    """
    Automates rebuilding a database service:
    1. Connects to the database.
    2. Clears/deletes all existing data (nodes, relationships, collections).
    3. Repopulates the database with the target benchmark dataset.
    """
    key_clean = db_key.lower().strip()
    if key_clean not in ADAPTER_MAP:
        raise ValueError(f"Unknown database service '{db_key}'. Available: cognodb, auradb, memgraph, surrealdb (or surreal), arangodb (or arango)")

    adapter_cls = ADAPTER_MAP[key_clean]
    adapter = adapter_cls(apply_cpu_throttling=False) if key_clean == 'cognodb' else adapter_cls()

    print(f"\n==========================================")
    print(f"  Rebuilding Database: {adapter.name}")
    print(f"==========================================")

    try:
        adapter.connect()
        print(f"[{adapter.name}] Clearing existing data...")
        adapter.clear_database()
        print(f"[{adapter.name}] Database cleared successfully.")

        print(f"[{adapter.name}] Repopulating database with {len(nodes):,} nodes and {len(edges):,} edges...")
        stats = adapter.load_data(nodes, edges, batch_size=batch_size)
        print(f"[{adapter.name}] Repopulation complete in {stats['total_time_sec']:.2f}s "
              f"({stats['nodes_per_sec']:.1f} nodes/sec, {stats['edges_per_sec']:.1f} edges/sec).")
        return stats
    except Exception as e:
        print(f"[{adapter.name}] ERROR during rebuild: {e}")
        return None
    finally:
        adapter.close()

def rebuild_all_services(num_nodes=20000, num_edges=100000, target_services=None, batch_size=1000):
    """
    Support function that automates rebuilding DB for all specified services
    by deleting them and repopulating them with the database.
    """
    nodes, edges, estimated_bytes = generate_benchmark_dataset(num_nodes=num_nodes, num_edges=num_edges)
    ResourceCapEnforcer.enforce_storage_limit(estimated_bytes)

    if target_services is None or 'all' in target_services:
        target_services = ['cognodb', 'auradb', 'memgraph', 'surrealdb', 'arangodb']

    results = {}
    for service_key in target_services:
        res = rebuild_single_service(service_key, nodes, edges, batch_size=batch_size)
        results[service_key] = res

    print("\nSummary of Database Rebuild Operations:")
    for service, res in results.items():
        status = "SUCCESS" if res else "FAILED"
        print(f" - {service.upper()}: {status}")

    return results

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Automated Database Rebuild & Repopulation Tool')
    parser.add_argument('--services', nargs='+', default=['all'], help='Services to rebuild: cognodb auradb memgraph surrealdb (or surreal) arangodb (or arango)')
    parser.add_argument('--nodes', type=int, default=20000, help='Number of nodes to populate')
    parser.add_argument('--edges', type=int, default=100000, help='Number of edges/relationships to populate (default: 100,000)')
    parser.add_argument('--batch-size', type=int, default=1000, help='Batch size for bulk insertion')

    args = parser.parse_args()
    rebuild_all_services(num_nodes=args.nodes, num_edges=args.edges, target_services=args.services, batch_size=args.batch_size)
