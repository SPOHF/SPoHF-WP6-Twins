#!/usr/bin/env python3
"""
SPoHF Yookr API Data Ingestion Script
=====================================
Fetches sensor data from Yookr API and populates TimescaleDB measurements table.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass

import httpx
import psycopg2
from psycopg2.extras import execute_batch
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class SensorData:
    sensor_id: str
    timestamp: datetime
    value: float
    raw_data: Dict[str, Any]

@dataclass
class APIConfig:
    base_url: str
    token: str
    page_size: int = 1000
    timeout: int = 30
    max_retries: int = 3
    request_delay: float = 0.1

@dataclass
class DBConfig:
    host: str = 'localhost'
    port: int = 5432
    database: str = 'sensordb'
    user: str = 'postgres'
    password: str = 'localdevpassword'

class YookrAPIClient:
    def __init__(self, config: APIConfig):
        self.config = config
        self.base_url = config.base_url.rstrip('/')
        self.headers = {
            'Authorization': f'Bearer {config.token}',
            'Accept': 'application/json'
        }
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
    )
    async def _fetch_page(self, client: httpx.AsyncClient, sensor_id: str, params: Dict) -> List[Dict]:
        url = f"{self.base_url}/sensor/{sensor_id}/read"
        response = await client.get(url, params=params, headers=self.headers, timeout=self.config.timeout)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else data.get('results', data.get('data', []))
    
    def _parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        if not timestamp_str:
            return None
        try:
            if timestamp_str.endswith('Z'):
                timestamp_str = timestamp_str[:-1] + '+00:00'
            return datetime.fromisoformat(timestamp_str)
        except ValueError:
            return None
    
    def _parse_measurements(self, sensor_id: str, raw_data: List[Dict]) -> List[SensorData]:
        measurements = []
        for item in raw_data:
            try:
                timestamp = self._parse_timestamp(item.get('datetimeMeasure'))
                value = float(item.get('value'))
                if timestamp and value is not None:
                    measurements.append(SensorData(sensor_id, timestamp, value, item))
            except (ValueError, TypeError):
                continue
        return measurements
    
    async def fetch_data(self, sensor_id: str, start_time: datetime, end_time: datetime, 
                        backwards: bool = False, existing_timestamps: set = None) -> Tuple[List[SensorData], bool]:
        """Fetch data for sensor. If backwards=True, stops when duplicates found."""
        measurements = []
        hit_duplicates = False
        current_time = end_time if backwards else start_time
        
        async with httpx.AsyncClient() as client:
            while True:
                # Format timestamps to match API expectation (Z format with 3-digit microseconds)
                gte_time = start_time.strftime('%Y-%m-%dT%H:%M:%S.') + f"{start_time.microsecond // 1000:03d}Z"
                lt_time = (current_time if backwards else end_time).strftime('%Y-%m-%dT%H:%M:%S.') + f"{((current_time if backwards else end_time).microsecond // 1000):03d}Z"
                
                params = {
                    'gt': gte_time,
                    'gte': gte_time,
                    'limit': self.config.page_size,
                    'lt': lt_time,
                    'lte': lt_time,
                    'order': 'datetimeMeasure DESC' if backwards else 'datetimeMeasure ASC'
                }
                
                try:
                    page_data = await self._fetch_page(client, sensor_id, params)
                    if not page_data:
                        break
                    
                    page_measurements = self._parse_measurements(sensor_id, page_data)
                    if not page_measurements:
                        break
                    
                    if backwards and existing_timestamps:
                        # Check for duplicates when going backwards
                        new_measurements = []
                        duplicate_count = 0
                        
                        for m in page_measurements:
                            if m.timestamp in existing_timestamps:
                                duplicate_count += 1
                            else:
                                new_measurements.append(m)
                        
                        measurements.extend(new_measurements)
                        
                        # Stop if significant duplicates found
                        if duplicate_count >= min(50, len(page_measurements) * 0.5):
                            logger.debug(f"🔄 Hit duplicates for {sensor_id}: {duplicate_count}/{len(page_measurements)} duplicates")
                            hit_duplicates = True
                            break
                        
                        logger.debug(f"➕ Added {len(new_measurements)} new measurements (skipped {duplicate_count} duplicates)")
                    else:
                        measurements.extend(page_measurements)
                        logger.debug(f"➕ Added {len(page_measurements)} measurements")
                    
                    # Check for more pages
                    if len(page_data) < self.config.page_size:
                        break
                    
                    # Update time for next page
                    if backwards:
                        earliest = page_data[-1].get('datetimeMeasure')
                        earliest_dt = self._parse_timestamp(earliest)
                        if earliest_dt:
                            current_time = earliest_dt - timedelta(seconds=1)
                        else:
                            break
                    else:
                        latest = page_data[-1].get('datetimeMeasure')
                        latest_dt = self._parse_timestamp(latest)
                        if latest_dt:
                            current_time = latest_dt + timedelta(seconds=1)
                        else:
                            break
                    
                    # Safety check
                    if len(measurements) > 100000:
                        break
                        
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        break
                    elif e.response.status_code == 429:
                        # Rate limited - wait longer
                        await asyncio.sleep(5)
                        continue
                    raise
        
        return measurements, hit_duplicates

class TimescaleDBManager:
    def __init__(self, config: DBConfig):
        self.config = config
    
    def connect(self):
        return psycopg2.connect(
            host=self.config.host, port=self.config.port, database=self.config.database,
            user=self.config.user, password=self.config.password
        )
    
    def get_sensor_ids(self) -> set:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT sensor_id FROM sensors")
                return {str(row[0]) for row in cursor.fetchall()}
    
    def has_data(self, sensor_id: str) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM measurements WHERE sensor_id = %s LIMIT 1", (sensor_id,))
                return cursor.fetchone() is not None
    
    def get_existing_timestamps(self, sensor_id: str, start: datetime, end: datetime) -> set:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT timestamp FROM measurements 
                    WHERE sensor_id = %s AND timestamp >= %s AND timestamp <= %s
                """, (sensor_id, start, end))
                return {row[0] for row in cursor.fetchall()}
    
    def insert_measurements(self, measurements: List[SensorData]) -> int:
        if not measurements:
            return 0
        
        valid_sensor_ids = self.get_sensor_ids()
        valid_measurements = [m for m in measurements if m.sensor_id in valid_sensor_ids]
        
        if not valid_measurements:
            return 0
        
        insert_data = [(m.timestamp, m.sensor_id, m.value) for m in valid_measurements]
        insert_query = """
            INSERT INTO measurements (timestamp, sensor_id, value) VALUES (%s, %s, %s)
            ON CONFLICT (timestamp, sensor_id) DO UPDATE SET value = EXCLUDED.value
        """
        
        with self.connect() as conn:
            with conn.cursor() as cursor:
                execute_batch(cursor, insert_query, insert_data, page_size=1000)
                return len(valid_measurements)

