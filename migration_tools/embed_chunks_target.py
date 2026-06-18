"""
Embed every :Chunk in the TARGET Neo4j database with the Jina v5 nano model
and persist the vectors (plus provenance metadata) back onto each node.

Hardware optimization and the optimal batching configuration are lifted directly
from benchmark_jina_embeddings_batching_chunks_only_gpu.py:

    Processing Group Configuration: [Batch Size: 32]
     -> Velocity:  ~32.35 chunks / second
     🎯 Estimated full dataset completion (23,472 chunks): ~12 minutes

Each embedded chunk receives three properties:
    embedding        : List[float]  (the 512-dim vector)
    embed_model_name : str          (the model that produced the vector)
    embed_dim        : int          (the vector dimensionality)
"""

import os
import time
import logging
import warnings
from pathlib import Path

import torch
import numpy as np
from dotenv import load_dotenv
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

# -------------------------------------------------------------------------
# 0. Log Cleanliness & Warning Filters
# -------------------------------------------------------------------------
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=SyntaxWarning)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)

# -------------------------------------------------------------------------
# 1. Configuration & Connection Setup
# -------------------------------------------------------------------------
# Load credentials from migration_tools/.env (same directory as this file).
# Writes to the TARGET (migrated) database.
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

NEO4J_URI = os.environ["TARGET_NEO4J_URI"]
NEO4J_USER = os.environ["TARGET_NEO4J_USER"]
NEO4J_PASSWORD = os.environ["TARGET_NEO4J_PASSWORD"]

MODEL_ID = "jinaai/jina-embeddings-v5-text-nano"
EMBED_DIM = 512               # Matches the 512-dimension database vector schema
ENCODE_BATCH_SIZE = 32        # Best throughput configuration from the GPU benchmark
WRITE_BATCH_SIZE = 1_000      # Nodes written back to Neo4j per transaction

# -------------------------------------------------------------------------
# 2. Pull chunks that still need an embedding
# -------------------------------------------------------------------------
print("⚡ Connecting to TARGET Neo4j to pull chunks for embedding...")
fetch_query = """
MATCH (c:Chunk)
WHERE c.text IS NOT NULL AND c.embedding IS NULL
RETURN elementId(c) AS id, c.text AS text
"""

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

with driver.session() as session:
    records = list(session.run(fetch_query))

node_ids = [r["id"] for r in records]
raw_texts = [r["text"] for r in records]

if not raw_texts:
    print("✅ No chunks require embedding (all :Chunk nodes already have c.embedding). Exiting.")
    driver.close()
    raise SystemExit(0)

print(
    f" Ready. Loaded {len(raw_texts)} chunks "
    f"(Avg chars: {np.mean([len(t) for t in raw_texts]):.1f})."
)

# -------------------------------------------------------------------------
# 3. Dynamic Model Optimization per Hardware Layer
# -------------------------------------------------------------------------
print(f"\n⚙️ Initializing {MODEL_ID} via Sentence-Transformers Engine...")

device = "cuda" if torch.cuda.is_available() else "cpu"
config_kwargs = {}

if device == "cuda":
    major_capability = torch.cuda.get_device_capability()[0]
    print(f"🚀 CUDA Detected! GPU Compute Capability: {torch.cuda.get_device_capability()}")

    if major_capability >= 8:
        model_dtype = torch.bfloat16
        config_kwargs["_attn_implementation"] = "flash_attention_2"
        print("  -> Ampere+ Architecture found: Enabled Flash Attention 2 & Bfloat16 precision.")
    else:
        model_dtype = torch.float16
        config_kwargs["_attn_implementation"] = "sdpa"
        print("  -> Pre-Ampere (T4/Turing) found: Forcing Float16 precision via PyTorch SDPA.")
else:
    model_dtype = torch.float32
    config_kwargs["_attn_implementation"] = "sdpa"
    print("💻 No GPU environment found. Running on pure CPU execution.")

model = SentenceTransformer(
    MODEL_ID,
    trust_remote_code=True,
    device=device,
    model_kwargs={"dtype": model_dtype},
    config_kwargs=config_kwargs,
)

# -------------------------------------------------------------------------
# 4. Encode all chunks at the optimal batch size
# -------------------------------------------------------------------------
print(f"\n=== Embedding {len(raw_texts)} chunks @ batch_size={ENCODE_BATCH_SIZE} ===")

# Warmup pass mimicking production constraints exactly
model.encode(
    sentences=raw_texts[:2],
    batch_size=2,
    task="retrieval",
    prompt_name="document",
    truncate_dim=EMBED_DIM,
    show_progress_bar=False,
)

start_time = time.perf_counter()
with torch.inference_mode():
    embeddings = model.encode(
        sentences=raw_texts,
        batch_size=ENCODE_BATCH_SIZE,
        task="retrieval",
        prompt_name="document",
        truncate_dim=EMBED_DIM,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
elapsed = time.perf_counter() - start_time

print(
    f" -> Encoded {len(embeddings)} vectors in {elapsed:.2f}s "
    f"({len(embeddings) / elapsed:.2f} chunks/sec)."
)

# -------------------------------------------------------------------------
# 5. Persist vectors + metadata back onto the chunks
# -------------------------------------------------------------------------
print(f"\n💾 Writing embeddings back to Neo4j (batches of {WRITE_BATCH_SIZE})...")

write_query = """
UNWIND $rows AS row
MATCH (c:Chunk) WHERE elementId(c) = row.id
SET c.embedding = row.embedding,
    c.embed_model_name = $model_name,
    c.embed_dim = $embed_dim
"""

written = 0
with driver.session() as session:
    for start in range(0, len(node_ids), WRITE_BATCH_SIZE):
        end = start + WRITE_BATCH_SIZE
        rows = [
            {"id": node_ids[i], "embedding": embeddings[i].tolist()}
            for i in range(start, min(end, len(node_ids)))
        ]
        session.run(
            write_query,
            rows=rows,
            model_name=MODEL_ID,
            embed_dim=EMBED_DIM,
        )
        written += len(rows)
        print(f"  -> {written}/{len(node_ids)} chunks updated")

driver.close()
print(f"\n✅ Done. Embedded and saved {written} chunks ({EMBED_DIM}-dim, {MODEL_ID}).")
