import os
import sys
import cohere

# Ensure your key is exported in your environment: export COHERE_API_KEY="your-key"
COHERE_API_KEY = os.environ.get("COHERE_API_KEY")

if not COHERE_API_KEY:
    print("❌ Error: COHERE_API_KEY is missing from environment variables.")
    sys.exit(1)

# Initialize the v2 client
co = cohere.ClientV2(api_key=COHERE_API_KEY)

# A sample text block matching a typical database chunk layout
paragraph = (
    "GraphRAG combines vector search with knowledge graphs. By using an embedding "
    "model like Cohere embed-v4.0 to index text chunks, and linking those chunks "
    "to structured nodes in Neo4j, LLMs can navigate complex entity connections "
    "with precise semantic accuracy."
)

print("🚀 Sending test paragraph to Cohere embed-v4.0...")

try:
    response = co.embed(
        texts=[paragraph],                 # Must be passed as a list
        model="embed-v4.0",
        input_type="search_document",       # Crucial: Tells Cohere this is a DB chunk
        embedding_types=["float"],
        output_dimension=1024               # Truncates to 1024 dim via Matryoshka MRL
    )
    
    # Extract the vector array
    vector = response.embeddings.float[0]
    
    print("\n✅ API Call Successful!")
    print(f"📐 Vector Dimensions: {len(vector)}")
    print(f"🔢 Data Type: {type(vector)}")
    print(f"👀 First 5 vector weights: {vector[:5]}")

except Exception as e:
    print(f"❌ API Call Failed: {e}")