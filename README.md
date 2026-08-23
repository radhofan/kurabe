# Benchmarking CognoDB vs. other Graph Managed Databases

In this repo, we created a reproducible benchmark suite comparing CognoDB Cloud against managed graph database cloud platforms (Neo4j AuraDB, Memgraph Cloud, ArangoDB Cloud, and SurrealDB Cloud) using identical datasets and query workloads under strict resource parity.

## Provider Selection

This benchmark suite evaluates CognoDB Cloud against four managed graph database platforms. The goal is a reproducible performance assessment across data loading, graph traversals, lookups, aggregations, and concurrent read/write throughput.

### Database Selection Criteria

Our selection criteria came down to matching free-tier resource capabilities as closely as possible to CognoDB's free tier, balancing technology similarity with architectural contrast:

- **Similar Technology Stack**: We chose [Neo4j AuraDB](https://neo4j.com/cloud/platform/auradb/) and [Memgraph](https://memgraph.com/) to compare against native Cypher/Bolt protocol implementations.
- **Different Architectural Methods**: We included multi-model and document-graph engines like [ArangoDB](https://www.arangodb.com/) to contrast native graph engines against alternative storage methods, and also since a lot of other studies tries to benchmark ArangoDB againts native graph a lot.
- **Seldom-Used Comparison**: To enrich data analysis, we also decided to pick a less popular provider and technology like [SurrealDB](https://surrealdb.com/) was specifically included as a less common multi-model database to evaluate how modern multi-model engines handle graph workloads and compare againts native one.

Our selection criteria also takes consideration from published benchmarks and comparative studies:

- [Benchmarking Graph Databases: Neo4j vs Amazon Neptune vs ArangoDB](https://www.researchgate.net/publication/389357088_Benchmarking_Graph_Databases_Neo4j_vs_Amazon_Neptune_vs_ArangoDB)
- [ArcadeDB Performance Benchmarks](https://arcadedb.com/benchmarks.html)
- [PuppyGraph: ArangoDB vs Neo4j Benchmark Analysis](https://www.puppygraph.com/blog/arangodb-vs-neo4j)

### Selected Databases

Our final choices came down to the following four platforms:

1. [Neo4j AuraDB](https://neo4j.com/cloud/platform/auradb/)
2. [Memgraph](https://memgraph.com/)
3. [ArangoDB](https://www.arangodb.com/)
4. [SurrealDB](https://surrealdb.com/)

### Overview

Here we provide overview of proposed cloud providers underlying technology to get a better understanding of what we are actually comparing here.

| Provider Name       | Query Language | DB Engine                    | Network Protocol          |
| :------------------ | :------------- | :--------------------------- | :------------------------ |
| **CognoDB Cloud**   | Cypher         | Native Graph Engine          | Bolt (`bolt+s`)           |
| **Neo4j AuraDB**    | Cypher         | Native Graph Engine          | Bolt (`neo4j+s`)          |
| **Memgraph Cloud**  | Cypher         | In-Memory Native Graph       | Bolt (`bolt+s`)           |
| **ArangoDB Oasis**  | AQL            | Multi-Model (Document/Graph) | HTTP/REST (`https`)       |
| **SurrealDB Cloud** | SurrealQL      | Multi-Model (Document/Graph) | HTTP/WebSockets (`https`) |

We understand that different technologies produce different speed because of their purposes, however thats the exact reason we are benchmarking it here.

## Hardware & Environment

All providers were used by their lowest/free tier available plan. All regions are picked to the same US-EAST configuration to ensure same travel latency and since all provider happen to have that available.

Although some hardware specs are not exposed by the provider, they should still yield similar performance while we also did some programmatic resource capping for further fairness strictness down below.

### Advertised Provider Specs

| Database Platform   | vCPU             | RAM            | Storage Limit  |
| :------------------ | :--------------- | :------------- | :------------- |
| **CognoDB Cloud**   | 0.5 vCPU (burst) | 512 MB         | 1.0 GB         |
| **Neo4j AuraDB**    | Not advertised   | Not advertised | Not advertised |
| **Memgraph Cloud**  | 1.0 vCPU         | 2.0 GB         | Not advertised |
| **ArangoDB Oasis**  | 0.25 vCPU        | 512 MB         | 1.0 GB         |
| **SurrealDB Cloud** | 0.25 vCPU        | 512 MB         | 40 GB          |

### Code-Level Resource Enforcement for Fairness

We tried our best to chose matching the specs as much as possible, but to the best of our knowledge, these are the closes possible resource matching provider there is to CognoDB free tier, in the end because cloud providers offer different default specs on their free tiers as reported per the table, running benchmarks directly on out-of-the-box hardware would yield an unfair comparison.

To eliminate hardware advantages, we try our best to runner programmatically cap all platforms at runtime to match performance as much as possible:

- **RAM & Storage Capping**: `ResourceCapEnforcer` programmatically verifies in-memory payload buffers (capped at 512 MB) and total estimated disk footprints (capped at 1.0 GB) before executing workloads. This is reliable because client dataset payload sizes and batch memory buffers are strictly measured and bounded before execution, ensuring no database exceeds free-tier memory or storage limits.

- **CPU Duty-Cycle Regulation**: `CpuFairnessRegulator` inserts inter-query sleep delays based on measured query execution times to equalize query frequency across providers. Note that client-side throttling regulates query issue rates rather than enforcing a true OS-level container CPU cap on the remote server host. For readers who prefer unthrottled raw provider performance, this regulator can be toggled off via code (`apply_cpu_throttling=False`).

Hence readers need to take this comparison with a grain of salt, **the biggest factor is the CPU power** from each provider because we cannot reliably enforce OS level strictness, for RAM and storage we can cap it effectively though.

## Dataset & Queries

### Dataset

- **Source**: SNAP soc-Pokec social network graph sample.
- **Scale**: 100,000 sampled relationships (edges) and 19,103 connected nodes.
- **Node Attributes**: `id` (integer), `name` (string), `gender` (integer), `region` (string), `age` (integer).

### Indexing

- **Primary Index**: Range/hash index on `Person(id)`.
- **Composite Index**: Compound index on `Person(age, region)`.

### Query Workloads

- **Data Ingest**: Bulk loading 19,103 nodes and 100,000 edges. Measured in nodes/sec, edges/sec, and total wall-clock time.
- **Graph Traversals**: 1-hop, 2-hop, and 3-hop query latency (p50 and p95) sampled across 100 random starting nodes.
- **Point Lookups**: Key lookup by node `id`.
- **Filtered Lookups**: Range and equality filter matching `age` and `region`.
- **Aggregations**: Group-by aggregation (`count(p)` and `avg(p.age)` grouped by `region`).
- **Mixed Concurrency**: 80% read / 20% write workload evaluated across 1, 10, and 40 concurrent client threads.
- **Query Warmup**: Prior to recording latencies, `benchmark.py` executes an explicit warmup pass across all query adapters to warm up engine query planners and page caches. All reported p50 and p95 latency percentiles reflect post-warmup query performance. Future works can be done to provide cold start options also for further comparison.

### Batching

Each adapter employs its provider's native equivalent bulk batching mechanism to achieve fair data loading parity with Cypher-based engines.

For Neo4j-based native graph databases (CognoDB, AuraDB, and Memgraph), batching uses parameterized Cypher queries over the official Bolt driver with the `UNWIND` clause (`UNWIND $batch AS row CREATE (:Person {id: row.id, ...})` for nodes and `UNWIND $batch AS row MATCH (src:Person {id: row.source}), (dst:Person {id: row.target}) CREATE (src)-[:CONNECTED_TO]->(dst)` for edges). The database engine unrolls the array inside a single server-side transaction.

For ArangoDB, batching uses the native HTTP REST bulk import API (`/api/import?collection=person&type=documents`). This is ArangoDB's standard bulk ingestion method equivalent to Cypher batching; rather than executing AQL queries, it posts a raw JSON array of documents straight to ArangoDB's C++ import endpoint, bypassing query parsing and writing objects directly into document and edge storage collections.

For SurrealDB, batching uses concatenated multi-statement SQL payloads sent over HTTP (`/sql`), which is SurrealDB's standard equivalent batching method. The adapter joins multiple statements into a single multi-line string (`CREATE person:1 SET ...; RELATE person:1->connected_to->person:2 SET weight=1.0;`) and posts the combined payload to the database endpoint, where SurrealDB parses and executes the batch sequentially within an HTTP transaction.

To ensure fair and reliable data loading across platforms:

- **Indexing Order**: All adapters follow the exact same loading sequence: ingest nodes first -> build and sync indexes second -> ingest relationships third. Creating indexes after node ingestion prevents index maintenance penalties during initial record creation across all engines.

- **Batch Size Configuration**: Ingestion uses provider-optimal batch tuning. AuraDB, Memgraph, ArangoDB, and SurrealDB ingest nodes and relationships in batches of 1,000 items.

<!-- CognoDB ingests nodes at 1,000 items per batch, but relationship ingestion uses smaller sub-batches of 250 items (`edge_batch_size = 250`). This sub-batching prevents cloud TCP connection drops on CognoDB's free tier when processing large Cypher transaction payloads over remote endpoints. We know that this is a major limitation, but based on our experiments, we could not reliably run it without getting broken TCP connections. -->

### Benchmark values

The benchmark execution script (`benchmark.py`) and database reset script (`rebuild.py`) accept the following command-line parameters:

| Script         | Flag                   | Type   | Default   | Description                                                                               |
| :------------- | :--------------------- | :----- | :-------- | :---------------------------------------------------------------------------------------- |
| `benchmark.py` | `--services`           | list   | `all`     | Target databases to benchmark (`cognodb`, `auradb`, `memgraph`, `surrealdb`, `arangodb`). |
| `benchmark.py` | `--edges`              | int    | `100000`  | Number of relationships to sample from the SNAP Pokec dataset.                            |
| `benchmark.py` | `--iterations`         | int    | `100`     | Number of query iterations per read workload after warmup.                                |
| `benchmark.py` | `--results-dir`        | string | `results` | Output directory for CSV metrics matrix and generated PNG charts.                         |
| `benchmark.py` | `--apply-cpu-throttling` | bool   | `True`    | Toggles inter-query CPU duty-cycle throttling (`apply_cpu_throttling=False` disables it). |
| `rebuild.py`   | `--services`           | list   | `all`     | Target databases to wipe and repopulate.                                                  |
| `rebuild.py`   | `--nodes`              | int    | `20000`   | Target node count to populate during database rebuild.                                    |
| `rebuild.py`   | `--edges`              | int    | `100000`  | Target relationship count to populate during database rebuild.                            |
| `rebuild.py`   | `--batch-size`         | int    | `1000`    | Batch size for bulk insertion operations.                                                 |

Note that we use default of 100K minimal relationship. This will still take about 25 minutes of running all services and getting the results.

## Results

### Results Matrix

| Metric                             | CognoDB           | AuraDB         | Memgraph        | SurrealDB           | ArangoDB        |
| :--------------------------------- | :---------------- | :------------- | :-------------- | :------------------ | :-------------- |
| **Load Time (sec)**                | 433.49            | 12.47          | 55.52           | 307.02              | 51.57           |
| **Ingest Nodes/sec**               | 114.6             | 3,985.5        | 894.9           | 161.8               | 963.4           |
| **Ingest Edges/sec**               | 230.7             | 8,021.8        | 1,801.1         | 325.7               | 1,939.0         |
| **1-Hop p50 / p95 (ms)**           | 256.52 / 443.56   | 23.45 / 28.57  | 269.01 / 410.27 | 1,304.94 / 2,031.93 | 259.28 / 333.79 |
| **2-Hop p50 / p95 (ms)**           | 272.73 / 545.52   | 23.54 / 29.49  | 276.82 / 357.34 | 1,158.61 / 1,300.57 | 261.48 / 346.63 |
| **3-Hop p50 / p95 (ms)**           | 286.39 / 511.00   | 22.57 / 27.42  | 300.62 / 350.06 | 1,377.56 / 1,992.83 | 255.18 / 475.01 |
| **Point Lookup p50 / p95 (ms)**    | 269.68 / 364.24   | 24.95 / 34.45  | 277.90 / 365.42 | 1,199.01 / 1,829.44 | 262.52 / 405.02 |
| **Filtered Lookup p50 / p95 (ms)** | 280.74 / 1,410.51 | 24.56 / 57.14  | 305.28 / 360.08 | 1,559.70 / 1,966.50 | 263.96 / 349.32 |
| **Aggregation p50 / p95 (ms)**     | 425.57 / 1,255.69 | 45.25 / 61.71  | 271.39 / 341.46 | 1,613.52 / 1,833.18 | 306.70 / 437.11 |
| **Mixed 1 Client (QPS)**           | 0.4               | 41.0           | 3.0             | 0.8                 | 3.6             |
| **Mixed 10 Clients (QPS)**         | 8.2               | 315.4          | 28.0            | 6.0                 | 34.4            |
| **Mixed 40 Clients (QPS)**         | 30.0              | 203.8          | 128.8           | 8.0                 | 105.8           |

### Performance Charts

#### Data Loading Ingest Throughput

![Ingest Throughput](results/ingest_throughput.png)

#### Traversal Query Latencies (1-Hop, 2-Hop, 3-Hop)

![Traversal Latencies](results/traversal_latencies.png)

#### Lookup and Aggregation Latencies

![Lookup Aggregation Latencies](results/lookup_aggregation_latencies.png)

#### Mixed Workload Concurrency Sweep (80% Read / 20% Write)

![Mixed Workload Concurrency](results/mixed_workload_concurrency.png)

## Engineering Deep Dive: Why the Numbers Differ

### Data Ingest Throughput

- **AuraDB and ArangoDB** achieved fast bulk data loading times of 12.47s (8,021.8 edges/sec) and 51.57s (1,939.0 edges/sec) respectively. Memgraph completed data loading in 55.52s (1,801.1 edges/sec).
- **SurrealDB** required 307.02s (325.7 edges/sec) due to document table mapping and SQL statement processing overhead during bulk insertion.
- **CognoDB** required 433.49s (230.7 edges/sec). Ingestion used batching with reconnect handling under cloud socket pressure, plus Cypher endpoint lookup overhead per relation statement.

### Traversal Performance & Tail Latencies

- **AuraDB** delivered ~22 to 23ms p50 across 1-hop, 2-hop, and 3-hop queries with low tail latencies (p95 under 30ms) due to pointer-chaining indexless adjacency.
- **CognoDB** maintained median latencies between 256.52ms and 286.39ms p50 across 1-hop, 2-hop, and 3-hop queries, with p95 tail latencies bounded between 443.56ms and 545.52ms.
- **ArangoDB** demonstrated consistent median latencies (~255 to 261ms p50) across all hop depths with p95 bounded between 333.79ms and 475.01ms.
- **Memgraph** logged median traversals between 269.01ms (1-hop) and 300.62ms (3-hop) with p95 tail latencies between 350.06ms and 410.27ms.
- **SurrealDB** averaged between 1,158.61ms and 1,377.56ms p50 across hop depths (with 1-hop p95 reaching 2,031.93ms) because graph traversals execute via relational table joins under its engine.

### Lookups & Aggregations

- **Point Lookups**: AuraDB completed point lookups in 24.95ms p50 (34.45ms p95). ArangoDB (262.52ms p50), CognoDB (269.68ms p50), and Memgraph (277.90ms p50) were bound primarily by network TLS transport to US East endpoints. SurrealDB averaged 1,199.01ms p50.
- **Filtered Lookups**: AuraDB led at 24.56ms p50 (57.14ms p95). ArangoDB (263.96ms p50) and Memgraph (305.28ms p50) maintained tight tail latencies (~349ms and ~360ms p95), while CognoDB (280.74ms p50) experienced a p95 tail latency spike of 1,410.51ms on complex filter evaluations. SurrealDB logged 1,559.70ms p50.
- **Aggregations**: AuraDB led at 45.25ms p50 (61.71ms p95). Memgraph and ArangoDB logged 271.39ms and 306.70ms p50. CognoDB recorded 425.57ms p50 (1,255.69ms p95) due to label scanning under CPU duty-cycle regulation. SurrealDB took 1,613.52ms p50.

### Concurrency Scaling (80% Read / 20% Write)

- **AuraDB** delivered 41.0 QPS at 1 client, peaked at 315.4 QPS at 10 clients, and registered 203.8 QPS at 40 clients under connection pool constraints.
- **Memgraph** scaled from 3.0 QPS (1 client) to 28.0 QPS (10 clients) and 128.8 QPS (40 clients).
- **ArangoDB** scaled from 3.6 QPS (1 client) to 34.4 QPS (10 clients) and 105.8 QPS (40 clients).
- **CognoDB** scaled from 0.4 QPS at 1 client to 8.2 QPS at 10 clients and 30.0 QPS at 40 clients under concurrent write-lock scheduling.
- **SurrealDB** scaled from 0.8 QPS (1 client) to 6.0 QPS (10 clients) and 8.0 QPS (40 clients).

## Threats to Validity

- **CPU power**: Probably the because factor of all, based on our knowledge, we could not find enough reliable free providers that offers the exact same amount of CPU cores like free tier CognoDB, hence we tried our best using programmatic approaches although less favourable. We do provide the option of turning `apply_cpu_throttling` on or off if the reader wishes to see further comparison.
- **Network Latency Impact**: All cloud instances were provisioned in the same region (US East) and tested over a stable connection to minimize latency variance as much as possible. However, network transit still plays a role in overall query execution times across remote cloud endpoints.
- **Query Dialect Variance**: Cypher was used for CognoDB, AuraDB, and Memgraph; AQL for ArangoDB; and SurrealQL for SurrealDB.
- **Variance Testing**: Due to time limit assigned by the task (2 days), we were not simply able to run multiple times and get the variance result across multiple runs. Readers who want to reproduce this experiment is **strongly advised to run multiple times** to get reliable result. We provided option in code to run reach provoder multiple times, default is one run only.
- **Dataset Generalization**: This study uses only the soc-pokec social dataset, to draw any meaningful conclusions, we consider it is best to add another dataset in the future which is easily doable via the modular code we designed.

## Quickstart

### Prerequisites

- Python 3.9+
- Cloud instances provisioned for CognoDB, Neo4j AuraDB, Memgraph, ArangoDB, and SurrealDB.

### Setup

1. Clone the repository and install dependencies:

   ```bash
   git clone https://github.com/radhofan/cognodb-benchmarking.git
   cd cognodb-benchmarking
   pip install -r requirements.txt
   ```

2. Get the dataset

   We did not commit the dataset because it is too huge for github, here you can download it [Soc-Pokec dataset](https://snap.stanford.edu/data/soc-Pokec.html) and get these two files (soc-pokec-relationships.txt.gz and
   soc-pokec-profiles.txt.gz) and put it in `dataset/soc-pokec`.

3. Create account and login to all providers and configure environment credentials in `.env`:

   ```env
   # CognoDB Cloud
   COGNODB_URI=bolt+s://<instance-id>.databases.cognodb.cloud:7687
   COGNODB_USER=cognodb
   COGNODB_PASSWORD=your_cognodb_password

   # Neo4j AuraDB Cloud
   AURADB_URI=neo4j+s://<instance-id>.databases.neo4j.io
   AURADB_USER=neo4j
   AURADB_PASSWORD=your_auradb_password

   # Memgraph Cloud
   MEMGRAPH_URI=bolt+s://<instance-id>.memgraph.cloud:7687
   MEMGRAPH_USER=memgraph
   MEMGRAPH_PASSWORD=your_memgraph_password

   # SurrealDB Cloud
   SURREALDB_URI=https://<instance-id>.surrealdb.cloud
   SURREALDB_USER=root
   SURREALDB_PASSWORD=your_surrealdb_password
   SURREALDB_NS=benchmark
   SURREALDB_DB=benchmark

   # ArangoDB Cloud (Oasis)
   ARANGODB_URI=https://<instance-id>.arangodb.cloud:8529
   ARANGODB_USER=root
   ARANGODB_PASSWORD=your_arangodb_password
   ARANGODB_DATABASE=benchmark

   # Resource Limits & Fairness Constraints
   MAX_RAM_MB=512
   MAX_STORAGE_GB=1.0
   TARGET_VCPU=0.25
   COGNODB_BURST_VCPU=0.5
   ```

4. Run the complete benchmark suite (this clears and rebuild db also):

   ```bash
   python benchmark.py
   ```

5. Clear and rebuild databases only:
   ```bash
   python rebuild.py
   ```
