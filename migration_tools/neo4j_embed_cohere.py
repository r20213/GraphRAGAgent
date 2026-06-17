import os
import sys
import time
import cohere
from neo4j import GraphDatabase

# Initialize Clients
COHERE_API_KEY = os.environ.get("COHERE_API_KEY")
NEO4J_URI = os.environ.get("TARGET_NEO4J_URI", "neo4j+s://xxxxxx.databases.neo4j.io")
NEO4J_USER = os.environ.get("TARGET_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("TARGET_NEO4J_PASSWORD", "your-password")

if not COHERE_API_KEY:
    print("❌ Error: COHERE_API_KEY missing from environment.")
    sys.exit(1)

co = cohere.ClientV2(api_key=COHERE_API_KEY)
db_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# 96 is Cohere's optimal max array length per API call envelope
BATCH_SIZE = 96  
# Spacing batches prevents burst-limit clipping on high concurrency
BATCH_DELAY = 2.9  

def fetch_unembedded_chunks(tx):
    query = """
    MATCH (c:Chunk) WHERE c.embedding_cohere IS NULL
    RETURN id(c) AS element_id, c.text AS text
    ORDER BY element_id ASC
    """
    return [dict(record) for record in tx.run(query)]

def write_vectors_to_nodes(tx, batch_data):
    query = """
    UNWIND $rows AS row
    MATCH (c:Chunk) WHERE id(c) = row.element_id
    SET c.embedding_cohere = row.vector
    """
    tx.run(query, rows=batch_data)

def main():
    print("🔍 Fetching target nodes from Neo4j storage...")
    with db_driver.session() as session:
        chunks = session.execute_read(fetch_unembedded_chunks)
        
    total_count = len(chunks)
    print(f"📋 Loaded {total_count:,} items requiring compilation.")
    
    if total_count == 0:
        return print("✅ Graph database vectors are up to date.")

    for i in range(0, total_count, BATCH_SIZE):
        slice_group = chunks[i : i + BATCH_SIZE]
        texts = [item["text"] for item in slice_group]
        
        print(f"🚀 Vectorizing sequence {i:,} to {i + len(slice_group):,}...")
        
        try:
            # Using V2 client method structure targeting English v3 (1024 dimensions)
            response = co.embed(
                    texts=texts,
                    model="embed-v4.0",              # Switch to the newer flagship model
                    input_type="search_document",
                    embedding_types=["float"],
                    output_dimension=1024            # Forces the vector down to 1024 dimensions
                )
            
            write_payload = []
            for idx, vector in enumerate(response.embeddings.float):
                write_payload.append({
                    "element_id": slice_group[idx]["element_id"],
                    "vector": vector
                })
                
            with db_driver.session() as session:
                session.execute_write(write_vectors_to_nodes, write_payload)
                
        except Exception as e:
            print(f"⚠️ Transaction exception caught: {e}. Cooling down...")
            time.sleep(10)
            continue
            
        if i + BATCH_SIZE < total_count:
            time.sleep(BATCH_DELAY)

    print("\n🎉 Complete. Vector indexing applied to Neo4j successfully.")

if __name__ == "__main__":
    try:
        main()
    finally:
        db_driver.close()