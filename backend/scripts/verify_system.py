"""
Complete system verification script.
Tests all phases of the backend.
"""

import asyncio
import sys


async def verify_system():
    """Run complete system verification."""
    
    print("=" * 70)
    print("OVERSEAS VISA CHATBOT - SYSTEM VERIFICATION")
    print("=" * 70)
    print()
    
    results = {
        "passed": 0,
        "failed": 0,
    }
    
    # Phase A: Database Connection
    print("📊 Phase A: Database Connection")
    try:
        from app.core.database import engine
        async with engine.connect() as conn:
            print("   ✅ Database connected")
            results["passed"] += 1
    except Exception as e:
        print(f"   ❌ Database connection failed: {e}")
        results["failed"] += 1
    
    # Phase A: Models Import
    print("\n📦 Phase A: Models")
    try:
        from app.models.user import User
        from app.models.profile import Profile
        from app.models.source import Source
        from app.models.document import Document
        from app.models.vector_chunk import VectorChunk
        from app.models.watchlist import Watchlist
        from app.models.notification import Notification
        from app.models.user_document import UserDocument
        from app.models.review import Review
        from app.models.chat_message import ChatMessage
        from app.models.change import Change
        from app.models.payment import Payment
        print("   ✅ All 12 models imported")
        results["passed"] += 1
    except Exception as e:
        print(f"   ❌ Model import failed: {e}")
        results["failed"] += 1
    
    # Phase B: Services
    print("\n🔧 Phase B: Ingestion Services")
    try:
        from app.services.scraper import WebScraper
        from app.services.chunker import TextChunker
        from app.services.embeddings import embedding_service
        from app.services.vector_store import vector_store
        from app.services.ingestion import ingestion_service
        print("   ✅ All ingestion services imported")
        results["passed"] += 1
    except Exception as e:
        print(f"   ❌ Service import failed: {e}")
        results["failed"] += 1
    
    # Phase D: RAG Services
    print("\n🤖 Phase D: RAG Services")
    try:
        from app.services.retrieval import retrieval_service
        from app.services.llm import llm_service
        from app.services.prompts import get_prompt_template
        print("   ✅ RAG services imported")
        results["passed"] += 1
    except Exception as e:
        print(f"   ❌ RAG service import failed: {e}")
        results["failed"] += 1
    
    # Phase E: Mobile APIs
    print("\n📱 Phase E: Mobile API Endpoints")
    try:
        from app.api.v1 import profile, documents, watchlist_api, notifications
        print("   ✅ Mobile API modules imported")
        results["passed"] += 1
    except Exception as e:
        print(f"   ❌ Mobile API import failed: {e}")
        results["failed"] += 1
    
    # Phase F: Change Detection
    print("\n🔍 Phase F: Change Detection")
    try:
        from app.services.change_detector import change_detector
        from app.services.notification_service import notification_service
        print("   ✅ Change detection services imported")
        results["passed"] += 1
    except Exception as e:
        print(f"   ❌ Change detection import failed: {e}")
        results["failed"] += 1
    
    # Phase G: Payments
    print("\n💳 Phase G: Payment System")
    try:
        from app.api.v1 import payments, reviews
        import stripe
        print("   ✅ Payment modules imported")
        results["passed"] += 1
    except Exception as e:
        print(f"   ❌ Payment import failed: {e}")
        results["failed"] += 1
    
    # Background Workers
    print("\n⚙️  Background Workers")
    try:
        from app.workers.tasks import (
            ingest_source_task,
            detect_changes_task,
            periodic_change_detection_task,
        )
        from app.workers.celery_app import celery_app
        print("   ✅ Celery tasks imported")
        results["passed"] += 1
    except Exception as e:
        print(f"   ❌ Celery import failed: {e}")
        results["failed"] += 1
    
    # API Application
    print("\n🚀 FastAPI Application")
    try:
        from app.main import app
        print(f"   ✅ Application created: {app.title}")
        print(f"   📝 Total routes: {len(app.routes)}")
        results["passed"] += 1
    except Exception as e:
        print(f"   ❌ App creation failed: {e}")
        results["failed"] += 1
    
    # Summary
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    print(f"✅ Passed: {results['passed']}")
    print(f"❌ Failed: {results['failed']}")
    
    if results["failed"] == 0:
        print("\n🎉 All systems operational!")
        return 0
    else:
        print("\n⚠️  Some systems failed. Check errors above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(verify_system())
    sys.exit(exit_code)
