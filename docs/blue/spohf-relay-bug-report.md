# SPoHF datalake relay (`yookr-data`) returns only one sensor per device

**To:** SPoHF backoffice / datalake team  •  **From:** WP6 Blue twin  •  **2026-06-15**

## Summary

The `GET /api/v1/data/yookr-data` endpoint on `backoffice.spohf.com` returns only
**one sensor per device**. Multi-sensor devices (soil probes, the weather station,
row climate sensors) expose just a single `sensor_tag`; the rest never appear. This
blocks us from using the datalake as the canonical source for the blue twin — we
currently fall back to pulling Yookr directly, which returns the full set.

## Evidence

Same 3-day window (2026-06-12 → 06-15), datalake relay vs. the direct Yookr feed
(both are the same physical sensors):

| source | distinct (device, sensor) series | rows | `weatherstation:airTemperature` |
|---|---|--:|---|
| direct Yookr feed | **58** (full sensor set per device) | 8,738 | present |
| `yookr-data` relay | **21** (one sensor per device) | 2,362 | **absent** |

Examples of what the relay returns per device (each should have more):
- `01 \| 0E5E \| BV + EC + BT` → only `soilMoisture` (missing `soilConductivity`, `soilTemperature`)
- `366D \| LT + LV \| Rij 1 Onder \| 5` → only `temperature` (missing `humidity`)
- `weatherstation` → only `windspeedGust` (missing `airTemperature` + 9 others)

## Reproduction

```
GET https://backoffice.spohf.com/api/v1/data/yookr-data
    ?timestamp_from=2026-06-15T00:00:00&timestamp_until=2026-06-15T06:00:00
    &size=1000&from=0
Authorization: Bearer <token>
```

A single 6-hour page returns 47 rows across 10 devices, and **zero** of those
devices report more than one `sensor_tag` — confirming it's the endpoint's output,
not a pagination artifact on our side. (Note: `size` > ~1000 returns an empty
`results` array — the page-size cap is worth documenting too.)

## The key question

Is this:
- **(a)** the `yookr-data` endpoint dropping sensors (a bug), or
- **(b)** the other sensors are served under *different* endpoints we should also be
  syncing?

If (b), please point us at the endpoint list; if (a), we'd appreciate a fix or ETA.

## Impact / context

- We can't retire the direct-Yookr ingest until the relay delivers all sensors per
  device, so blue keeps running both feeds in the meantime.
- Separately: the API token we use for this endpoint was revoked and restored on
  2026-06-15 (it had been returning `401 Unauthenticated`). It's working now — flag
  if that was intentional.
