import os
import random
import time
import argparse
import concurrent.futures
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from tabulate import tabulate
from dataset import generate_benchmark_dataset
from config import ResourceCapEnforcer
from db_adapters.cognodb_adapter import CognoDBAdapter
from db_adapters.auradb_adapter import AuraDBAdapter
from db_adapters.memgraph_adapter import MemgraphAdapter
from db_adapters.surrealdb_adapter import SurrealDBAdapter
from db_adapters.arangodb_adapter import ArangoDBAdapter

ADAPTERS = {
    'cognodb': CognoDBAdapter,
    'auradb': AuraDBAdapter,
    'memgraph': MemgraphAdapter,
    'surrealdb': SurrealDBAdapter,
    'surreal': SurrealDBAdapter,
    'arangodb': ArangoDBAdapter,
    'arango': ArangoDBAdapter
}

def calculate_percentiles(latencies):
    if not latencies:
        return 0.0, 0.0
    arr = np.array(latencies)
    return round(float(np.percentile(arr, 50)), 2), round(float(np.percentile(arr, 95)), 2)

def run_mixed_workload_worker(adapter, duration_sec, node_ids, read_ratio=0.8):
    start_time = time.time()
    ops_completed = 0
    errors = 0

    while time.time() - start_time < duration_sec:
        try:
            if random.random() < read_ratio:
                nid = random.choice(node_ids)
                adapter.run_1hop(nid)
            else:
                src = random.choice(node_ids)
                dst = random.choice(node_ids)
                adapter.write_single_edge(src, dst)
            ops_completed += 1
        except Exception:
            errors += 1

    return ops_completed, errors

def benchmark_mixed_workload(adapter_cls, node_ids, concurrency_levels, duration_sec=5, apply_cpu_throttling=True):
    results = {}
    for clients in concurrency_levels:
        adapters = [
            adapter_cls(apply_cpu_throttling=apply_cpu_throttling) if adapter_cls == CognoDBAdapter else adapter_cls()
            for _ in range(clients)
        ]
        for a in adapters:
            a.connect()

        with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as executor:
            futures = [
                executor.submit(run_mixed_workload_worker, a, duration_sec, node_ids, 0.8)
                for a in adapters
            ]
            completed_stats = [f.result() for f in concurrent.futures.as_completed(futures)]

        total_ops = sum(stat[0] for stat in completed_stats)
        qps = round(total_ops / duration_sec, 2)
        results[f'mixed_qps_{clients}_clients'] = qps

        for a in adapters:
            a.close()
    return results

