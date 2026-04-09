"""MySQL database connection for WP6 Red."""

from datetime import datetime
from typing import Any

import aiomysql
import pandas as pd

# Sensor tables and their measurement columns
SENSOR_TABLES: dict[str, list[str]] = {
    "dendro": ["adc_ch1", "adc_ch2", "adc_ch3"],
    "lht65_e5": ["temp", "hum", "lux"],
    "lht65_ne117": ["temp", "hum", "temp_ext"],
    "s1000": ["temp", "hum", "air_press", "lux", "wind_sp", "wind_dir",
              "rainfall", "pm25", "pm10", "co2"],
    "s2100": ["par"],
    "s2101": ["temp", "hum"],
    "s2103": ["temp", "hum", "co2"],
    "s2107": ["temp_ext"],
    "s31_lb": ["temp_ext", "hum_ext"],
}

# Common columns in all sensor tables (not charted by default)
COMMON_COLUMNS = ["device_id", "received_at", "gateway_id"]

# Common measurements available in all sensor tables
COMMON_MEASUREMENTS = ["battery_pc", "rssi", "snr"]


# Measurement groups - combine related columns into single charts
MEASUREMENT_GROUPS: dict[str, list[str]] = {
    "adc": ["adc_ch1", "adc_ch2", "adc_ch3"], # Dendrometer channels
    "pm": ["pm25", "pm10"],                   # Particulate matter
}


def get_measurements_to_tables() -> dict[str, list[str]]:
    """Get mapping of measurement type to tables that have it.

    Includes individual measurements, groups, and common measurements.
    """
    measurements: dict[str, list[str]] = {}
    all_tables = list(SENSOR_TABLES.keys())

    # Individual measurements
    for table, cols in SENSOR_TABLES.items():
        for col in cols:
            if col not in measurements:
                measurements[col] = []
            measurements[col].append(table)

    # Add groups (find tables that have ALL columns in the group)
    for group_name, group_cols in MEASUREMENT_GROUPS.items():
        tables_with_group = []
        for table, cols in SENSOR_TABLES.items():
            if all(c in cols for c in group_cols):
                tables_with_group.append(table)
        if tables_with_group:
            measurements[group_name] = tables_with_group

    # Add common measurements (available in all sensor tables)
    for col in COMMON_MEASUREMENTS:
        measurements[col] = all_tables

    return measurements


MEASUREMENTS_TO_TABLES = get_measurements_to_tables()


def expand_measurement(measurement: str) -> list[str]:
    """Expand a measurement name to its columns (handles groups)."""
    if measurement in MEASUREMENT_GROUPS:
        return MEASUREMENT_GROUPS[measurement]
    return [measurement]


