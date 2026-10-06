"""
Test script for change detection system.
"""

import asyncio
from app.services.change_detector import change_detector
from app.services.notification_service import notification_service
from app.core.database import AsyncSessionLocal
from sqlalchemy import select
from app.models.source import Source


async def test_change_detection():
    """Test the change detection system."""
    
    print("=== Testing Change Detection System ===\n")
    
    async with AsyncSessionLocal() as db:
        # Get first active source
        result = await db.execute(
            select(Source).where(Source.is_active == True).limit(1)
        )
        source = result.scalar_one_or_none()
        
        if not source:
            print("❌ No active sources found. Run seed_sources.py first.")
            return
        
        print(f"Testing with source: {source.name}")
        print(f"URL: {source.url}\n")
        
        # Detect changes
        print("1. Checking for changes...")
        change = await change_detector.detect_change(source.id, db)
        
        if not change:
            print("   ℹ️  No changes detected (content unchanged)")
        else:
            print(f"   ✅ Change detected!")
            print(f"   📊 Severity: {change.severity}")
            print(f"   📝 Summary: {change.diff_summary}\n")
            
            # Identify affected users
            print("2. Identifying affected users...")
            affected_users = await change_detector.identify_affected_users(change, db)
            print(f"   👥 Found {len(affected_users)} affected users\n")
            
            if affected_users:
                # Notify users
                print("3. Sending notifications...")
                await notification_service.notify_users_of_change(
                    user_ids=affected_users,
                    source_name=source.name,
                    diff_summary=change.diff_summary,
                    source_url=source.url,
                    severity=change.severity,
                    db=db,
                )
                print(f"   ✅ Notifications sent to {len(affected_users)} users\n")
        
        print("=== Test Complete ===")


if __name__ == "__main__":
    asyncio.run(test_change_detection())
