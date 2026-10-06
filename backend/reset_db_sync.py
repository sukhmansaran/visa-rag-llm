"""
Alternative: Direct PostgreSQL cleanup using psycopg2 (synchronous, more reliable on Windows).
"""
import sys


def reset_database_sync():
    """Reset database using synchronous psycopg2."""
    try:
        import psycopg2
        from psycopg2 import sql
    except ImportError:
        print("❌ psycopg2 not installed. Install with: pip install psycopg2-binary")
        return False
    
    from app.core.config import settings
    
    # Parse database URL
    db_url = settings.DATABASE_URL.replace('postgresql+asyncpg://', 'postgresql://')
    
    print("=" * 60)
    print("  DATABASE RESET (Synchronous Method)")
    print("=" * 60)
    print(f"\nDatabase: visa_chatbot")
    print("\n⚠️  WARNING: This will DELETE ALL DATA!\n")
    
    try:
        # Connect to database
        print("⏳ Connecting to database...")
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("⏳ Dropping schema...")
        cursor.execute("DROP SCHEMA IF EXISTS public CASCADE")
        cursor.execute("CREATE SCHEMA public")
        cursor.execute("GRANT ALL ON SCHEMA public TO postgres")
        cursor.execute("GRANT ALL ON SCHEMA public TO public")
        
        print("✅ Schema reset complete\n")
        
        cursor.close()
        conn.close()
        
        print("=" * 60)
        print("  ✅ DATABASE CLEANED!")
        print("=" * 60)
        print("\n📝 Next steps:")
        print("   1. Restart your backend server")
        print("   2. Tables will be recreated automatically")
        print("   3. Register a new user from your mobile app\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}\n")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main entry point."""
    print("\n" + "=" * 60)
    response = input("WARNING: Press ENTER to DELETE ALL DATA (or Ctrl+C to cancel): ")
    print()
    
    try:
        success = reset_database_sync()
        
        if success:
            print("\n✅ Success! Database is now clean.\n")
            sys.exit(0)
        else:
            print("\n❌ Reset failed!\n")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelled by user. Database was NOT modified.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