class MySQLConnection:
    """Async MySQL connection pool manager."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.pool: aiomysql.Pool | None = None

    async def connect(self) -> None:
        """Create connection pool."""
        self.pool = await aiomysql.create_pool(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            db=self.database,
            autocommit=True,
            minsize=1,
            maxsize=5,
        )

    async def close(self) -> None:
        """Close connection pool."""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    async def _fetch_available_sensors(self) -> list[dict[str, Any]]:
        """Query MySQL for sensor tables with device counts and reading counts."""
        if not self.pool:
            raise RuntimeError("Not connected")

        sensors = []
        async with self.pool.acquire() as conn, conn.cursor() as cursor:
            for table, columns in SENSOR_TABLES.items():
                try:
                    # Get device count and total readings
                    await cursor.execute(
                        f"SELECT COUNT(DISTINCT device_id), COUNT(*) FROM {table}"
                    )
                    row = await cursor.fetchone()
                    if row and row[1] > 0:
                        sensors.append({
                            "table": table,
                            "devices": row[0],
                            "readings": row[1],
                            "measurements": columns or ["value"],
                        })
                except Exception:
                    # Table might not exist
                    continue

        return sorted(sensors, key=lambda x: -x["readings"])

    async def get_available_sensors(self) -> list[dict[str, Any]]:
        """Get sensor list (cached via shared sensor summary)."""
        from wp6_data.shared.sensor_summary import get_sensor_summary

        return await get_sensor_summary("red", self._fetch_available_sensors)

    async def get_devices_for_table(self, table: str) -> list[str]:
        """Get list of unique device IDs for a sensor table (derived from cached device list)."""
        if table not in SENSOR_TABLES:
            raise ValueError(f"Unknown table: {table}")

        all_devices = await self.get_all_devices()
        return sorted(
            did for did, info in all_devices.items() if table in info["tables"]
        )

    async def get_readings_by_measurement(
        self,
        measurement: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit_per_table: int = 100000,
    ) -> pd.DataFrame:
        """Fetch readings for a measurement type across all tables that have it.

        Supports measurement groups (e.g., 'adc' expands to adc_ch1, adc_ch2, adc_ch3).

        Returns DataFrame with columns: device, sensor, time, value
        where 'device' is formatted as 'table:device_id' for clarity.
        """
        if not self.pool:
            raise RuntimeError("Not connected")

        if measurement not in MEASUREMENTS_TO_TABLES:
            raise ValueError(f"Unknown measurement: {measurement}")

        tables = MEASUREMENTS_TO_TABLES[measurement]
        columns = expand_measurement(measurement)
        all_records = []

        for table in tables:
            conditions = []
            params: list[Any] = []

            if start:
                conditions.append("received_at >= %s")
                params.append(start)
            if end:
                conditions.append("received_at <= %s")
                params.append(end)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cursor:
                # Order DESC to get most recent data, then reverse for chronological display
                query = f"""
                    SELECT device_id, received_at, {', '.join(columns)}
                    FROM {table}
                    {where_clause}
                    ORDER BY received_at DESC
                    LIMIT {limit_per_table}
                """
                await cursor.execute(query, params)
                rows = list(reversed(await cursor.fetchall()))

            for row in rows:
                for col in columns:
                    if row.get(col) is not None:
                        all_records.append({
                            "device": f"{table}:{row['device_id']}",
                            "sensor": col,
                            "time": row["received_at"],
                            "value": float(row[col]),
                        })

        df = pd.DataFrame(all_records)
        if not df.empty:
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time")
        return df

    async def _fetch_all_devices(self) -> dict[str, dict[str, list[str]]]:
        """Query MySQL for all devices with measurements and reading counts."""
        if not self.pool:
            raise RuntimeError("Not connected")

        devices: dict[str, dict[str, list[str]]] = {}
        async with self.pool.acquire() as conn, conn.cursor() as cursor:
            for table, cols in SENSOR_TABLES.items():
                try:
                    await cursor.execute(
                        f"SELECT device_id, COUNT(*) FROM {table} GROUP BY device_id"
                    )
                    rows = await cursor.fetchall()
                except Exception:
                    continue
                measurements = cols + COMMON_MEASUREMENTS
                for device_id, count in rows:
                    if device_id not in devices:
                        devices[device_id] = {
                            "tables": [], "measurements": [], "readings": 0,
                        }
                    devices[device_id]["tables"].append(table)
                    devices[device_id]["readings"] += count
                    for m in measurements:
                        if m not in devices[device_id]["measurements"]:
                            devices[device_id]["measurements"].append(m)
        return devices

    async def get_all_devices(self) -> dict[str, dict[str, list[str]]]:
        """Get all devices with measurements (cached via shared sensor summary)."""
        from wp6_data.shared.sensor_summary import get_sensor_summary

        return await get_sensor_summary("red:devices", self._fetch_all_devices)

    async def get_readings_for_comparison(
        self,
        device_id: str,
        measurement: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100000,
    ) -> pd.DataFrame:
        """Fetch readings for a device + measurement across all tables that have both.

        Returns DataFrame with columns: device, sensor, time, value.
        """
        if not self.pool:
            raise RuntimeError("Not connected")

        all_records = []
        for table, cols in SENSOR_TABLES.items():
            all_cols = cols + COMMON_MEASUREMENTS
            if measurement not in all_cols:
                continue

            conditions = ["device_id = %s"]
            params: list[Any] = [device_id]
            if start:
                conditions.append("received_at >= %s")
                params.append(start)
            if end:
                conditions.append("received_at <= %s")
                params.append(end)

            where_clause = f"WHERE {' AND '.join(conditions)}"

            async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cursor:
                query = f"""
                    SELECT device_id, received_at, {measurement}
                    FROM {table}
                    {where_clause}
                    ORDER BY received_at DESC
                    LIMIT {limit}
                """
                try:
                    await cursor.execute(query, params)
                except Exception:
                    continue
                rows = list(reversed(await cursor.fetchall()))

            for row in rows:
                if row.get(measurement) is not None:
                    all_records.append({
                        "device": row["device_id"],
                        "sensor": measurement,
                        "time": row["received_at"],
                        "value": float(row[measurement]),
                    })

        df = pd.DataFrame(all_records)
        if not df.empty:
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time")
        return df

    async def get_readings(
        self,
        table: str,
        device_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100000,
    ) -> pd.DataFrame:
        """Fetch readings from a sensor table.

        Returns DataFrame with columns: device, sensor, time, value
        (matching the format used by shared chart functions)
        """
        if not self.pool:
            raise RuntimeError("Not connected")

        if table not in SENSOR_TABLES:
            raise ValueError(f"Unknown table: {table}")

        columns = SENSOR_TABLES[table] or ["battery_pc"]  # Fallback to battery

        # Build query
        conditions = []
        params: list[Any] = []

        if device_id:
            conditions.append("device_id = %s")
            params.append(device_id)
        if start:
            conditions.append("received_at >= %s")
            params.append(start)
        if end:
            conditions.append("received_at <= %s")
            params.append(end)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cursor:
            # Order DESC to get most recent data, then reverse for chronological display
            query = f"""
                    SELECT device_id, received_at, {', '.join(columns)}
                    FROM {table}
                    {where_clause}
                    ORDER BY received_at DESC
                    LIMIT {limit}
                """
            await cursor.execute(query, params)
            rows = list(reversed(await cursor.fetchall()))

        if not rows:
            return pd.DataFrame(columns=["device", "sensor", "time", "value"])

        # Transform to long format for charting (device, sensor, time, value)
        records = []
        for row in rows:
            for col in columns:
                if row.get(col) is not None:
                    records.append({
                        "device": row["device_id"],
                        "sensor": col,
                        "time": row["received_at"],
                        "value": float(row[col]),
                    })

        df = pd.DataFrame(records)
        if not df.empty:
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time")
        return df

    # TODO: i think this can be easily refactored?

    async def get_par_readings(
        self,
        device_ids: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500000,
    ) -> pd.DataFrame:
        """Fetch PAR readings from s2100 table.

        Args:
            device_ids: Optional list of device IDs to filter (e.g., ['s2100-01-par'])
            start: Start datetime filter
            end: End datetime filter
            limit: Maximum records to fetch

        Returns:
            DataFrame with columns: device, sensor, time, value
        """
        if not self.pool:
            raise RuntimeError("Not connected")

        conditions = []
        params: list[Any] = []

        if device_ids:
            placeholders = ", ".join(["%s"] * len(device_ids))
            conditions.append(f"device_id IN ({placeholders})")
            params.extend(device_ids)
        if start:
            conditions.append("received_at >= %s")
            params.append(start)
        if end:
            conditions.append("received_at <= %s")
            params.append(end)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cursor:
            query = f"""
                SELECT device_id, received_at, par
                FROM s2100
                {where_clause}
                ORDER BY received_at DESC
                LIMIT {limit}
            """
            await cursor.execute(query, params)
            rows = list(reversed(await cursor.fetchall()))

        if not rows:
            return pd.DataFrame(columns=["device", "sensor", "time", "value"])

        records = []
        for row in rows:
            if row.get("par") is not None:
                records.append({
                    "device": row["device_id"],
                    "sensor": "par",
                    "time": row["received_at"],
                    "value": float(row["par"]),
                })

        df = pd.DataFrame(records)
        if not df.empty:
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time")
        return df

    async def get_weather_station_readings(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500000,
    ) -> pd.DataFrame:
        """Fetch lux readings from s1000 weather station.

        Args:
            start: Start datetime filter
            end: End datetime filter
            limit: Maximum records to fetch

        Returns:
            DataFrame with columns: device, time, lux, temp, hum
        """
        if not self.pool:
            raise RuntimeError("Not connected")

        conditions = []
        params: list[Any] = []

        if start:
            conditions.append("received_at >= %s")
            params.append(start)
        if end:
            conditions.append("received_at <= %s")
            params.append(end)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cursor:
            query = f"""
                SELECT device_id, received_at, lux, temp, hum
                FROM s1000
                {where_clause}
                ORDER BY received_at DESC
                LIMIT {limit}
            """
            await cursor.execute(query, params)
            rows = list(reversed(await cursor.fetchall()))

        if not rows:
            return pd.DataFrame(columns=["device", "time", "lux", "temp", "hum"])

        records = []
        for row in rows:
            if row.get("lux") is not None:
                records.append({
                    "device": row["device_id"],
                    "time": row["received_at"],
                    "lux": float(row["lux"]),
                    "temp": float(row["temp"]) if row.get("temp") else None,
                    "hum": float(row["hum"]) if row.get("hum") else None,
                })

        df = pd.DataFrame(records)
        if not df.empty:
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time")
        return df
