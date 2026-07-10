# Blue automated-sensor coverage: yookr-direct vs SPoHF datalake

**Historical record. Snapshot taken 2026-07-10, immediately before the retirement**
(prod `wp6-data-timescaledb`, db `postgres`).

`yookr-direct` no longer exists: its rows were purged and `readings.project` dropped on
2026-07-10 — see [`yookr-direct-retirement.md`](./yookr-direct-retirement.md). The queries
below **will not run** against the current schema. This document is kept because it is the
evidence on which the purge decision rested: it shows exactly what was, and was not, lost.

> **Supersedes the 2026-06-12 snapshot**, which showed the datalake universally stale with
> 5 devices absent. That was the combined effect of a revoked API token (401), the dedup
> race (fixed in issue 026), and the upstream one-sensor-per-device relay bug. All three
> were resolved.
>
> **What this snapshot did *not* yet know:** most of the row-level deficit below was our own
> 10,000-record truncation bug, not the relay. Fixing `fetch_window` and re-syncing the
> window cut the yookr-only rows from 337,081 to 59,493 before the purge ran.

## Headline

- **The datalake is now a strict superset of yookr-direct at the series level.**
  **Zero** `(device, sensor)` series exist only in yookr-direct. 59 series are shared,
  33 are datalake-only (92 total).
- **All five previously-absent devices are present and fresh**: `366D`, `366E`, `3670`,
  `3672` (LT+LV row sensors) and `PH1 | 4D1D` (soil pH).
- **`weatherstation:airTemperature` is present and fresh** (50,351 rows) — the specific
  series whose absence blocked the retirement.
- **Freshness is at parity**: datalake `max(time)` = 2026-07-10 10:31 UTC vs yookr-direct
  11:25 UTC; 3,385 vs 3,507 rows in the last 24 h.
