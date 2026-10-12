"""
Vector store service supporting Chroma (local) and Pinecone (production).
"""

from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
import asyncio
import uuid

from app.core.config import settings


def _invalidate_answer_cache() -> None:
    """Drop cached answers in this process after the knowledge base changes (B16)."""
    from app.services.cache_service import intent_cache
    intent_cache.clear()


class VectorStore(ABC):
    """Abstract base class for vector store implementations."""
    
    @abstractmethod
    async def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """
        Insert or update chunks in the vector store.
        
        Args:
            chunks: List of dicts with 'text', 'embedding', 'metadata'
            
        Returns:
            List of vector IDs
        """
        pass
    
    @abstractmethod
    async def search(
        self,
        query_embedding: List[float],
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar vectors.
        
        Args:
            query_embedding: Query vector
            filters: Metadata filters (e.g., {'country': 'Canada'})
            top_k: Number of results to return
            
        Returns:
            List of dicts with 'id', 'text', 'metadata', 'score'
        """
        pass
    
    @abstractmethod
    async def delete_by_source(self, source_id: int) -> None:
        """Delete all chunks from a specific source."""
        pass

    async def content_version(self) -> str:
        """
        Cheap fingerprint of the knowledge-base contents, used in answer-cache keys (B16)
        so cached answers stop matching once ingestion (in any process) changes the store.
        """
        return "static"


class ChromaVectorStore(VectorStore):
    """Chroma vector store implementation with persistent disk storage."""
    
    def __init__(self, persist_directory: Optional[str] = None):
        import chromadb
        from pathlib import Path
        
        persist_dir = persist_directory or settings.CHROMA_PERSIST_DIRECTORY
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        
        self.client = chromadb.PersistentClient(
            path=str(persist_dir),
        )
        
        # Get or create collection with cosine distance metric
        self.collection = self.client.get_or_create_collection(
            name="visa_chatbot",
            metadata={
                "description": "Visa and university information chunks",
                "hnsw:space": "cosine",
            }
        )
    
    async def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """Insert chunks into Chroma."""
        ids = []
        embeddings = []
        documents = []
        metadatas = []
        
        for chunk in chunks:
            chunk_id = str(uuid.uuid4())
            ids.append(chunk_id)
            embeddings.append(chunk['embedding'])
            documents.append(chunk['text'])
            metadatas.append(chunk['metadata'])
        
        # Offload synchronous Chroma operation to thread
        await asyncio.to_thread(
            self.collection.add,
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        _invalidate_answer_cache()
        
        return ids

    async def content_version(self) -> str:
        count = await asyncio.to_thread(self.collection.count)
        return f"chroma-{count}"
    
    async def search(
        self,
        query_embedding: List[float],
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search Chroma for similar chunks using cosine similarity."""
        
        # Build where filter - ChromaDB requires $and for multiple conditions
        where_filter = None
        if filters:
            conditions = [{k: v} for k, v in filters.items()]
            if len(conditions) == 1:
                where_filter = conditions[0]
            else:
                where_filter = {"$and": conditions}
        
        results = await asyncio.to_thread(
            self.collection.query,
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_filter,
        )
        
        # Format results: in cosine space, Chroma distance is 1 - cosine_sim
        # Convert distance to similarity score in [0.0, 1.0] where 1.0 is exact match
        formatted = []
        if results['ids'] and results['ids'][0]:
            for i, chunk_id in enumerate(results['ids'][0]):
                raw_dist = results['distances'][0][i] if results.get('distances') else 1.0
                similarity = max(0.0, min(1.0, 1.0 - raw_dist))
                formatted.append({
                    'id': chunk_id,
                    'text': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'score': round(similarity, 4),
                })
        
        return formatted
    
    async def delete_by_source(self, source_id: int) -> None:
        """Delete chunks by source_id metadata."""
        results = await asyncio.to_thread(
            self.collection.get,
            where={"source_id": source_id}
        )
        
        if results['ids']:
            await asyncio.to_thread(
                self.collection.delete,
                ids=results['ids']
            )
            _invalidate_answer_cache()


class PineconeVectorStore(VectorStore):
    """Pinecone vector store implementation for production."""
    
    def __init__(self):
        import pinecone
        
        pinecone.init(
            api_key=settings.PINECONE_API_KEY,
            environment=settings.PINECONE_ENVIRONMENT,
        )
        
        self.index = pinecone.Index(settings.PINECONE_INDEX_NAME)
    
    async def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """Insert chunks into Pinecone."""
        vectors = []
        ids = []
        
        for chunk in chunks:
            chunk_id = str(uuid.uuid4())
            ids.append(chunk_id)
            
            vectors.append({
                'id': chunk_id,
                'values': chunk['embedding'],
                'metadata': {
                    **chunk['metadata'],
                    'text': chunk['text'],  # Store text in metadata
                }
            })
        
        # Upsert in batches of 100
        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            self.index.upsert(vectors=batch)
        
        return ids
    
    async def search(
        self,
        query_embedding: List[float],
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search Pinecone for similar chunks."""
        
        results = self.index.query(
            vector=query_embedding,
            top_k=top_k,
            filter=filters,
            include_metadata=True,
        )
        
        formatted = []
        for match in results['matches']:
            formatted.append({
                'id': match['id'],
                'text': match['metadata'].get('text', ''),
                'metadata': match['metadata'],
                'score': match['score'],
            })
        
        return formatted
    
    async def delete_by_source(self, source_id: int) -> None:
        """Delete chunks by source_id filter."""
        self.index.delete(filter={"source_id": source_id})


def get_vector_store() -> VectorStore:
    """Factory function to get the configured vector store."""
    if settings.VECTOR_DB_TYPE == "pinecone":
        return PineconeVectorStore()
    else:
        return ChromaVectorStore()


# Global instance
vector_store = get_vector_store()
