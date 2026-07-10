"""MySQL database connection for WP6 Red."""

import asyncio
import functools
import re
from datetime import datetime
from typing import Any

import aiomysql
import pandas as pd
import structlog
from pymysql.err import InterfaceError, OperationalError

logger = structlog.get_logger()

# MySQL "connection lost/gone" codes worth a transparent retry — idle pooled
# connections can be dropped by the server or a proxy ("reset by peer").
_RETRYABLE_MYSQL_CODES = frozenset({2006, 2013, 2055})
# Recycle pooled connections older than this so we rarely hand out a stale one
# (kept under typical server/proxy idle timeouts).
POOL_RECYCLE_SECONDS = 280


def _retry_on_disconnect(retries: int = 2, delay: float = 0.5):
    """Retry an async DB read when the server drops the connection.

    Retries only on connection-lost codes; the methods here are idempotent
    SELECTs, so a re-run is safe. A dropped connection is discarded by the pool
    on release, so the retry acquires a fresh one.
    """
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            for attempt in range(retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except (OperationalError, InterfaceError) as exc:
                    code = exc.args[0] if exc.args else None
                    if code not in _RETRYABLE_MYSQL_CODES or attempt == retries:
                        raise
                    logger.warning(
                        "mysql_connection_lost_retry",
                        attempt=attempt + 1, code=code, method=fn.__name__,
                    )
                    await asyncio.sleep(delay)
        return wrapper
    return decorator

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


# ── Multi-height "wire sensor" table ──
# A single physical wire device reports four measurement types at five heights.
# The table is wide: 20 value columns named ``<measurement><height>`` — e.g.
# ``par1``..``par5``, ``co21``..``co25``. This is the external table's schema (a
# fixed structural fact, like SENSOR_TABLES above), not tunable config.
WIRE_SENSORS_TABLE = "wire_sensors"
WIRE_SENSOR_MEASUREMENTS = ["par", "temp", "hum", "co2"]
WIRE_SENSOR_HEIGHTS = [1, 2, 3, 4, 5]

# A radiation sensor hangs *above* H1 — one per wire, not one per height — so the
# table carries a single unindexed ``rad`` column rather than ``rad1``..``rad5``.
# Surfacing it as a virtual height 0 keeps it inside the ``-hN`` naming rule the
# provider already parses, instead of inventing a second one. See CONTEXT
# "Solar radiation". WP1 has yet to populate the column.
WIRE_RADIATION_MEASUREMENT = "rad"
WIRE_RADIATION_HEIGHT = 0

# Every virtual device on a wire: the radiation level above, then the five
# measured levels below it, top to bottom.
WIRE_DEVICE_HEIGHTS = [WIRE_RADIATION_HEIGHT, *WIRE_SENSOR_HEIGHTS]


def wire_height_measurements(height: int) -> list[str]:
    """The measurements a given virtual height reports."""
    if height == WIRE_RADIATION_HEIGHT:
        return [WIRE_RADIATION_MEASUREMENT]
    return list(WIRE_SENSOR_MEASUREMENTS)


def wire_column(measurement: str, height: int) -> str:
    """Wide-table column for a (measurement, height) — ``'par3'``, or bare ``'rad'``."""
    if height == WIRE_RADIATION_HEIGHT:
        return measurement
    return f"{measurement}{height}"


def wire_value_columns() -> list[str]:
    """Every wide value column: the 20 height-indexed ones plus ``rad``."""
    return [
        wire_column(measurement, height)
        for height in WIRE_DEVICE_HEIGHTS
        for measurement in wire_height_measurements(height)
    ]


def wire_device_id(physical_device_id: str, height: int) -> str:
    """Virtual per-height device id, e.g. ('WS_01_01', 3) -> 'WS_01_01-h3'.

    Each height is surfaced as its own device (see ADR 0001), so the wide row's
    physical id plus a height index becomes the ``(device, sensor)`` identity the
    rest of the platform speaks.
    """
    return f"{physical_device_id}-h{height}"


def wire_height_from_device(device_id: str) -> int | None:
    """Inverse of :func:`wire_device_id` — pull the height out of a ``-hN`` id."""
    match = re.search(r"-h(\d+)$", device_id)
    return int(match.group(1)) if match else None


def wire_physical_id(device_id: str) -> str:
    """Physical wire id behind a virtual device, e.g. 'WS_01_01-h3' -> 'WS_01_01'."""
    return re.sub(r"-h\d+$", "", device_id)


def unpivot_wire_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten wide ``wire_sensors`` rows into tidy long records.

    Each input row carries up to 20 height-indexed value columns; this emits one
    record per populated ``(measurement, height)`` cell. Empty cells (``None``)
    are skipped, so a height that never reports simply produces no points rather
    than a fake zero line. Each height becomes its own virtual ``device``.

    Returns records with keys: device, height, measurement, time, value.
    """
    records: list[dict[str, Any]] = []
    for row in rows:
        physical_id = row.get("device_id", "")
        for height in WIRE_DEVICE_HEIGHTS:
            for measurement in wire_height_measurements(height):
                value = row.get(wire_column(measurement, height))
                if value is not None:
                    records.append({
                        "device": wire_device_id(physical_id, height),
                        "height": height,
                        "measurement": measurement,
                        "time": row["received_at"],
                        "value": float(value),
                    })
    return records


def split_wire_rows_by_height(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group wide ``wire_sensors`` rows into per-height-device CSV records.

    Each source row becomes one record per height, carrying that height's four
    measurements as columns — the shape the other per-device exports use.

    Unlike :func:`unpivot_wire_rows`, this preserves source-row identity rather
    than going long. ``received_at`` is the relay's insert time and is *not*
    unique: bursts of genuinely different readings share one second. Keying
    output on the row, not the timestamp, keeps those readings distinct instead
    of collapsing them into an average.

    Returns ``{virtual_device_id: [{received_at, par, temp, hum, co2}, ...]}``,
    omitting heights that reported nothing. The radiation level (height 0) yields
    a single ``rad`` column instead of the four measurements.
    """
    by_device: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        physical_id = row.get("device_id", "")
        for height in WIRE_DEVICE_HEIGHTS:
            values = {
                measurement: row.get(wire_column(measurement, height))
                for measurement in wire_height_measurements(height)
            }
            if all(value is None for value in values.values()):
                continue
            device_id = wire_device_id(physical_id, height)
            by_device.setdefault(device_id, []).append({
                "received_at": row["received_at"],
                **values,
            })
    return by_device


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
            pool_recycle=POOL_RECYCLE_SECONDS,
        )

    async def close(self) -> None:
        """Close connection pool."""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    @_retry_on_disconnect()
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

    @_retry_on_disconnect()
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

    @_retry_on_disconnect()
    async def _fetch_all_devices(self) -> dict[str, dict[str, Any]]:
        """Query MySQL for all devices with measurements, counts, last-seen."""
        if not self.pool:
            raise RuntimeError("Not connected")

        devices: dict[str, dict[str, Any]] = {}
        async with self.pool.acquire() as conn, conn.cursor() as cursor:
            for table, cols in SENSOR_TABLES.items():
                try:
                    await cursor.execute(
                        f"SELECT device_id, COUNT(*), MAX(received_at) "
                        f"FROM {table} GROUP BY device_id",
                    )
                    rows = await cursor.fetchall()
                except Exception:
                    continue
                measurements = cols + COMMON_MEASUREMENTS
                for device_id, count, last_seen in rows:
                    entry = devices.setdefault(device_id, {
                        "tables": [], "measurements": [],
                        "readings": 0, "last_seen": None,
                    })
                    entry["tables"].append(table)
                    entry["readings"] += count
                    if last_seen and (
                        entry["last_seen"] is None
                        or last_seen > entry["last_seen"]
                    ):
                        entry["last_seen"] = last_seen
                    for m in measurements:
                        if m not in entry["measurements"]:
                            entry["measurements"].append(m)
        return devices

    async def get_all_devices(self) -> dict[str, dict[str, Any]]:
        """Get all devices with measurements (cached via shared sensor summary)."""
        from wp6_data.shared.sensor_summary import get_sensor_summary

        return await get_sensor_summary("red:devices", self._fetch_all_devices)

    @_retry_on_disconnect()
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

    @_retry_on_disconnect()
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

    @_retry_on_disconnect()
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

    @_retry_on_disconnect()
    async def get_wire_sensor_readings(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500000,
    ) -> pd.DataFrame:
        """Fetch multi-height wire-sensor readings from the wire_sensors table.

        The table is wide (the four measurement types at five heights spread
        across 20 columns); this unpivots them into a tidy long frame so each
        height can be drawn as its own line. Each height is surfaced as its own
        virtual ``device`` (e.g. ``WS_01_01-h3``) per ADR 0001.

        Args:
            start: Start datetime filter (inclusive)
            end: End datetime filter (exclusive)
            limit: Maximum rows to fetch

        Returns:
            DataFrame with columns: device, height, measurement, time, value
        """
        if not self.pool:
            raise RuntimeError("Not connected")

        conditions = []
        params: list[Any] = []
        if start:
            conditions.append("received_at >= %s")
            params.append(start)
        if end:
            conditions.append("received_at < %s")
            params.append(end)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        columns_sql = ", ".join(["device_id", "received_at", *wire_value_columns()])

        async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cursor:
            query = f"""
                SELECT {columns_sql}
                FROM {WIRE_SENSORS_TABLE}
                {where_clause}
                ORDER BY received_at DESC
                LIMIT {limit}
            """
            await cursor.execute(query, params)
            rows = list(reversed(await cursor.fetchall()))

        columns = ["device", "height", "measurement", "time", "value"]
        records = unpivot_wire_rows(rows)
        df = pd.DataFrame(records, columns=columns)
        if not df.empty:
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time")
        return df

    @_retry_on_disconnect()
    async def get_wire_rows(self, physical_device_id: str) -> list[dict[str, Any]]:
        """All wide rows for one physical wire, oldest first, for the CSV export.

        Unbounded on purpose: the export job writes the device's full history,
        matching :func:`export_device`'s per-table queries. Ordered by ``id`` as
        a tiebreak because ``received_at`` collides within an insert burst.
        """
        if not self.pool:
            raise RuntimeError("Not connected")

        columns_sql = ", ".join(["device_id", "received_at", *wire_value_columns()])
        async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                f"SELECT {columns_sql} FROM {WIRE_SENSORS_TABLE} "
                f"WHERE device_id = %s ORDER BY received_at ASC, id ASC",
                (physical_device_id,),
            )
            return list(await cursor.fetchall())

    @_retry_on_disconnect()
    async def get_wire_device_summary(self) -> dict[str, dict[str, Any]]:
        """Per virtual wire device: reading count and last-seen, for the explorer.

        Counts are per physical row (each row carries every height), so all
        heights of a wire share the same total — an honest approximation given
        the wide layout. Returns ``{device_id: {"readings", "last_seen"}}`` keyed
        by the virtual ``-hN`` ids.
        """
        if not self.pool:
            raise RuntimeError("Not connected")

        async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cursor:
            try:
                await cursor.execute(
                    f"SELECT device_id, COUNT(*) AS readings, "
                    f"MAX(received_at) AS last_seen "
                    f"FROM {WIRE_SENSORS_TABLE} GROUP BY device_id"
                )
                rows = await cursor.fetchall()
            except Exception:
                return {}

        summary: dict[str, dict[str, Any]] = {}
        for row in rows:
            for height in WIRE_DEVICE_HEIGHTS:
                summary[wire_device_id(row["device_id"], height)] = {
                    "readings": int(row["readings"] or 0),
                    "last_seen": row["last_seen"],
                }
        return summary

    @_retry_on_disconnect()
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