- **But the datalake is NOT a row-level superset.** 337,081 yookr-only rows remain (8.2%
  of yookr-direct's 4.10 M), entirely within 2024-11 → 2025-12. See below.

| project | rows | series | first | last |
|---|--:|--:|---|---|
| `spohf-datalake` | 4,912,026 | 92 | 2024-03-21 | 2026-07-10 |
| `yookr-direct` | 4,103,669 | 59 | 2024-03-21 | 2026-07-10 |
| `unknown` (manual) | 6,114 | 133 | 2024-04-23 | 2026-05-29 |

## The row-level deficit

Monthly, over the 59 shared series:

| window | datalake rows as % of yookr | shape |
|---|--:|---|
| 2024-03 → 2024-10 | 100 % | complete |
| 2024-11 → 2025-11 | 84 – 97 % | **thinning** — every series present every day, samples dropped inside the day |
| 2025-12 | 54 % | **hole** — 36 of 59 series have *zero* datalake rows |
| 2026-01 → 2026-07 | ~100 % | complete |

The thinning (~280 k rows) is analytically harmless: it widens the ~10-min sample spacing
to ~12 min, invisible to daily aggregates, coverage, and the soil forecast.

### December 2025: the relay bug, fossilised

That month the datalake retained **exactly one sensor per device** — the same signature as
the upstream bug reported in [`spohf-relay-bug-report.md`](./spohf-relay-bug-report.md).
56,805 yookr-only rows across 36 series:

| Device | Datalake kept | Datalake lost |
|---|---|---|
| `weatherstation` | `windspeedGust` | `airTemperature`, `solarRadiation`, `precipitation`, `windSpeed`, `windDirection`, `atmosphericPressure`, `vaporPressure`, `battery`, `inputVoltage`, `lightningStrikes` |
| `01 \| 0E5E \| BV + EC + BT` | `soilMoisture` | `soilConductivity`, `soilTemperature` |
| `02 \| 0E4F \| BV + EC + BT` | `soilTemperature` | `soilConductivity`, `soilMoisture` |
| `03 \| 0E09 \| BV + EC + BT` | `soilMoisture` | `soilConductivity`, `soilTemperature` |
| `04 \| 0E69 \| BV + EC + BT` | `soilMoisture` | `soilConductivity`, `soilTemperature` |
| `BV + BT + EC \| Nr. 6` | `soilConductivity` | `soilMoisture`, `soilTemperature` |
| `SPoHF_EC-BV_rij1` | `soilTemperature` | `soilConductivity`, `soilMoisture` |
| `SPoHF_EC-BV_rij2` | `soilMoisture`, `soilTemperature` | `soilConductivity` |
| `SPoHF_EC-BV_rij3` | `soilMoisture` | `soilConductivity`, `soilTemperature` |
| `SPoHF_EC-BV_rij4` | `soilMoisture` | `soilConductivity`, `soilTemperature` |
| `SPoHF_EC-BV_rij5` | `soilConductivity` | `soilMoisture`, `soilTemperature` |
| `366D`/`366E`/`3670`/`3671`/`3672 \| LT + LV` | `temperature` | `humidity` |
| `DF1C \| BN + BT` | `leaf_moisture` | `leaf_temperature` |
| `DF1D \| BN + BT` | `leaf_temperature` | `leaf_moisture` |

The 2026-06-16 full backfill already re-pulled this window and still landed only the
subset, while 2026-01 → 2026-06 came back complete. So the gap is most likely in SPoHF's
*stored* history, not in what the endpoint serves today.

## ⚠️ `/status` cannot show any of this

`deps.fetch_daily_coverage` joins the cagg at `(device, sensor, day)` granularity — a day
counts as covered if the series has **≥ 1 row** in it. So:

- the **thinning** is structurally invisible (same days, fewer rows within them), and
- the **December hole** falls outside the recent weekly grid the page renders.

Two `/status` pages agreeing across the source toggle is therefore *expected*, and is **not**
evidence that the datalake is row-complete. Only a row-level anti-join shows the deficit.

## Source of truth for this document

```sql
-- Series-level: is the datalake a superset?
WITH s AS (
  SELECT device_name, sensor_tag,
    count(*) FILTER (WHERE project='yookr-direct')   AS yk,
    count(*) FILTER (WHERE project='spohf-datalake') AS dl
  FROM readings WHERE project IN ('yookr-direct','spohf-datalake')
  GROUP BY 1,2)
SELECT count(*) FILTER (WHERE yk>0 AND dl=0) AS yookr_only_series,
       count(*) FILTER (WHERE yk=0 AND dl>0) AS datalake_only_series,
       count(*) FILTER (WHERE yk>0 AND dl>0) AS both
FROM s;

-- Row-level: exactly how many readings would a purge of yookr-direct destroy?
SELECT count(*) AS yookr_only_rows, count(DISTINCT (device_name,sensor_tag)) AS series
FROM readings y
WHERE y.project='yookr-direct'
  AND NOT EXISTS (
    SELECT 1 FROM readings d
    WHERE d.project='spohf-datalake'
      AND d.device_name=y.device_name AND d.sensor_tag=y.sensor_tag AND d.time=y.time);

-- Which series-months are true holes (datalake has nothing)?
WITH m AS (
  SELECT device_name, sensor_tag, date_trunc('month',time)::date mo,
    count(*) FILTER (WHERE project='yookr-direct')   yk,
    count(*) FILTER (WHERE project='spohf-datalake') dl
  FROM readings WHERE project IN ('yookr-direct','spohf-datalake')
  GROUP BY 1,2,3)
SELECT mo, count(*) AS series_with_dl_zero, sum(yk) AS yk_rows_at_risk
FROM m WHERE yk>0 AND dl=0 GROUP BY 1 ORDER BY 1;
```

## Datalake-only series (33) — not from yookr-direct

Retiring `yookr-direct` removes the toggle that currently hides these from the default
view. They will surface on `/status` and the sensor monitor:

| Device | Series | Rows | Note |
|---|--:|--:|---|
| `Natte bol - Test temperature zonder houder` | 1 | 458,140 | test rig, dead since 2025-12-31 |
| `Natte bol - Test Temperature (met houder)` | 1 | 473,208 | test rig, dead since 2025-12-31 |
| `Grubbenvorst, Limburg, Nederland` | 19 | 891 | *forecast* fields (`icon`, `moonPhase`, `sunrise`, `uvIndex`…), not sensor data |
| `351516175282524` | 10 | 10 | stray weatherstation rows under a raw IMEI |
| `366F \| LT + LV \| Rij 1 Boven \| 6` | 2 | 199,448 | real row sensor, dead since 2025-07-21 |

## Not yookr sensors — unaffected by removing yookr-direct

Manual ingest, distinguished by a non-default `readings.source` and always visible
regardless of the toggle:

- **long_data (CLI)** — treatment-keyed lab/field measures (`brix`, `firmness`,
  `berry_weight`, `shoot_length`, `yield_per_plant`, …) across treatments
  `Ca, K, Org1, Org2, Std, V_CA, V_CA_G_BrPK, V_K_G_CaBrP, G_K`.
- **fertigation_events** — `duration_min`, `program_id`, `volume_ml_per_plant`.
- **insects (admin/CLI upload)** — `insect-trap:total_insects`.
