"""
Run initial ingestion for all seeded sources.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.source import Source
from app.services.ingestion import ingestion_service


async def run_initial_ingestion(limit: int = None, priority: int = None):
    """
    Run initial ingestion for sources.
    
    Args:
        limit: Maximum number of sources to ingest (None for all)
        priority: Only ingest sources with this priority (None for all)
    """
    
    async with AsyncSessionLocal() as db:
        print("🚀 Starting Initial Ingestion")
        print("=" * 80)
        
        # Build query
        query = select(Source).where(Source.is_active == True)
        
        if priority is not None:
            query = query.where(Source.priority == priority)
            print(f"📌 Filtering by priority: {priority}")
        
        query = query.order_by(Source.priority, Source.id)
        
        if limit:
            query = query.limit(limit)
            print(f"📊 Limiting to: {limit} sources")
        
        result = await db.execute(query)
        sources = result.scalars().all()
        
        if not sources:
            print("❌ No sources found to ingest")
            return
        
        print(f"📦 Found {len(sources)} sources to ingest")
        print("=" * 80)
        print()
        
        results = {
            "success": 0,
            "skipped": 0,
            "error": 0,
            "total": len(sources)
        }
        
        for i, source in enumerate(sources, 1):
            print(f"\n[{i}/{len(sources)}] Processing: {source.name}")
            print(f"   URL: {source.url}")
            print(f"   Country: {source.country}")
            print(f"   Priority: {source.priority}")
            
            try:
                result = await ingestion_service.ingest_source(source.id, db)
                
                if result['status'] == 'success':
                    print(f"   ✅ Success: {result['chunks_created']} chunks created")
                    results["success"] += 1
                elif result['status'] == 'skipped':
                    print(f"   ⏭️  Skipped: {result['reason']}")
                    results["skipped"] += 1
                else:
                    print(f"   ⚠️  Status: {result['status']}")
                    results["error"] += 1
                    
            except Exception as e:
                print(f"   ❌ Error: {str(e)}")
                results["error"] += 1
            
            # Small delay to avoid overwhelming services
            await asyncio.sleep(2)
        
        print("\n" + "=" * 80)
        print("📊 Ingestion Summary")
        print("=" * 80)
        print(f"   Total Sources: {results['total']}")
        print(f"   ✅ Successful: {results['success']}")
        print(f"   ⏭️  Skipped: {results['skipped']}")
        print(f"   ❌ Errors: {results['error']}")
        print(f"   Success Rate: {(results['success'] / results['total'] * 100):.1f}%")
        print("=" * 80)


async def main():
    """Main function with CLI arguments."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run initial ingestion")
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of sources to ingest"
    )
    parser.add_argument(
        "--priority",
        type=int,
        choices=[1, 2, 3, 4, 5],
        help="Only ingest sources with this priority"
    )
    
    args = parser.parse_args()
    
    await run_initial_ingestion(limit=args.limit, priority=args.priority)


if __name__ == "__main__":
    asyncio.run(main())
