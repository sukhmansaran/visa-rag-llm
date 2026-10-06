"""
Vector store service supporting Chroma (local) and Pinecone (production).
"""

from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
import uuid

from app.core.config import settings


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


class ChromaVectorStore(VectorStore):
    """Chroma vector store implementation for local development."""
    
    def __init__(self):
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        
        self.client = chromadb.Client(ChromaSettings(
            persist_directory=settings.CHROMA_PERSIST_DIRECTORY,
            anonymized_telemetry=False,
        ))
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name="visa_chatbot",
            metadata={"description": "Visa and university information chunks"}
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
        
        # Chroma requires synchronous call
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        
        return ids
    
    async def search(
        self,
        query_embedding: List[float],
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search Chroma for similar chunks."""
        
        # Build where filter - ChromaDB requires $and for multiple conditions
        where_filter = None
        if filters:
            conditions = [{k: v} for k, v in filters.items()]
            if len(conditions) == 1:
                where_filter = conditions[0]
            else:
                where_filter = {"$and": conditions}
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_filter,
        )
        
        # Format results
        formatted = []
        if results['ids'] and results['ids'][0]:
            for i, chunk_id in enumerate(results['ids'][0]):
                formatted.append({
                    'id': chunk_id,
                    'text': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'score': results['distances'][0][i] if results.get('distances') else 0.0,
                })
        
        return formatted
    
    async def delete_by_source(self, source_id: int) -> None:
        """Delete chunks by source_id metadata."""
        # Query for all chunks with this source_id
        results = self.collection.get(
            where={"source_id": source_id}
        )
        
        if results['ids']:
            self.collection.delete(ids=results['ids'])


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
