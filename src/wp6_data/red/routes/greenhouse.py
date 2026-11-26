"""GET /greenhouse — the greenhouse in 3D, its heat and vapour balance, and what to do.

The page is a three.js scene (``static/red/greenhouse/``) driven by JSON from
the endpoints below. Everything physical is computed here, in
``red.greenhouse``; the browser only draws it.

- ``/greenhouse/api/day`` — one local day at 15 minutes: the state LetsGrow
  logged, every heat and vapour flow, the crop's activity and the advice.
- ``/greenhouse/api/whatif`` — the same day under other vent, screen or lamp
  settings, as changes against what ran.
- ``/greenhouse/api/microclimate`` — one local day of the multi-height wires,
  laid out as a cross-section of the row (the page's microclimate mode).
- ``/greenhouse/api/tomorrow`` — tomorrow's light: OpenMeteo's radiation
  forecast, its day length, and the lamp-hours the light target needs.

What each number means (how it is made, from which LetsGrow tags, how to read
it) travels with the page, from ``red.greenhouse.explain``.

No prices: the page speaks in MJ/m², lamp-hours and J/cm², because the energy
contract and crop value it would need are not known.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import structlog
from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from wp6_data.db.pool import is_initialised
from wp6_data.red import deps
from wp6_data.red.greenhouse import advice as A
from wp6_data.red.greenhouse import day as D
from wp6_data.red.greenhouse import explain
from wp6_data.red.greenhouse.microclimate import build_microclimate_day
from wp6_data.red.multi_height.config import load_uniformity_config
from wp6_data.red.multi_height.data import (
    day_window_utc,
    latest_reporting_date,
    load_wire_readings,
)
from wp6_data.red.wires import wire_ids
from wp6_data.shared import i18n, render_page
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.i18n import t, th
from wp6_data.shared.weather import DEFAULT_LAT, DEFAULT_LON

router = APIRouter(dependencies=[Depends(verify_session_user)])
log = structlog.get_logger()

_STATIC = Path(__file__).resolve().parents[4] / "static" / "red" / "greenhouse"
THREE = "https://cdn.jsdelivr.net/npm/three@0.170.0"

# A past day never changes once LetsGrow has delivered it.
_days: TTLCache = TTLCache(maxsize=64, ttl=6 * 3600)
# The wires keep reporting through the day, so their days are kept briefly.
_micro: TTLCache = TTLCache(maxsize=64, ttl=300)


def _asset(name: str) -> str:
    """URL of a page asset with an mtime cache-buster."""
    return f"/static/red/greenhouse/{name}?v={int((_STATIC / name).stat().st_mtime)}"


def _tz() -> str:
    return deps.base_settings.display_timezone


async def _last_reading() -> pd.Timestamp | None:
    from wp6_data.db.pool import get_pool

    cfg = deps.greenhouse
    async with get_pool().connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT max(time) FROM readings WHERE device_name = %s AND sensor_tag = %s",
            (cfg.devices.climate, "lg_temp_greenhouse"),
        )
        row = await cur.fetchone()
    return pd.Timestamp(row[0]) if row and row[0] else None


async def _first_reading() -> pd.Timestamp | None:
    from wp6_data.db.pool import get_pool

    cfg = deps.greenhouse
    async with get_pool().connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT min(time) FROM readings WHERE device_name = %s AND sensor_tag = %s",
            (cfg.devices.climate, "lg_temp_greenhouse"),
        )
        row = await cur.fetchone()
    return pd.Timestamp(row[0]) if row and row[0] else None


def _parse_day(value: str | None, latest: date) -> date:
    if not value:
        return latest
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"bad date {value!r}") from e


def page_title() -> str:
    return f"SPoHF Red - {t('greenhouse.page.title')}"


def _json_script(element_id: str, data) -> str:
    """``data`` as a JSON block the page's script reads (safe inside <script>)."""
    body = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/json" id="{element_id}">{body}</script>'


