# GDD tracker: source temperature from OpenMeteo (decouple from on-site sensor)

**Status:** ✅ Completed and verified 2026-06-12

## Design source

The grill decision (full decouple — option A) recorded in
`docs/blue/yookr-direct-retirement.md` ("Already handled" section) and the
sharpened `src/wp6_data/blue/CONTEXT.md`. No ADR (decided not necessary).

## Problem

GDD (`src/wp6_data/blue/routes/monitor/gdd.py`) reads `weatherstation:airTemperature`
via `provider.fetch_data`. That series is only fresh under `yookr-direct`; under the
datalake view it dies at 2026-03-20, so GDD is broken there. It also couples GDD to
the soon-to-be-retired direct interface.

## What to build

Decouple GDD from internal sensors entirely — source daily T_min/T_max from
**OpenMeteo modeled weather** at the blue farm location (Grubbenvorst).

- **Data assembly:** `OpenMeteoClient(lat, lon).get_historical(date(2024,1,1), today)`
  for the archive, bridge the ~5-day ERA5 tail with the forecast endpoint's
  `past_days`, and extend the future with the existing 14-day forecast. All three
  yield `DailyForecast`; feed them through the existing `gdd_from_forecasts()`.
  Delete the on-site path from GDD: `calculate_daily_gdd`, the `[-40,60]` overflow
  filter, and the `provider.fetch_data` call.
- **Config:** blue coordinates in settings — `WP6_BLUE_WEATHER_LAT=51.40642`,
  `WP6_BLUE_WEATHER_LON=6.11714` — mirroring `WP6_RED_WEATHER_*`. No hardcoded
  coords in code; the default must NOT be red's greenhouse coords.
- **Caching:** reuse `cachetools.TTLCache` (as in `shared/sensor_summary.py`),
  keyed by `(lat, lon)`, caching the assembled daily t_min/t_max table, TTL ~1h.
  `base`/`biofix` stay per-request recomputation on the cached table (cheap). No DB
  persistence — measured: 2.5 yr archive = one ~1.3 s call.
- **UI:** GDD becomes source-independent — it leaves the data-source toggle and
  shows "Weather: OpenMeteo · Grubbenvorst" instead of the `data_source` badge.

## Acceptance criteria

- [ ] GDD renders a correct cumulative curve from 2024 → today+14d from OpenMeteo, identical under either data-source cookie, with no dependency on `readings`
- [ ] Archive + recent bridge (`past_days`) + future forecast join into one continuous curve with no gap at the ERA5 tail
- [ ] Blue coordinates come from config (`WP6_BLUE_WEATHER_LAT/LON`); default is not red's coords
- [ ] Per-year overlay curves still work from the OpenMeteo data
- [ ] OpenMeteo responses cached (TTLCache); base/biofix controls recompute without re-fetching
- [ ] GDD page no longer shows the source toggle; shows the weather provider/location instead
- [ ] On OpenMeteo failure, GDD shows an error card (like the existing forecast try/except), not a 500

## Deferred / out of scope

- Threshold recalibration against the modeled-temp baseline, and resolving the
  base-temp default (`DEFAULT_BASE_TEMP = 5.0`) vs the `THRESHOLDS` comment
  ("GDD base 0°C") inconsistency — follow-up once observed pick dates exist.
- Optional on-site-sensor comparison overlay.

## Blocked by

None (independent of 022, but sequence **after** 022 per the agreed order).
Prerequisite for the deferred retirement epic (024).

## Comments

**2026-06-12 — implemented.** GDD now reads OpenMeteo modeled weather only.

- New `get_weather_hours(lat, lon, today)` in `blue/gdd.py` (cachetools TTLCache,
  ~1h, keyed by location): ERA5 archive (2024→) + forecast `past_days` bridge for
  the recent tail, returned as a `time`/`value` hourly frame **plus** the future
  `DailyForecast` list.
- **Reuse over deletion (deviation from the issue's literal wording):** rather than
  delete `calculate_daily_gdd`/`gdd_from_forecasts`, OpenMeteo hours are shaped like
  sensor readings and fed through them unchanged — the per-year/biofix/forecast
  plotting is untouched. Only the sensor/provider dependency was removed (no
  `provider.fetch_data`, no `get_provider`). The `[-40,60]` filter stays (harmless,
  still guards `calculate_daily_chill_hours`).
- `blue_weather_lat/lon` added to `Settings` (`WP6_BLUE_WEATHER_*`, Grubbenvorst).
- GDD leaves the source toggle: new `show_source_indicator` param on
  `render_page`/`render_nav_bar`; page shows "Weather: OpenMeteo · Grubbenvorst".
- `get_forecast` gained a `past_days` param.

Tests: `tests/test_gdd.py::TestGetWeatherHours` (assembly + archive-wins + caching,
network-free) and `tests/e2e/test_blue_gdd_openmeteo.py` (page renders, no toggle).
Live check: 894 daily rows, **0 missing days**, 2024-01-01→today + 13 forecast days.
459 unit + 41 e2e green, ruff clean.

Follow-ups (out of scope, noted): threshold recalibration vs modeled baseline;
base-temp default `5.0` vs the THRESHOLDS-comment `0°C`.
