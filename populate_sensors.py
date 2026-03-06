#!/usr/bin/env python3
"""
SPoHF TimescaleDB Sensor Population Script
==========================================
Populates the sensors table with metadata from sensor_overview_SPoHF.csv
Includes unit mappings and basic metadata for each sensor type.
"""

import csv
import json
from datetime import datetime
import psycopg2
from psycopg2.extras import Json

# Database connection parameters
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'sensordb',
    'user': 'postgres',
    'password': 'localdevpassword'
}

# Sensor type to unit mapping
SENSOR_UNITS = {
    'soil_pH': 'pH',
    'soilTemperature': '°C',
    'soilMoisture': '%',
    'soilConductivity': 'μS/cm',
    'leaf_moisture': '%',
    'leaf_temperature': '°C',
    'humidity': '%',
    'temperature': '°C',
    'airTemperature': '°C',
    'atmosphericPressure': 'hPa',
    'battery': 'V',
    'inputVoltage': 'V',
    'lightningStrikes': 'count',
    'precipitation': 'mm',
    'solarRadiation': 'W/m²',
    'vaporPressure': 'hPa',
    'windDirection': '°',
    'windSpeed': 'm/s',
    'windspeedGust': 'm/s',
    'par': 'μmol/m²/s'
}

# Sensor type metadata
SENSOR_METADATA = {
    'soil_pH': {
        'category': 'soil',
        'description': 'Soil pH level measurement',
        'range': {'min': 0, 'max': 14},
        'optimal_range': {'min': 5.5, 'max': 6.5},
        'frequency': 'hourly'
    },
    'soilTemperature': {
        'category': 'soil',
        'description': 'Soil temperature measurement',
        'range': {'min': -20, 'max': 50},
        'frequency': 'hourly'
    },
    'soilMoisture': {
        'category': 'soil',
        'description': 'Soil volumetric water content',
        'range': {'min': 0, 'max': 100},
        'optimal_range': {'min': 20, 'max': 40},
        'frequency': 'hourly'
    },
    'soilConductivity': {
        'category': 'soil',
        'description': 'Soil electrical conductivity',
        'range': {'min': 0, 'max': 5000},
        'frequency': 'hourly'
    },
    'leaf_moisture': {
        'category': 'plant',
        'description': 'Leaf moisture content',
        'range': {'min': 0, 'max': 100},
        'frequency': 'hourly'
    },
    'leaf_temperature': {
        'category': 'plant',
        'description': 'Leaf temperature measurement',
        'range': {'min': -10, 'max': 50},
        'frequency': 'hourly'
    },
    'humidity': {
        'category': 'environment',
        'description': 'Relative humidity',
        'range': {'min': 0, 'max': 100},
        'frequency': 'hourly'
    },
    'temperature': {
        'category': 'environment',
        'description': 'Ambient temperature',
        'range': {'min': -30, 'max': 50},
        'frequency': 'hourly'
    },
    'airTemperature': {
        'category': 'weather',
        'description': 'Air temperature from weather station',
        'range': {'min': -30, 'max': 50},
        'frequency': 'every 15 minutes'
    },
    'atmosphericPressure': {
        'category': 'weather',
        'description': 'Atmospheric pressure',
        'range': {'min': 900, 'max': 1100},
        'frequency': 'every 15 minutes'
    },
    'battery': {
        'category': 'system',
        'description': 'Battery voltage level',
        'range': {'min': 0, 'max': 15},
        'frequency': 'every 15 minutes'
    },
    'inputVoltage': {
        'category': 'system',
        'description': 'Input voltage level',
        'range': {'min': 0, 'max': 15},
        'frequency': 'every 15 minutes'
    },
    'lightningStrikes': {
        'category': 'weather',
        'description': 'Number of lightning strikes detected',
        'range': {'min': 0, 'max': None},
        'frequency': 'event-based'
    },
    'precipitation': {
        'category': 'weather',
        'description': 'Precipitation amount',
        'range': {'min': 0, 'max': None},
        'frequency': 'every 15 minutes'
    },
    'solarRadiation': {
        'category': 'weather',
        'description': 'Solar radiation intensity',
        'range': {'min': 0, 'max': 1500},
        'frequency': 'every 15 minutes'
    },
    'vaporPressure': {
        'category': 'weather',
        'description': 'Water vapor pressure',
        'range': {'min': 0, 'max': 50},
        'frequency': 'every 15 minutes'
    },
    'windDirection': {
        'category': 'weather',
        'description': 'Wind direction in degrees from north',
        'range': {'min': 0, 'max': 360},
        'frequency': 'every 15 minutes'
    },
    'windSpeed': {
        'category': 'weather',
        'description': 'Wind speed',
        'range': {'min': 0, 'max': None},
        'frequency': 'every 15 minutes'
    },
    'windspeedGust': {
        'category': 'weather',
        'description': 'Wind gust speed',
        'range': {'min': 0, 'max': None},
        'frequency': 'every 15 minutes'
    },
    'par': {
        'category': 'environment',
        'description': 'Photosynthetically Active Radiation',
        'range': {'min': 0, 'max': 3000},
        'frequency': 'hourly'
    }
}