@router.get("/greenhouse", response_class=HTMLResponse)
async def greenhouse_page() -> str:
    """The 3D greenhouse page; its data arrives from the JSON endpoints."""
    if not is_initialised():
        return render_page(page_title(), f"<h1>{th('page.db_not_connected')}</h1>")
    cfg = deps.greenhouse
    quoted = explain.params(cfg)
    content = f"""
    <link rel="stylesheet" href="{_asset("greenhouse.css")}">
    <script type="importmap">
      {{"imports": {{"three": "{THREE}/build/three.module.js",
                     "three/addons/": "{THREE}/examples/jsm/"}}}}
    </script>
    {_json_script("gh-explain", explain.catalogue(cfg))}
    {_json_script("gh-i18n", i18n.bundle("greenhouse.ui"))}
    {_json_script("gh-refs", explain.references())}
    {_json_script("gh-config", explain.configured(cfg))}
    <div id="gh-app" class="gh" data-api="/greenhouse/api" data-lang="{i18n.current()}">
      <header class="gh-head">
        <div>
          <h1>{th("greenhouse.page.title")}</h1>
          <p class="gh-sub">{th("greenhouse.page.sub")}</p>
        </div>
        <div class="gh-daypick" aria-label="{th("greenhouse.page.day")}">
          <button type="button" class="outline" data-day="-1"
                  aria-label="{th("greenhouse.page.previous_day")}">‹</button>
          <input type="date" id="gh-date" aria-label="{th("greenhouse.page.day")}">
          <button type="button" class="outline" data-day="1"
                  aria-label="{th("greenhouse.page.next_day")}">›</button>
          <button type="button" class="outline" id="gh-latest">
            {th("greenhouse.page.latest")}</button>
        </div>
      </header>
      <section class="gh-stage">
        <div class="gh-viewer" id="gh-viewer">
          <div class="gh-loading" id="gh-loading">{th("greenhouse.page.loading")}</div>
          <div class="gh-hud gh-hud-left" id="gh-hud-out"></div>
          <div class="gh-hud gh-hud-right" id="gh-hud-in"></div>
          <div class="gh-dial" id="gh-dial"></div>
          <div class="gh-layers" id="gh-layers" aria-label="{th("greenhouse.page.layers")}"></div>
          <div class="gh-micro" id="gh-micro" hidden></div>
          <div class="gh-timeline" id="gh-timeline"></div>
        </div>
        <aside class="gh-panel" id="gh-panel" aria-live="polite"></aside>
      </section>
      <section class="gh-below">
        <div class="gh-tiles" id="gh-tiles"></div>
        <div class="gh-columns">
          <div>
            <h2>{th("greenhouse.page.advice")}</h2>
            <p class="gh-sub" id="gh-advice-sub"></p>
            <div id="gh-advice" class="gh-advice"></div>
          </div>
          <div>
            <h2>{th("greenhouse.page.tomorrow")}</h2>
            <div id="gh-tomorrow" class="gh-tomorrow"></div>
          </div>
        </div>
        <details class="gh-method">
          <summary>{th("greenhouse.page.method")}</summary>
          <p>{explain.render_terms(t("greenhouse.page.method_balance_html", **quoted))}</p>
          <p>{explain.render_terms(t("greenhouse.page.method_whatif_html"))}</p>
          <p>{t("greenhouse.page.method_no_euros_html")}</p>
        </details>
      </section>
    </div>
    <script type="module" src="{_asset("app.js")}"></script>
    """
    return render_page(page_title(), content, show_back_link=True, back_url="/")


@router.get("/greenhouse/api/day")
async def greenhouse_day(date_: str | None = Query(None, alias="date")) -> JSONResponse:
    """One day of the greenhouse (default: the newest day LetsGrow has delivered)."""
    if not is_initialised():
        raise HTTPException(status_code=503, detail="database not connected")
    tz = _tz()
    last, first = await _last_reading(), await _first_reading()
    latest = D.latest_day(datetime.now(ZoneInfo(tz)), last, tz)
    day = _parse_day(date_, latest)
    key = (day, latest, i18n.current())
    if key not in _days:
        cfg = deps.greenhouse
        f5 = await D.fetch_five_minute(day, cfg, tz)
        if f5.empty:
            payload = {
                "date": day.isoformat(),
                "tz": tz,
                "empty": True,
                "notes": [t("greenhouse.note.no_data")],
            }
        else:
            payload = D.build_day(f5, day, cfg, tz, DEFAULT_LAT, DEFAULT_LON)
        payload["range"] = {
            "first": first.tz_convert(tz).date().isoformat() if first is not None else None,
            "latest": latest.isoformat(),
        }
        _days[key] = payload
    return JSONResponse(_days[key])


