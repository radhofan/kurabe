import os
import sys
import time
from dotenv import load_dotenv

load_dotenv()

MAX_RAM_MB = 512
MAX_STORAGE_GB = 1.0
TARGET_VCPU = 0.25

# 1. CognoDB Cloud
COGNODB_URI = os.getenv('COGNODB_URI', 'bolt+s://db.cognodb.cloud:7687')
COGNODB_USER = os.getenv('COGNODB_USER', 'cognodb')
COGNODB_PASSWORD = os.getenv('COGNODB_PASSWORD', '')

# 2. Neo4j AuraDB Cloud
AURADB_URI = os.getenv('AURADB_URI', 'neo4j+s://db.databases.neo4j.io')
AURADB_USER = os.getenv('AURADB_USER', 'neo4j')
AURADB_PASSWORD = os.getenv('AURADB_PASSWORD', '')

# 3. Memgraph Cloud
MEMGRAPH_URI = os.getenv('MEMGRAPH_URI', 'bolt+s://db.memgraph.cloud:7687')
MEMGRAPH_USER = os.getenv('MEMGRAPH_USER', 'memgraph')
MEMGRAPH_PASSWORD = os.getenv('MEMGRAPH_PASSWORD', '')

# 4. SurrealDB Cloud
SURREALDB_URI = os.getenv('SURREALDB_URI', 'https://db.surrealdb.cloud')
SURREALDB_USER = os.getenv('SURREALDB_USER', 'root')
SURREALDB_PASSWORD = os.getenv('SURREALDB_PASSWORD', '')
SURREALDB_NS = os.getenv('SURREALDB_NS', 'benchmark')
SURREALDB_DB = os.getenv('SURREALDB_DB', 'benchmark')

# 5. ArangoDB Cloud (Oasis)
ARANGODB_URI = os.getenv('ARANGODB_URI', 'https://db.arangodb.cloud:8529')
ARANGODB_USER = os.getenv('ARANGODB_USER', 'root')
ARANGODB_PASSWORD = os.getenv('ARANGODB_PASSWORD', '')
ARANGODB_DATABASE = os.getenv('ARANGODB_DATABASE', 'benchmark')


class ResourceCapEnforcer:
    """
    Code-level resource capping for cloud databases:
    - RAM Cap: Enforces strict 512 MB limit on data buffers & batch memory payload.
    - CPU Cap: Programmatically limits effective query duty-cycle to 0.25 vCPU.
    - Storage Cap: Programmatically verifies and restricts total database storage to <= 1.0 GB.
    """
    @staticmethod
    def enforce_ram_limit(data_bytes):
        max_bytes = MAX_RAM_MB * 1024 * 1024
        if data_bytes > max_bytes:
            raise MemoryError(
                f"RAM Limit Exceeded! Current payload size ({data_bytes / (1024**2):.2f} MB) "
                f"exceeds strict fairness limit of {MAX_RAM_MB} MB."
            )

    @staticmethod
    def enforce_storage_limit(storage_bytes):
        max_bytes = MAX_STORAGE_GB * 1024 * 1024 * 1024
        if storage_bytes > max_bytes:
            raise ValueError(
                f"Storage Limit Exceeded! Estimated storage footprint ({storage_bytes / (1024**3):.2f} GB) "
                f"exceeds maximum allowed limit of {MAX_STORAGE_GB} GB."
            )


class CpuFairnessRegulator:
    """
    Programmatic 0.25 vCPU cap regulator.
    CognoDB Cloud provides 0.5 burst vCPU while other cloud free tiers are capped differently.
    Calculates inter-query throttling to cap effective CPU usage strictly at 0.25 vCPU for all queries.
    """
    def __init__(self, platform_vcpu=0.25, target_vcpu=TARGET_VCPU, enabled=True):
        self.platform_vcpu = platform_vcpu
        self.target_vcpu = target_vcpu
        self.enabled = enabled
        self.ratio = target_vcpu / platform_vcpu if platform_vcpu > 0 else 1.0

    def throttle(self, query_duration_sec):
        if not self.enabled or query_duration_sec <= 0:
            return
        if self.ratio < 1.0:
            sleep_sec = query_duration_sec * ((1.0 / self.ratio) - 1.0)
            time.sleep(sleep_sec)