def connect_db():
    """Connect to TimescaleDB"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return None

def load_sensor_data():
    """Load sensor data from CSV file"""
    sensors = []
    try:
        with open('sensor_overview_SPoHF.csv', 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                sensors.append(row)
        print(f"📁 Loaded {len(sensors)} sensors from CSV")
        return sensors
    except Exception as e:
        print(f"❌ Failed to load CSV: {e}")
        return []

def populate_sensors_table(conn, sensors):
    """Populate the sensors table with sensor metadata"""
    cursor = conn.cursor()
    
    insert_query = """
    INSERT INTO sensors (sensor_id, device_id, sensor_tag, device_name, unit, metadata, created_at, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (sensor_id) DO UPDATE SET
        device_id = EXCLUDED.device_id,
        sensor_tag = EXCLUDED.sensor_tag,
        device_name = EXCLUDED.device_name,
        unit = EXCLUDED.unit,
        metadata = EXCLUDED.metadata,
        updated_at = EXCLUDED.updated_at
    """
    
    successfully_inserted = 0
    errors = []
    
    for sensor in sensors:
        try:
            sensor_id = sensor['sensor_id']
            device_id = sensor['device_id']
            sensor_tag = sensor['sensor_tag']
            device_name = sensor['device_name']
            
            # Get unit for this sensor type
            unit = SENSOR_UNITS.get(sensor_tag, 'unknown')
            
            # Get metadata for this sensor type
            metadata = SENSOR_METADATA.get(sensor_tag, {
                'category': 'unknown',
                'description': f'Unknown sensor type: {sensor_tag}',
                'frequency': 'unknown'
            })
            
            # Add device-specific metadata
            metadata['device_name'] = device_name
            metadata['sensor_tag'] = sensor_tag
            
            now = datetime.utcnow()
            
            cursor.execute(insert_query, (
                sensor_id,
                device_id,
                sensor_tag,
                device_name,
                unit,
                Json(metadata),
                now,
                now
            ))
            
            successfully_inserted += 1
            
        except Exception as e:
            errors.append(f"Failed to insert sensor {sensor.get('sensor_id', 'unknown')}: {e}")
    
    conn.commit()
    cursor.close()
    
    return successfully_inserted, errors

def main():
    print("🚀 SPoHF Sensor Metadata Population")
    print("=" * 50)
    
    # Connect to database
    conn = connect_db()
    if not conn:
        return
    
    # Load sensor data from CSV
    sensors = load_sensor_data()
    if not sensors:
        conn.close()
        return
    
    # Populate sensors table
    print("📊 Populating sensors table...")
    success_count, errors = populate_sensors_table(conn, sensors)
    
    # Report results
    print(f"\n✅ Successfully inserted/updated {success_count} sensors")
    
    if errors:
        print(f"\n⚠️  {len(errors)} errors occurred:")
        for error in errors[:5]:  # Show first 5 errors
            print(f"   • {error}")
        if len(errors) > 5:
            print(f"   ... and {len(errors) - 5} more errors")
    
    # Show summary by sensor type
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sensor_tag, unit, COUNT(*) as count 
        FROM sensors 
        GROUP BY sensor_tag, unit 
        ORDER BY count DESC
    """)
    
    print(f"\n📈 Sensor summary:")
    for sensor_tag, unit, count in cursor.fetchall():
        print(f"   • {sensor_tag:20} ({unit:10}): {count:2} sensors")
    
    cursor.close()
    conn.close()
    
    print(f"\n🎉 Sensor metadata population complete!")
    print(f"Your TimescaleDB now contains {success_count} sensors with complete metadata")

if __name__ == "__main__":
    main()