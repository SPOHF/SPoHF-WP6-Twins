"""Shared JSON API endpoints for the unified chart page."""

import asyncio
import math
from datetime import date, datetime
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from wp6_data.config import Settings
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.metadata import MetadataRegistry
from wp6_data.shared.routes.deps import get_metadata, get_provider, get_twin_config
from wp6_data.shared.sensor_summary import get_enriched_cache, set_enriched_cache
from wp6_data.shared.templates import resolve_date_range
from wp6_data.shared.time import to_local_isoformat
from wp6_data.shared.twin import SensorDataProvider, TwinConfig

_settings = Settings()

router = APIRouter(prefix="/api", dependencies=[Depends(verify_session_user)])


@router.get("/sensors")
async def list_sensors(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    metadata: Annotated[MetadataRegistry, Depends(get_metadata)],
    twin_config: Annotated[TwinConfig, Depends(get_twin_config)],
) -> list[dict[str, str]]:
    """List all available device+sensor combos, for the side panel tree."""
    cache_key = f"{twin_config.twin_id}:{provider.data_source_label or 'default'}"
    cached = get_enriched_cache(cache_key)
    if cached is not None:
        return JSONResponse(
            content=cached,
            headers={"Cache-Control": "private, max-age=300"},
        )

    try:
        sensors = await asyncio.wait_for(
            provider.fetch_available_sensors(), timeout=10.0
        )
    except TimeoutError:
        return JSONResponse(
            content={"error": "Sensor list timed out — database may be unreachable"},
            status_code=503,
        )
    except Exception:
        return JSONResponse(content={"error": "Database not connected"}, status_code=503)

    flat = [
        {"device": s["device"], "sensor": s["sensor"]}
        for s in sorted(sensors, key=lambda s: (s["sensor"], s["device"]))
    ]
    enriched = metadata.enrich_sensor_list(flat)
    set_enriched_cache(cache_key, enriched)
    return JSONResponse(
        content=enriched,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/series")
async def get_series(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    device: str = Query(..., description="Device name"),
    sensor: str = Query(..., description="Sensor tag"),
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    limit: int = Query(default=None, description="Max records"),
) -> dict[str, Any]:
    """Fetch time-series data for a single device+sensor combo."""
    if limit is None:
        limit = _settings.chart_query_limit

    _start, _end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await provider.fetch_data(
            sensor_tags=[sensor],
            device_names=[device],
            start=start_dt,
            end=end_dt,
            limit=limit,
        )
    except Exception:
        return JSONResponse(content={"error": "Database not connected"}, status_code=503)

    if df.empty:
        return {"data": [], "truncated": False}

    truncated = len(df) >= limit
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        t: datetime = row["time"]
        records.append({
            "time": to_local_isoformat(t),
            "value": None if row["value"] is None else float(row["value"]),
        })
    return {"data": records, "truncated": truncated, "limit": limit}


@router.get("/correlate")
async def get_correlate(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    s: str = Query(..., description="Comma-separated device:sensor keys"),
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    method: str = Query(
        default="pearson",
        description="Correlation method: pearson, spearman, kendall",
    ),
) -> dict[str, Any]:
    """Compute pairwise correlation matrix for the requested sensor series.

    Returns:
        ``{sensors: ["device:sensor", ...], matrix: [[float|null, ...], ...]}``
        where *matrix[i][j]* is the correlation between sensors[i] and sensors[j].
        Upper-triangle values (i < j) are ``null`` for display symmetry.
    """
    if method not in {"pearson", "spearman", "kendall"}:
        return JSONResponse(
            content={"error": "method must be one of: pearson, spearman, kendall"},
            status_code=422,
        )

    keys = [k.strip() for k in s.split(",") if k.strip()]
    if len(keys) < 2:
        return JSONResponse(
            content={"error": "At least 2 sensors required"},
            status_code=422,
        )

    # Parse device:sensor pairs — sensor tag may itself contain ':'
    sensor_tags = []
    device_names = []
    for key in keys:
        parts = key.split(":", 1)
        if len(parts) != 2:
            return JSONResponse(
                content={"error": f"Invalid key format (expected device:sensor): {key}"},
                status_code=422,
            )
        device_names.append(parts[0])
        sensor_tags.append(parts[1])

    _start, _end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await provider.fetch_data(
            sensor_tags=list(set(sensor_tags)),
            device_names=list(set(device_names)),
            start=start_dt,
            end=end_dt,
        )
    except Exception:
        return JSONResponse(content={"error": "Database not connected"}, status_code=503)

    if df.empty:
        return {"sensors": keys, "matrix": []}

    df = df.copy()
    df["key"] = df["device"] + ":" + df["sensor"]
    # Keep only the requested keys (in request order) to preserve duplicates/ordering
    df = df[df["key"].isin(set(keys))]

    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["hour"] = df["time"].dt.floor("1h")

    pivot = (
        df.groupby(["hour", "key"])["value"]
        .mean()
        .unstack("key")
        .sort_index()
    )

    # Reindex columns to match the requested order; missing keys become all-NaN
    pivot = pivot.reindex(columns=keys)

    # Drop columns with fewer than 2 non-null values
    valid_keys = [col for col in pivot.columns if pivot[col].notna().sum() >= 2]
    pivot = pivot[valid_keys]

    if pivot.shape[1] < 2:
        return {
            "sensors": keys,
            "matrix": [],
            "warning": "Fewer than 2 sensors had enough overlapping data",
        }

    corr = pivot.corr(method=method)

    # Build response matrix with upper triangle as null
    n = len(corr)
    matrix: list[list[float | None]] = []
    for i in range(n):
        row: list[float | None] = []
        for j in range(n):
            if j > i:
                row.append(None)
            else:
                v = corr.iloc[i, j]
                row.append(None if math.isnan(v) else round(float(v), 4))
        matrix.append(row)

    return {"sensors": list(corr.columns), "matrix": matrix}
