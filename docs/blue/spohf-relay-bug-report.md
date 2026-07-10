# SPoHF datalake relay (`yookr-data`) returns only one sensor per device

**To:** SPoHF backoffice / datalake team  •  **From:** WP6 Blue twin  •  **2026-06-15**

> ## ✅ RESOLVED for live data — 2026-07-10
>
> The relay now serves **every sensor per device**. Verified in prod: the datalake carries
> **92 distinct `(device, sensor)` series** against the direct feed's 59 — a strict superset,
> with **zero** series exclusive to the direct feed. `weatherstation:airTemperature` is back,
> and freshness is at parity (relay `max(time)` within ~1 h of the direct feed).
>
> Thank you. Two asks remain — see **[Still open](#still-open-2026-07-10)** at the bottom:
> a **backfill of December 2025**, and the **device-name duplication** question.

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

## Sharper findings (2026-06-16, after a full historical backfill)

A full backfill of the relay (2024→today) clarified two things:

1. **It's a recent regression, not how the relay always behaved.** The *historical*
   relay data is rich — **81 distinct (device, sensor) series**, with full sensor
   sets per device through 2024–2025. The "one sensor per device" symptom only
   appears in the **recent** window. So something degraded the relay's recent
   output; the pipeline itself can clearly carry the full set.

2. **The partial delivery is tied to specific device *names*, and there's
   duplication.** The same physical soil probes are carried under two naming
   schemes — hardware-ID names (`01 \| 0E5E \| BV + EC + BT` …) **and** row-position
   names (`SPoHF_EC-BV_rij1` … `rij5`). The relay currently fills the
   **`SPoHF_EC-BV_rijN`** names *completely* (all of moisture/conductivity/
   temperature) but only **partially** fills the `0Exx` names (e.g. `01 \| 0E5E`
   → moisture only, `02 \| 0E4F` → temperature only). The direct feed fills both
   fully. Two asks here: (a) restore full per-sensor delivery on the `0Exx`
   names, and (b) confirm whether the `0Exx` and `SPoHF_EC-BV_rijN` names are the
   same physical sensors (so we can de-duplicate rather than show both).

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

## Still open (2026-07-10)

### (a) Please backfill December 2025

The live fix does not appear to have repaired the *stored* history. For **2025-12-01 →
2025-12-31**, the relay still returns only one sensor per device — the exact signature of
the original bug, preserved. 36 of 59 series have **zero** rows that month:

| Device | Relay returns | Relay still missing |
|---|---|---|
| `weatherstation` | `windspeedGust` | `airTemperature`, `solarRadiation`, `precipitation`, `windSpeed`, `windDirection`, `atmosphericPressure`, `vaporPressure`, `battery`, `inputVoltage`, `lightningStrikes` |
| `01 \| 0E5E`, `03 \| 0E09`, `04 \| 0E69` | `soilMoisture` | `soilConductivity`, `soilTemperature` |
| `02 \| 0E4F` | `soilTemperature` | `soilConductivity`, `soilMoisture` |
| `BV + BT + EC \| Nr. 6` | `soilConductivity` | `soilMoisture`, `soilTemperature` |
| `SPoHF_EC-BV_rij1` … `rij5` | one of the three | the other two |
| `366D`/`366E`/`3670`/`3671`/`3672 \| LT + LV` | `temperature` | `humidity` |
| `DF1C`, `DF1D \| BN + BT` | one of the pair | `leaf_temperature` / `leaf_moisture` |

We re-ran a full historical sync on 2026-06-16 and again after the fix; December 2025 comes
back the same both times, while 2026-01 onward returns complete. That points at the stored
data rather than the serving path.

**Impact:** we are about to retire our direct-Yookr ingest, which currently holds the only
complete copy of those 56,805 readings. Once retired, that month is gone unless the relay
can serve it. A backfill on your side would let us keep an unbroken record; otherwise we
will carry a documented one-month gap across most sensors.

There is also a milder deficit from **2024-11 → 2025-11**: the relay carries 84–97% of the
readings the direct feed has for the same series. No days are missing, only samples within
them, so this is low priority for us.

### (b) Are `0Exx` and `SPoHF_EC-BV_rijN` the same physical probes?

Both naming schemes are now fully populated, so the same soil probes appear to be carried
twice under different device names. We would like to de-duplicate rather than display both.
Please confirm the mapping (or tell us they are genuinely distinct hardware).
