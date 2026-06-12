# Blue automated-sensor coverage: yookr-direct vs SPoHF datalake

**Snapshot: 2026-06-12** (prod `wp6-data-timescaledb`, db `postgres`).
Source of truth for this table:

```sql
SELECT device_name, sensor_tag,
  count(*) FILTER (WHERE project='yookr-direct')           AS yk_rows,
  max(time) FILTER (WHERE project='yookr-direct')::date     AS yk_last,
  count(*) FILTER (WHERE project<>'yookr-direct')           AS dl_rows,
  max(time) FILTER (WHERE project<>'yookr-direct')::date    AS dl_last
FROM readings GROUP BY device_name, sensor_tag;
```

The two automated blue sources are the **same underlying yookr sensors**, fetched two
ways: `yookr-direct` (straight from `api.yookr.org`) and the SPoHF datalake relay
(`backoffice.spohf.com/api/v1/data/yookr-data`, landing under `project='unknown'`).
This table exists to guarantee we don't silently lose a sensor when retiring
`yookr-direct`.

## Headline

- **The datalake is currently NOT a superset of yookr-direct.** Every automated
  sensor is fresh-to-today in `yookr-direct`; in the datalake the same sensors are
  **universally stale** (newest automated datalake point is 2026-05-12; most are
  2025-12-31 → 2026-03-20). The datalake relay sync is currently failing
  (`sync_metadata.yookr-data`: `last_run_success=false`, 316 total failures).
- **Five automated devices are entirely ABSENT from the datalake** (0 rows):
  `366D`, `366E`, `3670`, `3672` (LT+LV row sensors), and `PH1 | 4D1D` (soil pH).
- **One device exists ONLY in the datalake** and is itself stale:
  `366F | Rij 1 Boven | 6` (last 2025-07-21).
- ⇒ Retiring `yookr-direct` today would drop live coverage for **all** automated
  blue sensors, not just the weather station. The datalake must be repaired/backfilled
  first (and GDD repointed to OpenMeteo — see the cleanup plan).

Status legend: 🔴 datalake absent · 🟠 datalake present but stale (>30d behind) ·
🟢 datalake fresh & sufficient · ⚪ not a yookr sensor (unaffected by removal)

## Automated sensors (the coverage-risk set)

