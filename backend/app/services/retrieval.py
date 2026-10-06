"""
Retrieval service for RAG pipeline.
Handles vector search, reranking, and context preparation.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime

from app.services.vector_store import vector_store
from app.services.embeddings import embed_text


class RetrievalService:
    """Retrieves relevant context for RAG queries."""
    
    async def retrieve(
        self,
        query: str,
        country: Optional[str] = None,
        university: Optional[str] = None,
        visa_type: Optional[str] = None,
        intent: Optional[str] = None,
        top_k: int = 2,  # Mandated hard limit
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant chunks for a query with strict metadata filtering.
        """
        # Generate query embedding
        try:
            query_embedding = await embed_text(query)
        except Exception as e:
            print(f"[RETRIEVAL] Error generating query embedding: {e}")
            return []
        
        # Build strict metadata filters
        filters = {}
        if country and country != "unknown":
            filters['country'] = country
        if university and university != "unknown":
            filters['university'] = university
        if visa_type and visa_type != "unknown":
            filters['visa_type'] = visa_type
        if intent and intent != "general":
             filters['intent'] = intent
        
        # Retrieve from vector store with strict top_k
        results = await vector_store.search(
            query_embedding=query_embedding,
            filters=filters if filters else None,
            top_k=top_k,
        )
        
        # Rerank results
        reranked = self._rerank(results, query, country)
        
        return reranked
    
    def _rerank(
        self,
        results: List[Dict[str, Any]],
        query: str,
        country: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Rerank results based on relevance signals.
        
        Simple reranking based on:
        - Vector similarity score
        - Source priority (embassy > university > news)
        - Recency (newer = better)
        - Country match
        """
        scored_results = []
        
        for result in results:
            score = result.get('score', 0.0)
            metadata = result.get('metadata', {})
            
            # Boost embassy/official sources
            if metadata.get('source_type') == 'embassy':
                score *= 1.3
            elif metadata.get('source_type') == 'official':
                score *= 1.2
            
            # Boost recent content (last 6 months)
            scraped_at = metadata.get('scraped_at')
            if scraped_at:
                try:
                    scraped_date = datetime.fromisoformat(scraped_at.replace('Z', '+00:00'))
                    days_old = (datetime.now(scraped_date.tzinfo) - scraped_date).days
                    if days_old < 180:  # Less than 6 months
                        score *= 1.1
                except:
                    pass
            
            # Boost country match
            if country and metadata.get('country') == country:
                score *= 1.15
            
            result['rerank_score'] = score
            scored_results.append(result)
        
        # Sort by reranked score (higher = better)
        # Note: Chroma returns distances (lower = better), Pinecone returns similarity (higher = better)
        # For now, assume higher score = better after boosting
        scored_results.sort(key=lambda x: x['rerank_score'], reverse=True)
        
        return scored_results
    
    def prepare_context(
        self,
        chunks: List[Dict[str, Any]],
        max_context_length: int = 4000,
    ) -> str:
        """
        Prepare context string from chunks.
        
        Args:
            chunks: Retrieved chunks
            max_context_length: Maximum context length in characters
            
        Returns:
            Formatted context string
        """
        context_parts = []
        current_length = 0
        
        for i, chunk in enumerate(chunks):
            text = chunk.get('text', '')
            metadata = chunk.get('metadata', {})
            
            # Format: [Source N] {text}
            # URL: {url} (Retrieved: {date})
            source_text = f"[Source {i+1}] {text}\nURL: {metadata.get('url', 'N/A')} (Retrieved: {metadata.get('scraped_at', 'N/A')})\n\n"
            
            if current_length + len(source_text) > max_context_length:
                break
            
            context_parts.append(source_text)
            current_length += len(source_text)
        
        return ''.join(context_parts)


# Global instance
retrieval_service = RetrievalService()
