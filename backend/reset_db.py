"""
Simple database reset script - Windows compatible.
"""
import asyncio
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def reset_database():
    """Reset database by dropping and recreating schema."""
    
    # Get database URL from settings
    from app.core.config import settings
    database_url = settings.DATABASE_URL
    
    print("=" * 60)
    print("  DATABASE RESET")
    print("=" * 60)
    print("\nDatabase: {database_url.split('@')[1] if '@' in database_url else database_url}")
    print("\nWARNING: This will DELETE ALL DATA!\n")
    
    # Create engine with proper cleanup
    engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0
    )
    
    try:
        print("[*] Dropping schema...")
        async with engine.begin() as conn:
            # Drop and recreate schema
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.execute(text("GRANT ALL ON SCHEMA public TO postgres"))
            await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        
        print("[OK] Schema dropped and recreated\n")
        
        print("[*] Creating tables...")
        # Import models
        from sqlmodel import SQLModel
        from app.models.user import User
        from app.models.profile import Profile
        from app.models.user_document import UserDocument
        from app.models.watchlist import Watchlist
        from app.models.source import Source
        from app.models.document import Document
        from app.models.change import Change
        from app.models.notification import Notification
        
        # Create all tables
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        
        print("[OK] Tables created successfully\n")
        
        # List created tables
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public' 
                ORDER BY tablename
            """))
            tables = result.fetchall()
            
            print("[i] Created tables:")
            for table in tables:
                print(f"   - {table[0]}")
        
        print("\n" + "=" * 60)
        print("  [OK] DATABASE RESET COMPLETE!")
        print("=" * 60)
        print("\n[i] Next steps:")
        print("   1. Restart your backend server")
        print("   2. Register a new user from your mobile app\n")
        
        return True
        
    except Exception as e:
        print(f"\n[ERROR] {str(e)}\n")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Properly close engine
        await engine.dispose()


def main():
    """Main entry point."""
    print("\n" + "=" * 60)
    response = input("WARNING: Press ENTER to DELETE ALL DATA (or Ctrl+C to cancel): ")
    print()
    
    # Run with proper event loop cleanup
    if sys.platform == 'win32':
        # Windows-specific asyncio policy
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        success = asyncio.run(reset_database())
        
        if success:
            print("\n[OK] Success! Database is now clean.\n")
            sys.exit(0)
        else:
            print("\n[ERROR] Reset failed!\n")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\nWARNING: Cancelled by user. Database was NOT modified.\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
