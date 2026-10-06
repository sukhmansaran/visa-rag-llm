"""
Manual test script for the ingestion pipeline.
Tests scraping, chunking, embedding, and vector storage.
"""

import asyncio
from app.services.scraper import scrape_with_retry
from app.services.chunker import chunk_document
from app.services.embeddings import embed_texts_batch
from app.services.vector_store import vector_store


async def test_ingestion_pipeline():
    """Test the complete ingestion pipeline on a sample URL."""
    
    # Test URL — Canada-only focus
    test_url = "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada/study-permit.html"
    
    print("=== Testing Ingestion Pipeline ===\n")
    
    # Step 1: Scraping
    print("1. Scraping URL...")
    scraped_data = await scrape_with_retry(test_url)
    print(f"   ✅ Scraped: {scraped_data['title']}")
    print(f"   📏 Content length: {len(scraped_data['extracted_text'])} chars")
    print(f"   #️⃣  Hash: {scraped_data['content_hash'][:16]}...")
    
    # Step 2: Chunking
    print("\n2. Chunking text...")
    chunks = chunk_document(
        text=scraped_data['extracted_text'],
        url=test_url,
        title=scraped_data['title'],
        scraped_at=scraped_data['scraped_at'],
        chunk_size=500,
        overlap=100,
    )
    print(f"   ✅ Created {len(chunks)} chunks")
    if chunks:
        print(f"   📝 First chunk preview: {chunks[0]['text'][:100]}...")
    
    # Step 3: Embedding
    print("\n3. Embedding chunks...")
    chunk_texts = [chunk['text'] for chunk in chunks[:5]]  # Test with first 5
    embeddings = await embed_texts_batch(chunk_texts)
    print(f"   ✅ Generated {len(embeddings)} embeddings")
    print(f"   🔢 Embedding dimension: {len(embeddings[0])}")
    
    # Step 4: Vector storage
    print("\n4. Storing in vector database...")
    for chunk, embedding in zip(chunks[:5], embeddings):
        chunk['embedding'] = embedding
        chunk['metadata']['source_id'] = 999  # Test source ID
        chunk['metadata']['country'] = 'Canada'
        chunk['metadata']['source_type'] = 'embassy'
    
    vector_ids = await vector_store.upsert_chunks(chunks[:5])
    print(f"   ✅ Stored {len(vector_ids)} vectors")
    print(f"   🆔 Vector IDs: {vector_ids[:2]}...")
    
    # Step 5: Search test
    print("\n5. Testing vector search...")
    query_text = "What documents do I need for a Canada student visa?"
    from app.services.embeddings import embed_text
    query_embedding = await embed_text(query_text)
    
    results = await vector_store.search(
        query_embedding=query_embedding,
        filters={"country": "Canada"},
        top_k=3,
    )
    
    print(f"   ✅ Found {len(results)} results")
    for i, result in enumerate(results, 1):
        print(f"\n   Result {i}:")
        print(f"   📊 Score: {result['score']:.4f}")
        print(f"   📝 Text: {result['text'][:150]}...")
    
    print("\n=== Pipeline Test Complete ===")


if __name__ == "__main__":
    asyncio.run(test_ingestion_pipeline())
