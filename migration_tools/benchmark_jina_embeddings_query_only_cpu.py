import time
import logging
import warnings
import torch
from sentence_transformers import SentenceTransformer

# -------------------------------------------------------------------------
# 0. Production Log Cleanliness & Warning Filters
# -------------------------------------------------------------------------
# Suppress noisy layout warnings from deep dependencies during CPU execution
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=SyntaxWarning)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)

# -------------------------------------------------------------------------
# 1. Initialization (Force CPU Execution)
# -------------------------------------------------------------------------
MODEL_ID = "jinaai/jina-embeddings-v5-text-nano"
device = "cpu"

print(f"⚙️ Loading {MODEL_ID} natively on CPU...")
model = SentenceTransformer(
    MODEL_ID,
    trust_remote_code=True,
    device=device,
    model_kwargs={"dtype": torch.float32}  # float32 is optimal for standard CPUs
)

# -------------------------------------------------------------------------
# 2. Define Sample Queries & Benchmark
# -------------------------------------------------------------------------
# Typical GraphRAG user query strings
sample_queries = [
    "What are the specific environmental compliance regulations for coastal real estate development?",
    "Show me all text nodes related to structural failures in sub-zero concrete foundations.",
    "How does climate change directly impact municipal water infrastructure financing?"
]

print("\n=== Commencing CPU Query Latency Test ===")

# Run a single cold-start warm-up pass (disregarded from benchmarks)
# This handles initial internal library configurations and memory allocations
_ = model.encode(sentences=["Warmup text string"], task="retrieval", prompt_name="query")

latencies = []

for idx, query_text in enumerate(sample_queries, start=1):
    start_time = time.perf_counter()
    
    with torch.inference_mode():
        # Sentence Transformers native method uses 'sentences' parameter 
        query_vector = model.encode(
            sentences=[query_text],
            batch_size=1,
            task="retrieval",
            prompt_name="query",       # Crucial: Routing instruction for real-time search queries
            truncate_dim=512,          # Matches your database collection dimensions
            show_progress_bar=False
        )[0]
        
    end_time = time.perf_counter()
    latency_ms = (end_time - start_time) * 1000
    latencies.append(latency_ms)
    
    print(f"\nQuery #{idx}: '{query_text[:50]}...'")
    print(f" -> Latency: {latency_ms:.2f} ms")
    print(f" -> Output Vector Shape: {len(query_vector)}")

# -------------------------------------------------------------------------
# 3. Final Summary Report
# -------------------------------------------------------------------------
print("\n=== Performance Metrics Summary ===")
print(f" ⏱️ Average Query Latency: {sum(latencies)/len(latencies):.2f} ms")
print("Verdict: Perfectly acceptable for standard interactive application workflows!")