"""
Test script for the complete RAG pipeline.
Tests retrieval, LLM generation, citation validation, and confidence scoring.
"""

import asyncio
from app.services.retrieval import retrieval_service
from app.services.llm import llm_service


async def test_rag_pipeline():
    """Test the complete RAG pipeline."""
    
    print("=== Testing Complete RAG Pipeline ===\n")
    
    # Test query — Canada-only focus
    test_query = "What documents do I need for a Canada student visa?"
    
    print(f"Query: {test_query}\n")
    
    # Step 1: Retrieval
    print("1. Retrieving context...")
    chunks = await retrieval_service.retrieve(
        query=test_query,
        country="Canada",
        top_k=5,
    )
    
    if not chunks:
        print("   ❌ No chunks retrieved. Run ingestion first!")
        return
    
    print(f"   ✅ Retrieved {len(chunks)} chunks")
    print(f"   📊 Top chunk score: {chunks[0].get('rerank_score', 0):.4f}")
    print(f"   📝 First chunk: {chunks[0].get('text', '')[:100]}...\n")
    
    # Step 2: Prepare context
    print("2. Preparing context...")
    context = retrieval_service.prepare_context(chunks, max_context_length=4000)
    print(f"   ✅ Context prepared ({len(context)} chars)\n")
    
    # Step 3: Generate answer
    print("3. Generating answer with LLM...")
    result = await llm_service.generate_answer(
        query=test_query,
        context=context,
        chunks=chunks,
        query_type="visa",
    )
    
    print(f"   ✅ Answer generated")
    print(f"   📈 Confidence: {result['confidence']:.2%}")
    print(f"   🚨 Escalate: {result['escalate']}")
    print(f"   📚 Sources cited: {len(result['sources'])}\n")
    
    # Step 4: Display answer
    print("=" * 70)
    print("ANSWER:")
    print("=" * 70)
    print(result['advice_text'])
    print("=" * 70)
    
    # Step 5: Display sources
    print("\nSOURCES:")
    print("=" * 70)
    for i, source in enumerate(result['sources'], 1):
        print(f"\n[{i}] {source.get('title', 'Untitled')}")
        print(f"    URL: {source.get('url', 'N/A')}")
        print(f"    Type: {source.get('source_type', 'unknown')}")
        print(f"    Retrieved: {source.get('scraped_at', 'N/A')}")
        print(f"    Snippet: {source.get('snippet', '')[:150]}...")
    
    print("\n" + "=" * 70)
    
    # Step 6: Metadata
    print("\nMETADATA:")
    print("=" * 70)
    metadata = result.get('metadata', {})
    for key, value in metadata.items():
        print(f"  {key}: {value}")
    
    print("\n=== Pipeline Test Complete ===")


async def test_multiple_queries():
    """Test multiple query types."""
    
    test_queries = [
        ("What is the Canada student visa processing time?", "visa", "Canada"),
        ("Tell me about admission requirements for University of Toronto", "university", "Canada"),
        ("What documents do I need for Canada study permit?", "checklist", "Canada"),
    ]
    
    print("\n=== Testing Multiple Query Types ===\n")
    
    for query, qtype, country in test_queries:
        print(f"\n{'='*70}")
        print(f"Query: {query}")
        print(f"Type: {qtype} | Country: {country}")
        print('='*70)
        
        chunks = await retrieval_service.retrieve(query, country=country, top_k=3)
        
        if not chunks:
            print("❌ No chunks found")
            continue
        
        context = retrieval_service.prepare_context(chunks)
        result = await llm_service.generate_answer(query, context, chunks, qtype)
        
        print(f"\nConfidence: {result['confidence']:.2%} | Sources: {len(result['sources'])}")
        print(f"\nAnswer (first 200 chars):\n{result['advice_text'][:200]}...\n")


if __name__ == "__main__":
    print("Choose test:")
    print("1. Single query (detailed)")
    print("2. Multiple queries (summary)")
    
    choice = input("Enter choice (1/2): ").strip()
    
    if choice == "1":
        asyncio.run(test_rag_pipeline())
    elif choice == "2":
        asyncio.run(test_multiple_queries())
    else:
        print("Invalid choice")