def run_benchmark_for_adapter(db_key, nodes, edges, iterations=100, concurrency_levels=(1, 10, 40), apply_cpu_throttling=True):
    key_clean = db_key.lower().strip()
    adapter_cls = ADAPTERS[key_clean]
    adapter = adapter_cls(apply_cpu_throttling=apply_cpu_throttling) if key_clean == 'cognodb' else adapter_cls()

    print(f"\n=======================================================")
    print(f"   Starting PDF-Compliant Benchmark for: {adapter.name}")
    print(f"=======================================================")

    metrics = {
        'platform': adapter.name,
        'indexed_properties': 'id, (age, region)'
    }

    try:
        adapter.connect()
        print(f"[{adapter.name}] Clearing database...")
        adapter.clear_database()

        # Category 1: Data Loading
        print(f"[{adapter.name}] PDF Metric: Data Ingest Throughput ({len(nodes):,} nodes, {len(edges):,} edges)...")
        load_stats = adapter.load_data(nodes, edges)
        metrics['load_total_wall_clock_sec'] = round(load_stats['total_time_sec'], 2)
        metrics['ingest_nodes_per_sec'] = round(load_stats['nodes_per_sec'], 1)
        metrics['ingest_edges_per_sec'] = round(load_stats['edges_per_sec'], 1)

        node_ids = [n['id'] for n in nodes]
        sample_node_ids = [random.choice(node_ids) for _ in range(iterations)]
        regions = list(set([n['region'] for n in nodes if n.get('region')]))
        if not regions:
            regions = ['unknown']

        # Warmup Run
        print(f"[{adapter.name}] Warming up query engines...")
        for nid in sample_node_ids[:10]:
            adapter.run_1hop(nid)

        # Category 2: Traversals (1-hop, 2-hop, 3-hop)
        print(f"[{adapter.name}] PDF Metric: 1-hop traversal p50/p95 latency...")
        lat_1hop = [adapter.run_1hop(nid) for nid in sample_node_ids]
        p50, p95 = calculate_percentiles(lat_1hop)
        metrics['traversal_1hop_p50_ms'] = p50
        metrics['traversal_1hop_p95_ms'] = p95

        print(f"[{adapter.name}] PDF Metric: 2-hop traversal p50/p95 latency...")
        lat_2hop = [adapter.run_2hop(nid) for nid in sample_node_ids]
        p50, p95 = calculate_percentiles(lat_2hop)
        metrics['traversal_2hop_p50_ms'] = p50
        metrics['traversal_2hop_p95_ms'] = p95

        print(f"[{adapter.name}] PDF Metric: 3-hop traversal p50/p95 latency...")
        lat_3hop = [adapter.run_3hop(nid) for nid in sample_node_ids]
        p50, p95 = calculate_percentiles(lat_3hop)
        metrics['traversal_3hop_p50_ms'] = p50
        metrics['traversal_3hop_p95_ms'] = p95

        # Category 3: Lookups (Point & Filtered/Indexed)
        print(f"[{adapter.name}] PDF Metric: Point lookup p50/p95 latency...")
        lat_point = [adapter.point_lookup(nid) for nid in sample_node_ids]
        p50, p95 = calculate_percentiles(lat_point)
        metrics['lookup_point_p50_ms'] = p50
        metrics['lookup_point_p95_ms'] = p95

        print(f"[{adapter.name}] PDF Metric: Filtered/Indexed lookup p50/p95 latency...")
        lat_filter = [adapter.filtered_lookup(random.randint(18, 60), random.choice(regions)) for _ in range(iterations)]
        p50, p95 = calculate_percentiles(lat_filter)
        metrics['lookup_filtered_p50_ms'] = p50
        metrics['lookup_filtered_p95_ms'] = p95

        # Category 4: Aggregations
        print(f"[{adapter.name}] PDF Metric: Count / group-by aggregation p50/p95 latency...")
        lat_agg = [adapter.aggregation_query() for _ in range(iterations)]
        p50, p95 = calculate_percentiles(lat_agg)
        metrics['aggregation_p50_ms'] = p50
        metrics['aggregation_p95_ms'] = p95

        # Category 5: Mixed Workload Concurrency Sweeps
        print(f"[{adapter.name}] PDF Metric: Mixed read/write sustained throughput ({concurrency_levels} clients)...")
        mixed_stats = benchmark_mixed_workload(adapter_cls, node_ids, concurrency_levels, duration_sec=5, apply_cpu_throttling=apply_cpu_throttling)
        metrics.update(mixed_stats)

        # Category 6: Footprint (Query observable platform usage or report unobservable per PDF spec)
        fp = adapter.get_footprint()
        metrics['allocated_ram'] = fp.get('allocated_ram', 'Not observable')
        metrics['target_vcpu'] = fp.get('allocated_cpu', '0.25 vCPU cap')
        metrics['footprint_storage'] = fp.get('max_storage', 'Not observable')

        print(f"[{adapter.name}] All required PDF metrics collected successfully.")
        return metrics

    except Exception as e:
        print(f"[{adapter.name}] BENCHMARK ERROR: {e}")
        return None
    finally:
        adapter.close()

