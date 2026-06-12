# GDD tracker: source temperature from OpenMeteo (decouple from on-site sensor)

**Status:** ready-for-agent

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
