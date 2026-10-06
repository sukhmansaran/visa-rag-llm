"""
Quick smoke test for the Ollama integration.
Run from the backend/ directory:

    python scripts/test_ollama.py

Does NOT need the full backend running — hits Ollama directly.
"""

import asyncio
import sys
import os

# Allow imports from app/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set minimal env so Settings doesn't complain about missing required vars
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("OLLAMA_MODEL", "llama3.2:3b")
os.environ.setdefault("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")

from app.services.llm import OllamaService  # noqa: E402


async def test_basic():
    svc = OllamaService()
    print(f"\n{'='*60}")
    print(f"  Ollama smoke test")
    print(f"  Base URL : {svc.base_url}")
    print(f"  Model    : {svc.model}")
    print(f"{'='*60}\n")

    # --- Test 1: basic non-streaming response ---
    print("▶ Test 1: Non-streaming response")
    try:
        response = await svc.generate_answer(
            system_prompt="You are a helpful assistant. Be brief.",
            user_prompt="What documents does a student typically need for a Canada study permit?",
            max_tokens=300,
        )
        print(f"  ✅ Got response ({len(response)} chars)")
        print(f"  Preview: {response[:200]}...\n")
    except Exception as e:
        print(f"  ❌ FAILED: {e}\n")
        return False

    # --- Test 2: streaming response ---
    print("▶ Test 2: Streaming response")
    try:
        chunks = []
        async for chunk in svc.generate_answer_stream(
            system_prompt="You are a helpful assistant. Be brief.",
            user_prompt="Name three things to pack for a Canada winter trip.",
            max_tokens=150,
        ):
            chunks.append(chunk)
            print(chunk, end="", flush=True)
        print(f"\n  ✅ Stream complete — {len(chunks)} chunks received\n")
    except Exception as e:
        print(f"\n  ❌ FAILED: {e}\n")
        return False

    # --- Test 3: factual summarize ---
    print("▶ Test 3: factual_summarize()")
    try:
        sample = (
            "Canadian study permits require a letter of acceptance from a DLI, "
            "proof of financial support (at least CAD $10,000/year), a valid passport, "
            "passport-size photos, and a completed application form. Biometrics are "
            "required for most applicants. Processing takes 8–16 weeks on average."
        )
        summary = await svc.factual_summarize(sample)
        print(f"  ✅ Summary ({len(summary)} chars)")
        print(f"  {summary[:200]}\n")
    except Exception as e:
        print(f"  ❌ FAILED: {e}\n")
        return False

    print("='*60")
    print("  All tests passed — Ollama integration is working ✅")
    print("='*60\n")
    return True


if __name__ == "__main__":
    ok = asyncio.run(test_basic())
    sys.exit(0 if ok else 1)
