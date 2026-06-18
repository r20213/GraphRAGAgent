import time
import os
import logging
import warnings
from pathlib import Path

import torch
import numpy as np
from dotenv import load_dotenv
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

# -------------------------------------------------------------------------
# 0. Production Log Cleanliness & Warning Filters
# -------------------------------------------------------------------------
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=SyntaxWarning)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)

# -------------------------------------------------------------------------
# 1. Configuration & Connection Setup
# -------------------------------------------------------------------------
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

NEO4J_URI = os.environ["SOURCE_NEO4J_URI"]
NEO4J_USER = os.environ["SOURCE_NEO4J_USER"]
NEO4J_PASSWORD = os.environ["SOURCE_NEO4J_PASSWORD"]

MODEL_ID = "jinaai/jina-embeddings-v5-text-nano"
TEST_SAMPLE_SIZE = 300  
BATCH_SIZES_TO_PROFILE = [1, 8, 16, 32]  

print("⚡ Connecting to Neo4j to pull real text samples...")
query = "MATCH (c:Chunk) WHERE c.text IS NOT NULL RETURN c.text LIMIT $limit"

with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
    with driver.session() as session:
        result = session.run(query, limit=TEST_SAMPLE_SIZE)
        raw_texts = [row["c.text"] for row in result]

if not raw_texts:
    raise ValueError("Database returned 0 records. Check your graph label definitions.")

print(f" Ready. Loaded {len(raw_texts)} real chunks (Avg chars: {np.mean([len(t) for t in raw_texts]):.1f}).")

# -------------------------------------------------------------------------
# 2. Dynamic Model Optimization per Hardware Layer
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
    print("💻 No GPU environment found. Benchmarking using pure CPU execution.")
    model_dtype = torch.float32
    config_kwargs["_attn_implementation"] = "sdpa"

model = SentenceTransformer(
    MODEL_ID,
    trust_remote_code=True,
    device=device,
    model_kwargs={"dtype": model_dtype},
    config_kwargs=config_kwargs,
)

# -------------------------------------------------------------------------
# 3. Execution Benchmarking Engine
# -------------------------------------------------------------------------
print("\n=== Commencing Local Vector Throughput Test ===")

# Warmup pass mimicking production constraints exactly
model.encode(
    sentences=raw_texts[:2], 
    batch_size=2, 
    task="retrieval", 
    prompt_name="document", 
    truncate_dim=512, 
    show_progress_bar=False
)

for batch_size in BATCH_SIZES_TO_PROFILE:
    print(f"\nProcessing Group Configuration: [Batch Size: {batch_size}]")
    
    start_time = time.perf_counter()
    
    with torch.inference_mode():
        embeddings = model.encode(
            sentences=raw_texts,
            batch_size=batch_size,
            task="retrieval",
            prompt_name="document",
            truncate_dim=512,  # Added back to match your 512-dimension database schema
            show_progress_bar=False
        )
        
    end_time = time.perf_counter()
    elapsed_seconds = end_time - start_time
    processed_count = len(raw_texts)
    chunks_per_second = processed_count / elapsed_seconds
    
    estimated_total_minutes = (23472 / chunks_per_second) / 60

    print(f" -> Processed: {processed_count} samples in {elapsed_seconds:.2f}s")
    print(f" -> Velocity:  {chunks_per_second:.2f} chunks / second")
    print(f" 🎯 Estimated full dataset completion (23,472 chunks): {estimated_total_minutes:.2f} minutes")
    
    del embeddings
    if device == "cuda":
        torch.cuda.empty_cache()

print("\nProfiling Complete. Pick the batch size configuration that yielded the highest chunks/sec!")