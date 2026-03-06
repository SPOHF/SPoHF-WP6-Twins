#!/usr/bin/env python3

"""Create TimescaleDB schema for SPoHF sensor data."""

import psycopg2
import sys

# Database connection settings
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "sensordb"
DB_USER = "postgres"
DB_PASSWORD = "localdevpassword"

def create_schema():
    """Create the sensors and measurements tables."""
    
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
        
        print("🏗️  Creating TimescaleDB schema for sensor data...")
        
        # Create sensors table
        print("   Creating sensors table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sensors (
                sensor_id UUID PRIMARY KEY,
                device_id UUID NOT NULL,
                sensor_tag VARCHAR(50) NOT NULL,
                device_name VARCHAR(100),
                unit VARCHAR(20),
                metadata JSONB
            );
        """)
        
        # Create measurements table
        print("   Creating measurements table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS measurements (
                timestamp TIMESTAMPTZ NOT NULL,
                sensor_id UUID NOT NULL REFERENCES sensors(sensor_id),
                value NUMERIC NOT NULL,
                PRIMARY KEY (timestamp, sensor_id)
            );
        """)
        
        # Enable TimescaleDB hypertable on measurements
        print("   Converting measurements to TimescaleDB hypertable...")
        try:
            cursor.execute("SELECT create_hypertable('measurements', 'timestamp');")
        except psycopg2.Error as e:
            if "already a hypertable" in str(e):
                print("   (measurements is already a hypertable)")
            else:
                raise
        
        # Create indexes
        print("   Creating indexes...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_measurements_sensor_time 
            ON measurements (sensor_id, timestamp DESC);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_measurements_time 
            ON measurements (timestamp DESC);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sensors_tag 
            ON sensors (sensor_tag);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sensors_device 
            ON sensors (device_id);
        """)
        
        # Commit changes
        conn.commit()
        
        print("✅ Schema created successfully!")
        
        # Show table info
        cursor.execute("""
            SELECT table_name, column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name IN ('sensors', 'measurements')
            ORDER BY table_name, ordinal_position;
        """)
        
        print("\n📊 Schema structure:")
        current_table = ""
        for row in cursor.fetchall():
            table, column, data_type = row
            if table != current_table:
                print(f"\n{table}:")
                current_table = table
            print(f"  - {column}: {data_type}")
        
        cursor.close()
        conn.close()
        
        return True
        
    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


if __name__ == "__main__":
    print("🚀 SPoHF TimescaleDB Schema Setup")
    print("=" * 50)
    
    # Create schema
    if create_schema():
        print("\n🎉 Schema setup complete!")
    else:
        print("❌ Schema setup failed!")
        sys.exit(1)