class YookrDataIngestion:
    def __init__(self, api_config: APIConfig, db_config: DBConfig):
        self.api_client = YookrAPIClient(api_config)
        self.db_manager = TimescaleDBManager(db_config)
    
    async def sync_sensor(self, sensor_id: str) -> int:
        """Sync a single sensor using appropriate strategy"""
        has_data = self.db_manager.has_data(sensor_id)
        end_time = datetime.now(timezone.utc)
        
        if not has_data:
            # Initial sync: forward from beginning date
            beginning_date_str = os.getenv('SYNC_BEGINNING_DATE', '2024-01-01')
            try:
                start_time = datetime.strptime(beginning_date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            except ValueError:
                # Fallback: if date format invalid, use 30 days back
                start_time = end_time - timedelta(days=30)
                logger.warning(f"Invalid SYNC_BEGINNING_DATE format, using 30 days fallback")
            
            measurements, _ = await self.api_client.fetch_data(sensor_id, start_time, end_time, backwards=False)
        else:
            # Incremental sync: backwards from now until duplicates
            start_time = end_time - timedelta(days=365)  # Look back up to 1 year max
            existing_timestamps = self.db_manager.get_existing_timestamps(sensor_id, start_time, end_time)
            measurements, hit_duplicates = await self.api_client.fetch_data(
                sensor_id, start_time, end_time, backwards=True, existing_timestamps=existing_timestamps
            )
        
        if measurements:
            return self.db_manager.insert_measurements(measurements)
        return 0
    
    async def sync_all_sensors(self, sensor_ids: Optional[List[str]] = None) -> Dict[str, int]:
        """Sync all sensors"""
        if sensor_ids is None:
            sensor_ids = list(self.db_manager.get_sensor_ids())
        
        results = {}
        total_measurements = 0
        successful_sensors = 0
        failed_sensors = 0
        
        logger.info(f"Starting sync of {len(sensor_ids)} sensors")
        
        for i, sensor_id in enumerate(sensor_ids, 1):
            try:
                count = await self.sync_sensor(sensor_id)
                results[sensor_id] = count
                total_measurements += count
                if count > 0:
                    successful_sensors += 1
                    logger.info(f"Updated sensor {sensor_id} with {count} entries")
                
                # Brief delay to be API-friendly
                await asyncio.sleep(self.api_client.config.request_delay)
                
            except Exception as e:
                logger.error(f"Failed to sync sensor {sensor_id}: {e}")
                results[sensor_id] = 0
                failed_sensors += 1
        
        logger.info(f"Sync complete: {successful_sensors} successful, {failed_sensors} failed, {total_measurements} total measurements")
        return results

def load_config() -> Tuple[APIConfig, DBConfig]:
    load_dotenv('.env.yookr')
    
    api_config = APIConfig(
        base_url=os.getenv('YOOKR_API_BASE_URL', 'https://api.yookr.org'),
        token=os.getenv('YOOKR_API_TOKEN', ''),
        page_size=int(os.getenv('YOOKR_PAGE_SIZE', '1000')),
        timeout=int(os.getenv('YOOKR_TIMEOUT', '30')),
        max_retries=int(os.getenv('YOOKR_MAX_RETRIES', '3')),
        request_delay=float(os.getenv('YOOKR_REQUEST_DELAY', '0.1'))
    )
    
    db_config = DBConfig(
        host=os.getenv('DB_HOST', 'localhost'),
        port=int(os.getenv('DB_PORT', '5432')),
        database=os.getenv('DB_NAME', 'sensordb'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'localdevpassword')
    )
    
    return api_config, db_config

async def main():
    logger.info("Starting Yookr API data ingestion")
    
    api_config, db_config = load_config()
    
    if not api_config.token:
        logger.error("YOOKR_API_TOKEN environment variable is required!")
        return
    
    ingestion = YookrDataIngestion(api_config, db_config)
    await ingestion.sync_all_sensors()

if __name__ == "__main__":
    asyncio.run(main())