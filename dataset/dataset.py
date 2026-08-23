import os
import sys
import gzip
import json
from config import ResourceCapEnforcer

def load_snap_pokec_dataset(rel_file='dataset/soc-pokec/soc-pokec-relationships.txt', prof_file='dataset/soc-pokec/soc-pokec-profiles.txt', target_relationships=100000):
    """
    Parses official SNAP soc-Pokec dataset files located in dataset/soc-pokec/ directory.
    Defaults to 100,000 relationships.
    """
    rel_path = rel_file if os.path.exists(rel_file) else (rel_file + '.gz' if os.path.exists(rel_file + '.gz') else None)
    prof_path = prof_file if os.path.exists(prof_file) else (prof_file + '.gz' if os.path.exists(prof_file + '.gz') else None)

    if not rel_path:
        raise FileNotFoundError(
            f"SNAP Pokec relationships file '{rel_file}' not found in dataset/soc-pokec/ directory!\n"
            f"Expected file: dataset/soc-pokec/soc-pokec-relationships.txt"
        )

    edges = []
    nodes_set = set()

    open_rel = gzip.open if rel_path.endswith('.gz') else open
    print(f"Reading SNAP Pokec dataset from {rel_path} ({target_relationships:,} target relationships)...")
    with open_rel(rel_path, 'rt', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if not line or line.startswith('#'):
                continue
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                try:
                    src = int(parts[0])
                    dst = int(parts[1])
                    edges.append({'source': src, 'target': dst, 'weight': 1.0})
                    nodes_set.add(src)
                    nodes_set.add(dst)
                    if len(edges) >= target_relationships:
                        break
                except ValueError:
                    continue

    profiles_map = {}
    if prof_path:
        open_prof = gzip.open if prof_path.endswith('.gz') else open
        print(f"Reading SNAP Pokec profiles from {prof_path} for {len(nodes_set):,} connected nodes...")
        with open_prof(prof_path, 'rt', encoding='utf-8', errors='ignore') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 1:
                    try:
                        user_id = int(parts[0])
                        if user_id in nodes_set:
                            gender = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                            region = parts[3].strip() if len(parts) > 3 and parts[3].strip() else 'zilinsky kraj, zilina'
                            age = int(parts[6]) if len(parts) > 6 and parts[6].isdigit() else 25
                            profiles_map[user_id] = {
                                'id': user_id,
                                'name': f'pokec_user_{user_id}',
                                'gender': gender,
                                'region': region,
                                'age': age
                            }
                    except ValueError:
                        continue

    nodes = []
    for nid in nodes_set:
        if nid in profiles_map:
            nodes.append(profiles_map[nid])
        else:
            nodes.append({
                'id': nid,
                'name': f'pokec_user_{nid}',
                'gender': 0,
                'region': 'zilinsky kraj, zilina',
                'age': 25
            })

    nodes_json = json.dumps(nodes)
    edges_json = json.dumps(edges)
    estimated_bytes = len(nodes_json) + len(edges_json)

    ResourceCapEnforcer.enforce_ram_limit(sys.getsizeof(nodes_json) + sys.getsizeof(edges_json))
    ResourceCapEnforcer.enforce_storage_limit(estimated_bytes)

    print(f"SNAP Pokec dataset loaded: {len(nodes):,} nodes, {len(edges):,} relationships ({estimated_bytes / (1024 * 1024):.2f} MB)")
    return nodes, edges, estimated_bytes


def generate_benchmark_dataset(num_nodes=50000, num_edges=100000, seed=42):
    return load_snap_pokec_dataset(target_relationships=num_edges)
