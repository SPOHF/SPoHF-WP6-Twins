# Blue twin — domain glossary

The blueberry-farm digital twin. This glossary defines the terms used across
blue's data sources and dashboards. It is a glossary, not a spec — no
implementation details.

## Terms

### Treatment
A fertilization/cultivation strategy applied to a plot of blueberry plants.
The categorical axis every manual blue measurement is grouped by: a treatment
is modelled as **one device**, named by its code, with the same code carried in
the device's `position`. Manual readings are not resolved below this level —
individual plants are not identified (see **Plant**).

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
One physical blueberry plant. Plants are **not** individually modelled: a
`Plant_nr` that some source files carry is discarded on ingest (see ADR 0004),
because per-plant devices proved too cumbersome in the UI and were never queried
below the treatment. A plant's measured values are kept — they live as
**Samples** on the treatment device — but they are not labelled by plant.

### Sample
An individual measured value (a shoot, a berry, a pooled stored-berry sample).
Samples are **not** given their own devices — they attach to the **treatment**
device. Multiple samples on the same date for the same device + measure are kept
individually (no averaging) by encoding the sample's file order in the
timestamp: `date 00:00:00 UTC + i seconds`, `i` = 1-based file order (so
`00:00:00` is reserved/unused). This preserves the full distribution and entry
order without per-sample devices or a schema change. Date-only data is anchored
at **UTC midnight, not localized** — unlike [[insects]] — so both day-bucketing
paths file it under the correct date.

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

### Automated sensor source — the SPoHF datalake
The automated blue sensors (soil, leaf, PAR, pH, row climate, weather station)
are physical **yookr sensors**, but blue never talks to yookr. It reads them
relayed through SPoHF's backoffice platform (`yookr-data`), which is the single
canonical automated source. There is no data-source toggle: the nav bar shows a
static "SPoHF Datalake" badge.

Until 2026-07 a second pipeline, `yookr-direct`, pulled the same sensors straight
from `api.yookr.org` as a cross-check while the relay matured, and a `project`
column on `readings` told the two apart. Both are gone; blue now matches red's
single-categorical model, where `readings.source` distinguishes manual uploads
from automated ingest (which keeps the `'unknown'` default). History and the one
surviving gap (December 2025) are in `docs/blue/yookr-direct-retirement.md`.

**The relay caps a query at 10,000 records** (Elasticsearch `max_result_window`).
`SpoHFClient.fetch_window` bisects any time window that overflows, because offset
paging silently stops there — which once cost ~280k readings. Re-fetching means
the sync re-emits rows, so every ingest path must stay idempotent.

### long_data
Manual, lab/field-recorded blueberry measurements delivered as yearly Excel
files (`Long_Data <year>.xlsx`), one new file per year, ingested via CLI only.
Already in long/tidy form: `Date, Meting (measure), Treatment, Value`
(+ `Plant_nr` from 2025 on). Harmonizing the per-year `Meting` and `Treatment`
vocabularies (incl. unit conversion) into one canonical set is the core of
this source.

Every reading — both years, including 2025's `Plant_nr`-tagged rows and the
pooled storage samples — resolves to its treatment device `"{treatment}"`. The
individual samples within a treatment are preserved via the timestamp-ordinal
encoding (see **Sample**), not by minting per-plant or per-sample devices
(see ADR 0004).

### insects
Manual insect-trap counts delivered as CSV, ingested via CLI or admin upload.
One synthetic device (`insect-trap`); sensors `total_insects`, `suzukii`.
