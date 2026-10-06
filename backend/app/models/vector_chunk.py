from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, JSON, Column

if TYPE_CHECKING:
    from app.models.document import Document


class VectorChunk(SQLModel, table=True):
    """Text chunks with embeddings stored in vector database."""
    
    __tablename__ = "vector_chunks"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="documents.id", index=True)
    
    # Chunk index within the document
    chunk_index: int = Field()
    
    # Actual text content
    text: str = Field()
    
    # Vector database ID (Chroma/Pinecone)
    vector_id: str = Field(unique=True, index=True, max_length=255)
    
    # Metadata stored in vector DB: {url, title, page_no, scraped_at, country, source_type}
    chunk_metadata: Dict[str, Any] = Field(sa_column=Column(JSON))  # Renamed from metadata
    
    # Relationships
    document: "Document" = Relationship(back_populates="chunks")
