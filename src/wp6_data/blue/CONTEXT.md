# Blue twin — domain glossary

The blueberry-farm digital twin. This glossary defines the terms used across
blue's data sources and dashboards. It is a glossary, not a spec — no
implementation details.

## Terms

### Treatment
A fertilization/cultivation strategy applied to a plot of blueberry plants.
The categorical axis every manual blue measurement is grouped by, and the
value carried in a device's `position`. `plant_nr` is numbered **locally
within a treatment**, so the same number under two treatments is two different
physical plants — `(treatment, plant_nr)` is the unique plant identity. The
same physical plant may carry a *different* treatment in a later year; keying
on treatment means its record correctly continues only while the regime is
unchanged.

Canonical treatment codes (reused from the automated sensors' `position`
vocabulary so manual + automated readings of one plot group together):

- `Org1`, `Org2`, `Std`, `Ca`, `K` — present in both 2024 and 2025.
- `G_K`, `V_CA`, `V_CA_G_BrPK`, `V_K_G_CaBrP` — phenological-stage regimes,
  2025+ only. `V_` = vegetative stage, `G_` = generative stage; e.g.
  `V_K_G_CaBrP` = potassium in the vegetative stage, then calcium + boron +
  phosphorus in the generative stage. These are first-class treatments, not
  sub-variants of `Ca`/`K`.

Source-label → canonical: `Organic 1`/`Organisch-1` → `Org1`; `Organic 2`/
`Organisch-2` → `Org2`; `Standard`/`Standaard` → `Std`; `Calcium`/`Ca` → `Ca`;
`Kalium`/`K` → `K`; the four 2025 codes pass through unchanged.

### Plant
One physical blueberry plant, identified by `(treatment, plant_nr)` and modelled
as a device named `"{treatment} / plant {nr}"`. Perennial: the same plant keeps
its device across years while its treatment is unchanged. When individual plants
were not recorded (see [[long_data]] 2024) or a measure is a pooled sample (see
**Sample**), readings are attributed to the treatment-level device
`"{treatment} / plant 0"` instead.

### Sample
An individual measured value (a shoot, a berry, a pooled stored-berry sample)
not tied to a known plant. Samples are **not** given their own devices — they
attach to the treatment-level `plant 0` device. Multiple samples on the same
date for the same device + measure are kept individually (no averaging) by
encoding the sample's file order in the timestamp: `date 00:00:00 UTC + i
seconds`, `i` = 1-based file order (so `00:00:00` is reserved/unused). This
preserves the full distribution and entry order without per-sample devices or a
schema change. Date-only data is anchored at **UTC midnight, not localized** —
unlike [[insects]] — so both day-bucketing paths file it under the correct date.

### Measure
A kind of manual measurement. In source files this is a free-text column
(`Meting`) whose labels vary across years and languages; it maps to a canonical
`sensor_tag` in `readings`. Notable blueberry measures:

- **Brix** — sugar content, %. **Firmness** — burst pressure, bar (2025; the
  2024 unit is unknown, so cross-year firmness is not comparable). **Shoot
  length** — cm. **Berry weight** — per-berry, g. **Yield per plant** — g.
- **Storage measures** — fresh vs after-storage values (Brix, firmness, weight)
  that gauge shelf life. A pooled per-treatment sample, not per-plant; pre/post
  are distinct `sensor_tag`s (`brix` / `brix_after_storage`).
- **Score** (1–10) — overall plant vigour/health, 10 best. **Budscore** (1–10)
  — bud count. **Flowering score** (1–10) — flower count. Phenology scores,
  2025+ only.

## Data sources

### long_data
Manual, lab/field-recorded blueberry measurements delivered as yearly Excel
files (`Long_Data <year>.xlsx`), one new file per year, ingested via CLI only.
Already in long/tidy form: `Date, Meting (measure), Treatment, Value`
(+ `Plant_nr` from 2025 on). Harmonizing the per-year `Meting` and `Treatment`
vocabularies (incl. unit conversion) into one canonical set is the core of
this source.

- **2025+**: per-plant measures resolve to `"{treatment} / plant {nr}"`.
  Pooled storage samples (per-treatment, not per-plant) go to `plant 0`.
- **2024**: no plant ids (fixed sampling protocol — uniform sample counts
  across treatments, not a per-plant census). All readings go to the
  treatment-level `"{treatment} / plant 0"` device; the individual samples are
  preserved via the timestamp-ordinal encoding (see **Sample**), not by minting
  per-sample devices.

### insects
Manual insect-trap counts delivered as CSV, ingested via CLI or admin upload.
One synthetic device (`insect-trap`); sensors `total_insects`, `suzukii`.
