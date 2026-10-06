"""
Monitor ingestion status and vector store health.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import AsyncSessionLocal
from app.models.source import Source
from app.models.document import Document
from app.models.vector_chunk import VectorChunk
from app.services.vector_store import vector_store


async def monitor_ingestion():
    """Monitor ingestion status and provide statistics."""
    
    async with AsyncSessionLocal() as db:
        print("📊 Ingestion Monitoring Dashboard")
        print("=" * 80)
        print(f"Timestamp: {datetime.utcnow().isoformat()}")
        print("=" * 80)
        
        # Source Statistics
        print("\n📦 Source Statistics")
        print("-" * 80)
        
        total_sources = await db.execute(select(func.count(Source.id)))
        total = total_sources.scalar()
        
        active_sources = await db.execute(
            select(func.count(Source.id)).where(Source.is_active == True)
        )
        active = active_sources.scalar()
        
        scraped_sources = await db.execute(
            select(func.count(Source.id)).where(Source.last_scraped_at.isnot(None))
        )
        scraped = scraped_sources.scalar()
        
        print(f"Total Sources: {total}")
        print(f"Active Sources: {active}")
        print(f"Scraped Sources: {scraped}")
        print(f"Not Yet Scraped: {active - scraped}")
        
        # Sources by priority
        print("\n📌 Sources by Priority:")
        for priority in [1, 2, 3, 4, 5]:
            count = await db.execute(
                select(func.count(Source.id))
                .where(Source.is_active == True)
                .where(Source.priority == priority)
            )
            print(f"   Priority {priority}: {count.scalar()}")
        
        # Sources by country
        print("\n🌍 Sources by Country:")
        result = await db.execute(
            select(Source.country, func.count(Source.id))
            .where(Source.is_active == True)
            .group_by(Source.country)
            .order_by(func.count(Source.id).desc())
        )
        for country, count in result.all():
            print(f"   {country}: {count}")
        
        # Document Statistics
        print("\n📄 Document Statistics")
        print("-" * 80)
        
        total_docs = await db.execute(select(func.count(Document.id)))
        print(f"Total Documents: {total_docs.scalar()}")
        
        # Recent documents (last 24 hours)
        day_ago = datetime.utcnow() - timedelta(days=1)
        recent_docs = await db.execute(
            select(func.count(Document.id))
            .where(Document.scraped_at >= day_ago)
        )
        print(f"Documents (Last 24h): {recent_docs.scalar()}")
        
        # Vector Chunk Statistics
        print("\n🔢 Vector Chunk Statistics")
        print("-" * 80)
        
        total_chunks = await db.execute(select(func.count(VectorChunk.id)))
        print(f"Total Chunks: {total_chunks.scalar()}")
        
        # Average chunks per document
        avg_chunks = await db.execute(
            select(func.avg(
                select(func.count(VectorChunk.id))
                .where(VectorChunk.document_id == Document.id)
                .scalar_subquery()
            ))
        )
        avg = avg_chunks.scalar()
        if avg:
            print(f"Average Chunks per Document: {avg:.1f}")
        
        # Recent Activity
        print("\n⏰ Recent Activity")
        print("-" * 80)
        
        # Last 5 scraped sources
        result = await db.execute(
            select(Source)
            .where(Source.last_scraped_at.isnot(None))
            .order_by(Source.last_scraped_at.desc())
            .limit(5)
        )
        recent_sources = result.scalars().all()
        
        if recent_sources:
            print("Last 5 Scraped Sources:")
            for source in recent_sources:
                time_ago = datetime.utcnow() - source.last_scraped_at
                hours_ago = time_ago.total_seconds() / 3600
                print(f"   • {source.name}")
                print(f"     {hours_ago:.1f} hours ago")
        
        # Sources needing scraping
        print("\n⚠️  Sources Needing Attention")
        print("-" * 80)
        
        # Never scraped
        never_scraped = await db.execute(
            select(Source)
            .where(Source.is_active == True)
            .where(Source.last_scraped_at.is_(None))
            .limit(10)
        )
        never_scraped_list = never_scraped.scalars().all()
        
        if never_scraped_list:
            print(f"Never Scraped ({len(never_scraped_list)}):")
            for source in never_scraped_list[:5]:
                print(f"   • {source.name} (Priority {source.priority})")
            if len(never_scraped_list) > 5:
                print(f"   ... and {len(never_scraped_list) - 5} more")
        
        # Stale sources (not scraped in 2x their frequency)
        stale_sources = []
        result = await db.execute(
            select(Source)
            .where(Source.is_active == True)
            .where(Source.last_scraped_at.isnot(None))
        )
        all_scraped = result.scalars().all()
        
        for source in all_scraped:
            hours_since = (datetime.utcnow() - source.last_scraped_at).total_seconds() / 3600
            if hours_since > (source.scrape_frequency * 2):
                stale_sources.append((source, hours_since))
        
        if stale_sources:
            print(f"\nStale Sources ({len(stale_sources)}):")
            for source, hours in sorted(stale_sources, key=lambda x: x[1], reverse=True)[:5]:
                print(f"   • {source.name}")
                print(f"     Last scraped {hours:.1f} hours ago (frequency: {source.scrape_frequency}h)")
        
        # Vector Store Health
        print("\n🗄️  Vector Store Health")
        print("-" * 80)
        
        try:
            # Try a test search
            test_embedding = [0.1] * 1536
            results = await vector_store.search(
                query_embedding=test_embedding,
                top_k=1
            )
            print(f"✅ Vector Store: Operational")
            print(f"   Test search returned {len(results)} results")
        except Exception as e:
            print(f"❌ Vector Store: Error")
            print(f"   {str(e)}")
        
        print("\n" + "=" * 80)
        print("✅ Monitoring Complete")
        print("=" * 80)


if __name__ == "__main__":
    asyncio.run(monitor_ingestion())