@router.get("/greenhouse/api/microclimate")
async def greenhouse_microclimate(date_: str | None = Query(None, alias="date")) -> JSONResponse:
    """The multi-height wires on one day (default: the newest day any wire reported)."""
    if deps.db is None:
        raise HTTPException(status_code=503, detail="database not connected")
    tz = _tz()
    installed = await wire_ids()
    latest = await latest_reporting_date(installed, tz) or datetime.now(ZoneInfo(tz)).date()
    day = _parse_day(date_, latest)
    key = (day, latest, i18n.current())
    if key not in _micro:
        start, end = day_window_utc(day, tz, 0)
        df = await load_wire_readings(start, end)
        # read per request, like the uniformity page: retuning stays a YAML edit
        spans = load_uniformity_config(deps._METADATA_PATH).notable_spread
        payload = build_microclimate_day(
            df, deps.greenhouse.microclimate, installed, day, tz, spans
        )
        payload["range"] = {"latest": latest.isoformat()}
        _micro[key] = payload
    return JSONResponse(_micro[key])


@router.get("/greenhouse/api/whatif")
async def greenhouse_whatif(
    date_: str = Query(..., alias="date"),
    vent_scale: float | None = Query(None, ge=0, le=2),
    screen_dark: float | None = Query(None, ge=0, le=1),
    lamps: str | None = Query(None, pattern="^off$"),
) -> JSONResponse:
    """The day under other settings, against what ran."""
    if not is_initialised():
        raise HTTPException(status_code=503, detail="database not connected")
    tz = _tz()
    day = _parse_day(date_, date.today())
    cfg = deps.greenhouse
    f5 = await D.fetch_five_minute(day, cfg, tz)
    if f5.empty:
        raise HTTPException(status_code=404, detail=t("greenhouse.note.no_data"))
    try:
        result = D.what_if_day(
            f5, day, cfg, tz, vent_scale=vent_scale, screen_dark=screen_dark, lamps=lamps
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return JSONResponse(result)


@router.get("/greenhouse/api/tomorrow")
async def greenhouse_tomorrow() -> JSONResponse:
    """Tomorrow's light: forecast sun per hour, day length, lamp-hours for the target."""
    tz = _tz()
    cfg = deps.greenhouse
    target = datetime.now(ZoneInfo(tz)).date() + timedelta(days=1)
    try:
        fc = await deps.get_weather_client().get_hourly(["shortwave_radiation"], forecast_days=3)
    except Exception as e:  # noqa: BLE001 - the forecast is optional; say so
        log.warning("greenhouse_forecast_unavailable", error=str(e))
        return JSONResponse(
            {
                "available": False,
                "date": target.isoformat(),
                "reason": t("greenhouse.note.no_forecast"),
            }
        )
    start = pd.Timestamp(target, tz=tz)
    hours = pd.date_range(start, start + timedelta(days=1), freq="1h", inclusive="left")
    # OpenMeteo's radiation is the mean of the preceding hour: 13:00 holds 12-13
    sun = (
        fc.set_index("datetime")["shortwave_radiation"]
        .tz_convert(tz)
        .reindex(hours + timedelta(hours=1))
        .set_axis(hours)
    )
    if sun.isna().sum() > 2:
        return JSONResponse(
            {
                "available": False,
                "date": target.isoformat(),
                "reason": t("greenhouse.note.forecast_short"),
            }
        )
    sun_j = sun.fillna(0).clip(lower=0).to_numpy() * A.J_PER_W_HOUR
    a = cfg.advice
    k = cfg.lamps.radiation_eq
    needed = A.lamp_hours_needed(sun_j, cfg)
    longest = A.longest_day_lamp_hours(sun_j, cfg)
    sun_total = float(sun_j.sum())
    return JSONResponse(
        {
            "available": True,
            "date": target.isoformat(),
            "sun_j": [round(float(x), 1) for x in sun_j],
            "sun_total": round(sun_total, 1),
            "sun_h": int((sun.fillna(0) > 0).sum()),
            "target": a.light_target_jcm2,
            "dark_min": a.dark_min_h,
            "sun_max_j": a.sun_max_w * A.J_PER_W_HOUR,
            "lamp_jcm2": k,
            "wake": a.wake_lamp_h,
            "lamp_h_needed": needed,
            "lamp_h_longest_day": longest,
            "light_longest_day": round(sun_total + max(0.0, longest - a.wake_lamp_h) * k),
        }
    )
