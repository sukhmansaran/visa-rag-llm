"""
Text chunking service for splitting documents into embeddable chunks.
"""

from typing import List, Dict, Any
import re


class TextChunker:
    """Chunks text into overlapping segments for embedding."""
    
    def __init__(self, chunk_size: int = 1000, overlap: int = 200):
        """
        Initialize chunker.
        
        Args:
            chunk_size: Target size of each chunk in characters
            overlap: Number of overlapping characters between chunks
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
    
    def chunk_text(
        self,
        text: str,
        metadata: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Split text into chunks with metadata.
        
        Args:
            text: Text content to chunk
            metadata: Metadata to attach to each chunk (url, title, etc.)
            
        Returns:
            List of chunk dicts with text and metadata
        """
        chunks = []
        
        # Split into sentences for better chunk boundaries
        sentences = self._split_into_sentences(text)
        
        current_chunk = []
        current_length = 0
        chunk_index = 0
        
        for sentence in sentences:
            sentence_length = len(sentence)
            
            # If adding this sentence exceeds chunk size, save current chunk
            if current_length + sentence_length > self.chunk_size and current_chunk:
                chunk_text = ' '.join(current_chunk)
                chunks.append({
                    'text': chunk_text,
                    'chunk_index': chunk_index,
                    'metadata': {
                        **metadata,
                        'chunk_size': len(chunk_text),
                    }
                })
                
                chunk_index += 1
                
                # Keep overlap sentences for context
                overlap_text = chunk_text[-self.overlap:] if len(chunk_text) > self.overlap else chunk_text
                current_chunk = [overlap_text]
                current_length = len(overlap_text)
            
            current_chunk.append(sentence)
            current_length += sentence_length + 1  # +1 for space
        
        # Add final chunk
        if current_chunk:
            chunk_text = ' '.join(current_chunk)
            chunks.append({
                'text': chunk_text,
                'chunk_index': chunk_index,
                'metadata': {
                    **metadata,
                    'chunk_size': len(chunk_text),
                }
            })
        
        return chunks
    
    @staticmethod
    def _split_into_sentences(text: str) -> List[str]:
        """
        Split text into sentences.
        
        Uses simple regex-based sentence splitting.
        """
        # Split on period, exclamation, question mark followed by space or newline
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]


def chunk_document(
    text: str,
    url: str,
    title: str,
    scraped_at: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> List[Dict[str, Any]]:
    """
    Convenience function to chunk a document.
    
    Args:
        text: Document text
        url: Source URL
        title: Document title
        scraped_at: ISO timestamp of scraping
        chunk_size: Target chunk size
        overlap: Overlap size
        
    Returns:
        List of chunks with metadata
    """
    chunker = TextChunker(chunk_size=chunk_size, overlap=overlap)
    
    metadata = {
        'url': url,
        'title': title,
        'scraped_at': scraped_at,
    }
    
    return chunker.chunk_text(text, metadata)
