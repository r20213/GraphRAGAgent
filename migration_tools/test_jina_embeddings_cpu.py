import time
import os
from pathlib import Path

import torch
import numpy as np
from dotenv import load_dotenv
from neo4j import GraphDatabase
from transformers import AutoTokenizer
from optimum.onnxruntime import ORTModelForFeatureExtraction

# -------------------------------------------------------------------------
# 1. Configuration & Connection Setup
# -------------------------------------------------------------------------
# Load credentials from migration_tools/.env (same directory as this file).
# Uses the SOURCE_* (original) database — not the migrated target.
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

NEO4J_URI = os.environ["SOURCE_NEO4J_URI"]
NEO4J_USER = os.environ["SOURCE_NEO4J_USER"]
NEO4J_PASSWORD = os.environ["SOURCE_NEO4J_PASSWORD"]

MODEL_ID = "jinaai/jina-embeddings-v5-text-nano-retrieval"
TEST_SAMPLE_SIZE = 300  # Number of real chunks pulled to run the benchmark
BATCH_SIZES_TO_PROFILE = [8, 16, 32]  # Profiles performance across various memory scales

print("⚡ Connecting to Neo4j to pull real text samples...")
query = "MATCH (c:Chunk) WHERE c.text IS NOT NULL RETURN c.text LIMIT $limit"

with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
    with driver.session() as session:
        result = session.run(query, limit=TEST_SAMPLE_SIZE)
        # Jina Retrieval expects the formal "Document: " namespace prefix
        raw_texts = [f"Document: {row['c.text']}" for row in result]

if not raw_texts:
    raise ValueError("Database returned 0 records. Ensure your label matches 'Chunk' and property matches '.text'.")

print(f" Ready. Loaded {len(raw_texts)} real chunks (Avg chars: {np.mean([len(t) for t in raw_texts]):.1f}).")

# -------------------------------------------------------------------------
# 2. Initialize Model and Runtime Environments
# -------------------------------------------------------------------------
print("\n⚙️ Initializing Jina-v5-Nano via ONNX Runtime Engine...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)

# Detect if your machine can use hardware acceleration (CUDA/GPU)
device_provider = "CPUExecutionProvider"
if torch.cuda.is_available():
    device_provider = "CUDAExecutionProvider"
    print("🚀 CUDA Detected! Running benchmark using GPU acceleration.")
else:
    print("💻 No GPU environment found. Benchmarking using pure CPU execution.")

model = ORTModelForFeatureExtraction.from_pretrained(
    MODEL_ID,
    subfolder="onnx",
    file_name="model.onnx",
    provider=device_provider,
    trust_remote_code=True,
)

# -------------------------------------------------------------------------
# 3. Execution Benchmarking Engine
# -------------------------------------------------------------------------
print("\n=== Commencing Local Vector Throughput Test ===")

for batch_size in BATCH_SIZES_TO_PROFILE:
    print(f"\nProcessing Group Configuration: [Batch Size: {batch_size}]")
    
    start_time = time.perf_counter()
    processed_count = 0

    for i in range(0, len(raw_texts), batch_size):
        batch = raw_texts[i : i + batch_size]
        
        # Tokenize chunk and push attention masks
        inputs = tokenizer(batch, padding=True, truncation=True, return_tensors="pt")
        
        with torch.no_grad():
            outputs = model(**inputs)
            
        # Jina-v5 Specific Last-Token Pooling Strategy
        last_hidden_state = outputs.last_hidden_state
        sequence_lengths = inputs.attention_mask.sum(dim=1) - 1
        embeddings = last_hidden_state[torch.arange(last_hidden_state.size(0)), sequence_lengths]
        
        processed_count += len(batch)

    end_time = time.perf_counter()
    elapsed_seconds = end_time - start_time
    chunks_per_second = processed_count / elapsed_seconds
    
    # Scale calculation up to your real full count (23,472 chunks)
    estimated_total_minutes = (23472 / chunks_per_second) / 60

    print(f" -> Processed: {processed_count} samples in {elapsed_seconds:.2f}s")
    print(f" -> Velocity:  {chunks_per_second:.2f} chunks / second")
    print(f" 🎯 Estimated full dataset completion (23,472 chunks): {estimated_total_minutes:.2f} minutes")

print("\nProfiling Complete. Pick the batch size configuration that yielded the highest chunks/sec!")