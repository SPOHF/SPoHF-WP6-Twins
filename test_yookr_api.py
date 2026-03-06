#!/usr/bin/env python3
"""
Yookr API Connection Test
========================
Simple test script to validate your API credentials and connection.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv('.env.yookr')

async def test_api_connection():
    """Test basic API connectivity"""
    
    base_url = os.getenv('YOOKR_API_BASE_URL', 'https://api.yookr.org')
    token = os.getenv('YOOKR_API_TOKEN', '')
    
    print("🔍 Testing Yookr API Connection")
    print("=" * 40)
    print(f"API Base URL: {base_url}")
    print(f"Token: {'✅ Set' if token else '❌ Missing'}")
    
    if not token:
        print("\n❌ Error: YOOKR_API_TOKEN not set!")
        print("Please set your bearer token in .env.yookr file")
        return False
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json'
    }
    
    # Get a test sensor ID from database
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='localhost', port=5432, database='sensordb',
            user='postgres', password='localdevpassword'
        )
        
        with conn.cursor() as cursor:
            cursor.execute("SELECT sensor_id FROM sensors LIMIT 1")
            result = cursor.fetchone()
            
            if not result:
                print("❌ No sensors found in database!")
                return False
                
            test_sensor_id = str(result[0])
            print(f"Test sensor ID: {test_sensor_id}")
            
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False
    
    # Test the actual Yookr API endpoint structure
    async with httpx.AsyncClient() as client:
        endpoint = f"sensor/{test_sensor_id}/read"
        url = f"{base_url.rstrip('/')}/{endpoint}"
        
        # Test with minimal parameters
        params = {
            'limit': 5,  # Just get a few records
            'order': 'datetimeMeasure DESC'  # Get recent data
        }
        
        print(f"\n🔗 Testing endpoint: {endpoint}")
        print(f"Full URL: {url}")
        
        try:
            response = await client.get(url, headers=headers, params=params, timeout=10)
            
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    print(f"✅ API connection successful!")
                    print(f"Response type: {type(data)}")
                    
                    if isinstance(data, list):
                        print(f"Found {len(data)} measurements")
                        if data:
                            # Show structure of first measurement
                            sample = data[0]
                            print(f"Sample measurement structure:")
                            for key, value in sample.items():
                                print(f"   {key}: {type(value).__name__} = {value}")
                    
                    return True
                    
                except Exception as e:
                    print(f"   Response parsing error: {e}")
                    
            elif response.status_code == 401:
                print(f"❌ Authentication failed - check your token")
            elif response.status_code == 404:
                print(f"❌ Sensor not found or endpoint incorrect")
            else:
                print(f"❌ Unexpected status: {response.status_code}")
                print(f"Response: {response.text[:200]}")
                
        except httpx.ConnectError:
            print(f"❌ Connection failed - check URL: {base_url}")
        except httpx.TimeoutException:
            print(f"❌ Request timed out")
        except Exception as e:
            print(f"❌ Error: {e}")
    
    return False

async def test_sensor_data():
    """Test fetching data for a specific sensor with date range"""
    
    # Get a sensor ID from our database  
    import psycopg2
    
    try:
        conn = psycopg2.connect(
            host='localhost',
            port=5432, 
            database='sensordb',
            user='postgres',
            password='localdevpassword'
        )
        
        with conn.cursor() as cursor:
            cursor.execute("SELECT sensor_id, sensor_tag FROM sensors LIMIT 1")
            result = cursor.fetchone()
            
            if result:
                sensor_id, sensor_tag = result
                print(f"\n🔬 Testing sensor data fetch")
                print(f"Sensor ID: {sensor_id}")
                print(f"Sensor Type: {sensor_tag}")
                
                # Try to fetch recent data for this sensor
                base_url = os.getenv('YOOKR_API_BASE_URL')
                token = os.getenv('YOOKR_API_TOKEN')
                
                headers = {'Authorization': f'Bearer {token}'}
                
                # Use Yookr API date range parameters
                end_time = datetime.now(timezone.utc)
                start_time = end_time - timedelta(days=30)  # Last 30 days
                
                # Yookr API endpoint structure: /sensor/{sensorId}/read
                endpoint = f"sensor/{sensor_id}/read"
                url = f"{base_url.rstrip('/')}/{endpoint}"
                
                # Yookr API parameters
                params = {
                    'gte': start_time.isoformat(),           # greater than or equal
                    'lt': end_time.isoformat(),              # less than  
                    'limit': 10,                             # small test sample
                    'order': 'datetimeMeasure DESC'          # newest first
                }
                
                print(f"\n   URL: {url}")
                print(f"   Parameters: {params}")
                
                async with httpx.AsyncClient() as client:
                    try:
                        response = await client.get(
                            url,
                            headers=headers,
                            params=params,
                            timeout=15
                        )
                        
                        print(f"   Status: {response.status_code}")
                        
                        if response.status_code == 200:
                            data = response.json()
                            print(f"   ✅ Got data: {type(data)}")
                            
                            if isinstance(data, list):
                                print(f"   Found {len(data)} measurements")
                                
                                if data:
                                    # Show first measurement structure
                                    sample = data[0]
                                    print(f"   Sample measurement:")
                                    print(f"      sensorId: {sample.get('sensorId')}")
                                    print(f"      datetimeMeasure: {sample.get('datetimeMeasure')}")
                                    print(f"      value: {sample.get('value')}")
                                    print(f"      metadata: {sample.get('metadata')}")
                                
                                return True
                            else:
                                print(f"   Unexpected response format: {data}")
                                
                        elif response.status_code == 404:
                            print(f"   ❌ Sensor not found")
                        elif response.status_code == 401:
                            print(f"   ❌ Authentication failed")
                        else:
                            print(f"   ❌ Error: {response.status_code}")
                            print(f"   Response: {response.text[:200]}")
                                
                    except Exception as e:
                        print(f"   Error: {e}")
            else:
                print(f"\n⚠️  No sensors found in database")
                
    except Exception as e:
        print(f"\n❌ Database connection failed: {e}")
    
    return False

async def main():
    """Main test runner"""
    print("🚀 Yookr API Test Suite")
    print("=" * 50)
    
    # Test 1: Basic connectivity
    connection_ok = await test_api_connection()
    
    if connection_ok:
        print(f"\n" + "=" * 50)
        # Test 2: Sensor data fetch
        await test_sensor_data()
    
    print(f"\n" + "=" * 50)
    print("🎯 Next Steps:")
    if not connection_ok:
        print("1. ❌ Fix API connection issues first")
        print("2. Check your YOOKR_API_TOKEN in .env.yookr")
        print("3. Verify the API base URL") 
    else:
        print("1. ✅ API connection working!")
        print("2. Run: python yookr_api_ingestion.py")
        print("3. Monitor the logs for data ingestion progress")

if __name__ == "__main__":
    asyncio.run(main())