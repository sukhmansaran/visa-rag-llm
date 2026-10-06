"""
Backward-compatibility shim.
All code that imported from app.services.gemini now gets OllamaService transparently.
"""

from app.services.llm import llm_service as gemini_service  # noqa: F401

__all__ = ["gemini_service"]
