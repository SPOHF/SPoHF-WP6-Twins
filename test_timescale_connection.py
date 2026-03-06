#!/usr/bin/env python3

"""Test TimescaleDB connection and basic functionality."""

import psycopg2
import sys

# Database connection settings
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "sensordb"
DB_USER = "postgres"
DB_PASSWORD = "localdevpassword"

def test_connection():
    """Test basic TimescaleDB connection."""
    print("🔍 Testing TimescaleDB connection...")
    print(f"   Host: {DB_HOST}:{DB_PORT}")
    print(f"   Database: {DB_NAME}")
    print(f"   User: {DB_USER}")
    
    try:
        # Connect to TimescaleDB
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,  
            user=DB_USER,
            password=DB_PASSWORD
        )
        
        cursor = conn.cursor()
        
        # Test basic query
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        print(f"✅ Connected successfully!")
        print(f"   PostgreSQL version: {version}")
        
        # Check if TimescaleDB extension is available
        cursor.execute("SELECT * FROM pg_available_extensions WHERE name = 'timescaledb';")
        timescale_available = cursor.fetchone()
        
        if timescale_available:
            print(f"✅ TimescaleDB extension is available")
            
            # Check if TimescaleDB is already enabled
            cursor.execute("SELECT * FROM pg_extension WHERE extname = 'timescaledb';")
            timescale_enabled = cursor.fetchone()
            
            if timescale_enabled:
                print(f"✅ TimescaleDB extension is enabled")
            else:
                print(f"ℹ️  TimescaleDB extension is available but not enabled yet")
        else:
            print(f"❌ TimescaleDB extension is not available")
            
        cursor.close()
        conn.close()
        
        return True
        
    except psycopg2.Error as e:
        print(f"❌ Connection failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)