def generate_result_charts(df, results_dir='results'):
    """
    Generates PDF-compliant visual charts in the results/ folder.
    """
    os.makedirs(results_dir, exist_ok=True)
    platforms = df['platform'].tolist()

    # Chart 1: Ingest Throughput
    plt.figure(figsize=(10, 6))
    x = np.arange(len(platforms))
    width = 0.35
    plt.bar(x - width/2, df['ingest_nodes_per_sec'], width, label='Nodes/sec')
    plt.bar(x + width/2, df['ingest_edges_per_sec'], width, label='Edges/sec')
    plt.xlabel('Database Platform')
    plt.ylabel('Throughput (records/sec)')
    plt.title('Data Loading Ingest Throughput (SNAP Pokec)')
    plt.xticks(x, platforms)
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, 'ingest_throughput.png'))
    plt.close()

    # Chart 2: Traversals Latency (p50 and p95)
    plt.figure(figsize=(12, 6))
    width = 0.12
    x = np.arange(len(platforms))
    plt.bar(x - 2.5*width, df['traversal_1hop_p50_ms'], width, label='1-hop p50')
    plt.bar(x - 1.5*width, df['traversal_1hop_p95_ms'], width, label='1-hop p95')
    plt.bar(x - 0.5*width, df['traversal_2hop_p50_ms'], width, label='2-hop p50')
    plt.bar(x + 0.5*width, df['traversal_2hop_p95_ms'], width, label='2-hop p95')
    plt.bar(x + 1.5*width, df['traversal_3hop_p50_ms'], width, label='3-hop p50')
    plt.bar(x + 2.5*width, df['traversal_3hop_p95_ms'], width, label='3-hop p95')
    plt.xlabel('Database Platform')
    plt.ylabel('Latency (ms)')
    plt.title('Traversal Query Latencies (1-hop, 2-hop, 3-hop)')
    plt.xticks(x, platforms)
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, 'traversal_latencies.png'))
    plt.close()

    # Chart 3: Lookups & Aggregations
    plt.figure(figsize=(10, 6))
    width = 0.2
    x = np.arange(len(platforms))
    plt.bar(x - 1.5*width, df['lookup_point_p50_ms'], width, label='Point Lookup p50')
    plt.bar(x - 0.5*width, df['lookup_filtered_p50_ms'], width, label='Filtered Lookup p50')
    plt.bar(x + 0.5*width, df['aggregation_p50_ms'], width, label='Aggregation p50')
    plt.xlabel('Database Platform')
    plt.ylabel('Latency (ms)')
    plt.title('Lookup and Aggregation p50 Latencies')
    plt.xticks(x, platforms)
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, 'lookup_aggregation_latencies.png'))
    plt.close()

    # Chart 4: Mixed Workload Concurrency Sweep
    plt.figure(figsize=(10, 6))
    client_cols = [c for c in df.columns if c.startswith('mixed_qps_')]
    client_labels = [c.replace('mixed_qps_', '').replace('_clients', ' Clients') for c in client_cols]

    for idx, row in df.iterrows():
        plt.plot(client_labels, [row[c] for c in client_cols], marker='o', linewidth=2, label=row['platform'])

    plt.xlabel('Client Concurrency')
    plt.ylabel('Sustained Queries / Second (QPS)')
    plt.title('Mixed Read/Write Workload Concurrency Sweep (80% Read / 20% Write)')
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, 'mixed_workload_concurrency.png'))
    plt.close()

    print(f"\nGenerated 4 benchmark metric charts in '{results_dir}/' folder.")

def main():
    parser = argparse.ArgumentParser(description='Graph Database Cloud Benchmarking Suite for SNAP Pokec')
    parser.add_argument('--services', nargs='+', default=['all'], help='Services to benchmark: cognodb auradb memgraph surrealdb (or surreal) arangodb (or arango)')
    parser.add_argument('--edges', type=int, default=100000, help='Number of relationships to sample from Pokec dataset (default: 100,000)')
    parser.add_argument('--iterations', type=int, default=100, help='Number of query iterations')
    parser.add_argument('--results-dir', type=str, default='results', help='Directory to save benchmark metrics and charts')
    parser.add_argument('--apply-cpu-throttling', type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=True, help='Apply CPU duty-cycle throttling regulator (default: True)')
    parser.add_argument('--no-cpu-throttling', action='store_false', dest='apply_cpu_throttling', help='Disable CPU duty-cycle throttling regulator')
    args = parser.parse_args()

    nodes, edges, estimated_bytes = generate_benchmark_dataset(num_edges=args.edges)
    ResourceCapEnforcer.enforce_storage_limit(estimated_bytes)

    target_services = ['cognodb', 'auradb', 'memgraph', 'surrealdb', 'arangodb'] if 'all' in args.services else args.services

    csv_path = os.path.join(args.results_dir, 'benchmark_results_matrix.csv')
    existing_df = None
    if os.path.exists(csv_path) and 'all' not in args.services:
        try:
            existing_df = pd.read_csv(csv_path)
            print(f"Loaded existing results matrix from '{csv_path}' ({len(existing_df)} platforms found).")
        except Exception as e:
            print(f"Warning: Could not read existing results matrix: {e}")

    new_results = []
    for db_key in target_services:
        res = run_benchmark_for_adapter(db_key, nodes, edges, iterations=args.iterations, apply_cpu_throttling=args.apply_cpu_throttling)
        if res:
            new_results.append(res)

    if new_results or existing_df is not None:
        if new_results:
            new_df = pd.DataFrame(new_results)
            if existing_df is not None and not existing_df.empty:
                new_platforms = set(new_df['platform'].tolist())
                existing_df = existing_df[~existing_df['platform'].isin(new_platforms)]
                df = pd.concat([existing_df, new_df], ignore_index=True)
            else:
                df = new_df
        else:
            df = existing_df

        print("\n" + "=" * 80)
        print("                  PDF-COMPLIANT BENCHMARK RESULTS MATRIX")
        print("=" * 80)
        print(tabulate(df, headers='keys', tablefmt='grid'))

        os.makedirs(args.results_dir, exist_ok=True)
        df.to_csv(csv_path, index=False)

        generate_result_charts(df, results_dir=args.results_dir)

if __name__ == '__main__':
    main()