| Device | Sensor | yk rows | yk last | dl rows | dl last | Status |
|---|---|--:|---|--:|---|:--:|
| weatherstation | airTemperature | 52720 | 2026-06-12 | 793 | 2026-03-20 | 🟠 |
| weatherstation | atmosphericPressure | 52732 | 2026-06-12 | 781 | 2025-12-31 | 🟠 |
| weatherstation | battery | 52725 | 2026-06-12 | 793 | 2026-03-20 | 🟠 |
| weatherstation | inputVoltage | 52723 | 2026-06-12 | 793 | 2026-03-20 | 🟠 |
| weatherstation | lightningStrikes | 52720 | 2026-06-12 | 793 | 2026-03-20 | 🟠 |
| weatherstation | precipitation | 52730 | 2026-06-12 | 781 | 2025-12-31 | 🟠 |
| weatherstation | solarRadiation | 52732 | 2026-06-12 | 781 | 2025-12-31 | 🟠 |
| weatherstation | vaporPressure | 52732 | 2026-06-12 | 781 | 2025-12-31 | 🟠 |
| weatherstation | windDirection | 52733 | 2026-06-12 | 781 | 2025-12-31 | 🟠 |
| weatherstation | windSpeed | 52732 | 2026-06-12 | 781 | 2025-12-31 | 🟠 |
| weatherstation | windspeedGust | 52732 | 2026-06-12 | 781 | 2025-12-31 | 🟠 |
| 366D \| LT + LV \| Rij 1 Onder \| 5 | humidity | 184543 | 2026-06-12 | 0 | – | 🔴 |
| 366D \| LT + LV \| Rij 1 Onder \| 5 | temperature | 184543 | 2026-06-12 | 0 | – | 🔴 |
| 366E \| LT + LV \| Rij 5 boven \| 2 | humidity | 178281 | 2026-06-12 | 0 | – | 🔴 |
| 366E \| LT + LV \| Rij 5 boven \| 2 | temperature | 178281 | 2026-06-12 | 0 | – | 🔴 |
| 3670 \| LT + LV \| Rij 3 Onder \| 3 | humidity | 184999 | 2026-06-11 | 0 | – | 🔴 |
| 3670 \| LT + LV \| Rij 3 Onder \| 3 | temperature | 185002 | 2026-06-11 | 0 | – | 🔴 |
| 3671 \| LT + LV \| Rij 3 Boven \| 4 | humidity | 138740 | 2026-06-12 | 47113 | 2026-03-20 | 🟠 |
| 3671 \| LT + LV \| Rij 3 Boven \| 4 | temperature | 185840 | 2026-06-12 | 13 | 2026-03-20 | 🟠 |
| 3672 \| LT + LV \| Rij 5 onder \| 1 | humidity | 185696 | 2026-06-11 | 0 | – | 🔴 |
| 3672 \| LT + LV \| Rij 5 onder \| 1 | temperature | 185699 | 2026-06-11 | 0 | – | 🔴 |
| 366F \| LT + LV \| Rij 1 Boven \| 6 | humidity | 0 | – | 93073 | 2025-07-21 | ⚪ dl-only |
| 366F \| LT + LV \| Rij 1 Boven \| 6 | temperature | 0 | – | 93270 | 2025-07-21 | ⚪ dl-only |
| 3672 \| PAR | par | 19837 | 2026-06-12 | 87478 | 2025-12-31 | 🟠 |
| 01 \| 0E5E \| BV + EC + BT | soilConductivity | 26546 | 2026-06-12 | 734 | 2025-12-31 | 🟠 |
| 01 \| 0E5E \| BV + EC + BT | soilMoisture | 26546 | 2026-06-12 | 734 | 2025-12-31 | 🟠 |
| 01 \| 0E5E \| BV + EC + BT | soilTemperature | 26545 | 2026-06-12 | 734 | 2025-12-31 | 🟠 |
| 02 \| 0E4F \| BV + EC + BT | soilConductivity | 26470 | 2026-06-12 | 746 | 2026-03-20 | 🟠 |
| 02 \| 0E4F \| BV + EC + BT | soilMoisture | 26470 | 2026-06-12 | 746 | 2026-03-20 | 🟠 |
| 02 \| 0E4F \| BV + EC + BT | soilTemperature | 26471 | 2026-06-12 | 746 | 2026-03-20 | 🟠 |
| 03 \| 0E09 \| BV + EC + BT | soilConductivity | 26453 | 2026-06-12 | 740 | 2025-12-31 | 🟠 |
| 03 \| 0E09 \| BV + EC + BT | soilMoisture | 26454 | 2026-06-12 | 740 | 2025-12-31 | 🟠 |
| 03 \| 0E09 \| BV + EC + BT | soilTemperature | 26453 | 2026-06-12 | 740 | 2025-12-31 | 🟠 |
| 04 \| 0E69 \| BV + EC + BT | soilConductivity | 26607 | 2026-06-12 | 742 | 2025-12-31 | 🟠 |
| 04 \| 0E69 \| BV + EC + BT | soilMoisture | 26607 | 2026-06-12 | 742 | 2025-12-31 | 🟠 |
| 04 \| 0E69 \| BV + EC + BT | soilTemperature | 26605 | 2026-06-12 | 742 | 2025-12-31 | 🟠 |
| BV + BT + EC \| Nr. 6 | soilConductivity | 48747 | 2026-06-12 | 746 | 2026-03-20 | 🟠 |
| BV + BT + EC \| Nr. 6 | soilMoisture | 48747 | 2026-06-12 | 746 | 2026-03-20 | 🟠 |
| BV + BT + EC \| Nr. 6 | soilTemperature | 48420 | 2026-06-12 | 746 | 2026-03-20 | 🟠 |
| SPoHF_EC-BV_rij1 | soilConductivity | 27803 | 2026-06-12 | 26652 | 2026-03-20 | 🟠 |
| SPoHF_EC-BV_rij1 | soilMoisture | 7436 | 2026-06-12 | 47019 | 2026-03-20 | 🟠 |
| SPoHF_EC-BV_rij1 | soilTemperature | 10409 | 2026-06-12 | 44049 | 2026-02-18 | 🟠 |
| SPoHF_EC-BV_rij2 | soilConductivity | 52844 | 2026-06-11 | 1337 | 2026-03-20 | 🟠 |
| SPoHF_EC-BV_rij2 | soilMoisture | 52846 | 2026-06-11 | 1337 | 2026-03-20 | 🟠 |
| SPoHF_EC-BV_rij2 | soilTemperature | 52847 | 2026-06-11 | 1336 | 2026-03-20 | 🟠 |
| SPoHF_EC-BV_rij3 | soilConductivity | 10174 | 2026-06-12 | 39384 | 2025-12-31 | 🟠 |
| SPoHF_EC-BV_rij3 | soilMoisture | 8068 | 2026-06-12 | 41493 | 2026-03-20 | 🟠 |
| SPoHF_EC-BV_rij3 | soilTemperature | 7745 | 2026-06-12 | 41816 | 2025-12-31 | 🟠 |
| SPoHF_EC-BV_rij4 | soilConductivity | 48348 | 2026-06-12 | 696 | 2025-12-31 | 🟠 |
| SPoHF_EC-BV_rij4 | soilMoisture | 48339 | 2026-06-12 | 708 | 2026-03-20 | 🟠 |
| SPoHF_EC-BV_rij4 | soilTemperature | 48336 | 2026-06-12 | 708 | 2026-03-20 | 🟠 |
| SPoHF_EC-BV_rij5 | soilConductivity | 48633 | 2026-06-11 | 738 | 2025-12-31 | 🟠 |
| SPoHF_EC-BV_rij5 | soilMoisture | 48633 | 2026-06-11 | 738 | 2025-12-31 | 🟠 |
| SPoHF_EC-BV_rij5 | soilTemperature | 48630 | 2026-06-11 | 738 | 2025-12-31 | 🟠 |
| DF1C \| BN + BT \| Zijkant Biologisch | leaf_moisture | 52422 | 2026-06-12 | 749 | 2026-03-20 | 🟠 |
| DF1C \| BN + BT \| Zijkant Biologisch | leaf_temperature | 52419 | 2026-06-12 | 749 | 2026-03-20 | 🟠 |
| DF1D \| BN + BT \| Midden control | leaf_moisture | 52661 | 2026-06-12 | 699 | 2025-12-31 | 🟠 |
| DF1D \| BN + BT \| Midden control | leaf_temperature | 52661 | 2026-06-12 | 699 | 2025-12-31 | 🟠 |
| PH1 \| 4D1D | soil_pH | 12700 | 2026-06-11 | 0 | – | 🔴 |
| PH2 \| 4D25 | soil_pH | 22139 | 2026-06-06 | 736 | 2026-05-12 | 🟠 |
| PH3 \| 4D20 | soil_pH | 22279 | 2026-06-11 | 670 | 2025-12-31 | 🟠 |

## Not yookr sensors — unaffected by removing yookr-direct ⚪

These never come from `api.yookr.org`; they are ingested by other endpoints and
all land under `project='unknown'`:

- **long_data (CLI)** — treatment-keyed lab/field measures: `brix`,
  `brix_after_storage`, `firmness`, `firmness_after_storage`, `berry_weight`,
  `berry_weight_after_storage`, `shoot_length`, `score`, `budscore`,
  `flowering_score`, `yield_per_plant`, `sample_weight_before/after_storage`,
  across treatments `Ca, K, Org1, Org2, Std, V_CA, V_CA_G_BrPK, V_K_G_CaBrP, G_K`.
- **fertigation_events** — `duration_min`, `program_id`, `volume_ml_per_plant`
  across `Ca/K/Org1/Org2/Std` and `Ca1/Ca3/K1/K3`.
- **insects (admin/CLI upload)** — `insect-trap:total_insects` (538 rows, 2026-05-29).
</content>
</invoke>
