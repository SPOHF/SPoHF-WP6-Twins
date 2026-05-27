# PRD — Manual `long_data` Blueberry Measurements for the Blue Twin

## Problem Statement

The blue (blueberry farm) twin receives **manual, lab/field-recorded plant
measurements** that no automated sensor pipeline captures: shoot length, Brix,
firmness, berry and sample weights, per-plant yield, and phenology scores
(plant vigour, buds, flowering). This arrives once a year as an Excel file
("Long_Data <year>.xlsx") delivered retrospectively — 2024 and 2025 exist
today, a 2026 file is expected next year.

Today there is no way to:
- Get this data into the blue twin without baking the file into a redeploy.
- Explore trends in these manual measurements alongside the automated sensor
  data (soil, climate, PAR) for the same treatment plot.
- Add a new year's file without disturbing the years already ingested.

The data is also **awkward to model**:
- It is delivered per year with **different vocabularies**: 2024 uses English
  measure/treatment labels, 2025 uses Dutch labels and finer treatment codes;
  the same measure is sometimes spelled differently or split differently.
- 2024 has **no plant identity** (a fixed-count sampling protocol), while 2025
  records a per-treatment `Plant_nr`.
- Several measures are **pooled per-treatment samples** (e.g. storage weights),
  not per-plant, and a single date can carry many samples of one measure.
- The blue `readings` table has a `UNIQUE (device_name, sensor_tag, time)`
  index and the shared ingest mean-buckets duplicate timestamps — both of
  which would silently destroy the sample distribution this data is for.

A reusable manual-upload capability already exists (built for the blue insect
source and red Sijia source): content-addressed storage, transactional
all-or-nothing apply, the `manual_uploads` audit trail, prune, preview/apply/
history UI, CLI, and home-page freshness. `long_data` should be its next
consumer — but its yearly cadence and sample-preservation needs require three
small, generic extensions rather than a copy of the flow.

## Solution

Add `long_data` as a new blue manual source on the existing shared
manual-ingest capability, with a CLI ingest path as the primary (and
sufficient) interface. A new year's file is ingested with one command and
**replaces only that year's data**, leaving prior years intact.

The hard part is a faithful **decoder** that harmonizes the two yearly
vocabularies into one canonical dataset and preserves every sample, plus three
generic capability extensions (recorded as ADRs):

- **Sample multiplicity via a timestamp ordinal** (ADR 0001): because the data
  is date-only, the unused time-of-day encodes each sample's file order
  (`date 00:00:00 UTC + i seconds`), so many samples coexist at one
  device+date+measure with no schema change and no per-sample devices.
- **Per-year scoped replace** (ADR 0002): one `long_data` source fed by yearly
  files; apply deletes only the calendar year(s) in the uploaded file.
- **Wildcard device metadata** (ADR 0003): `metadata.yaml` device keys may be
  glob patterns, so ~1000 data-driven plant devices inherit their treatment's
  `position` from one pattern per treatment.

From the user's perspective:

- An **operator** runs `wp6-blue-ingest-long-data <file.xlsx>` — locally or
  against the remote/prod blue TSDB — to validate and ingest a year's file;
  re-running a year re-replaces just that year, and adding a new year leaves
  earlier years untouched.
- A **researcher/viewer** sees the manual measurements plotted on the blue
  dashboard like any other sensor, grouped **by treatment position** next to
  the automated soil/climate/PAR sensors of the same plot, with the full
  per-sample spread available for box-plots/variance.
- The existing **insect** and **red/Sijia** sources are unchanged — they keep
  whole-source replace and strict dedup; the new behaviours are opt-in per
  source.

## User Stories

1. As a blue-twin operator, I want to ingest a yearly `long_data` Excel file
   via a CLI command, so that I can load it without a redeploy or a web UI.
2. As an operator, I want that CLI to run against the remote/prod blue TSDB, so
   that I can validate the schema + decoder end-to-end as the earliest check.
3. As an operator, I want ingesting the 2026 file to leave 2024 and 2025 data
   intact, so that yearly delivery is additive, not destructive.
4. As an operator, I want re-ingesting a year's file to replace only that
   year's rows, so that I can correct a year's file idempotently.
5. As an operator, I want a validation preview (parsed rows, devices, sensors,
   date range, skipped rows) before anything is written, so that I can catch a
   bad file early.
6. As an operator, I want the existing-data comparison in the preview scoped to
   the file's year(s), so that a single-year upload does not report every other
   year as "removed".
7. As an operator, I want apply to be atomic (all-or-nothing), so that a
   mid-apply failure never leaves blue data half-written.
8. As an operator, I want every upload recorded in the `manual_uploads` audit
   log (filename, hash, timestamp, row count), so that provenance is kept.
9. As a data analyst, I want the two yearly vocabularies harmonized into one
   canonical set of measures, so that I can compare a measure across years in
   one series.
10. As a data analyst, I want 2024's English and 2025's Dutch treatment labels
    mapped to canonical treatment codes, so that the same plot lines up across
    years and with the automated sensors.
11. As a data analyst, I want the four 2025 phenological-stage treatments
    (`G_K`, `V_CA`, `V_CA_G_BrPK`, `V_K_G_CaBrP`) kept as first-class
    treatments, so that the split strategies are not wrongly folded into 2024's
    coarse `Ca`/`K`.
12. As a data analyst, I want per-plant 2025 measurements modelled as
    `"{treatment} / plant {nr}"` devices, so that I can explore individual
    plants where the data supports it.
13. As a data analyst, I want a perennial plant's series to continue across
    years while its treatment is unchanged (no year in the device name), so
    that I see a real multi-year trend.
14. As a data analyst, I want measurements with no plant identity (all of 2024;
    pooled storage samples any year) attributed to the treatment-level
    `"{treatment} / plant 0"` device, so that I am not misled by fake plants.
15. As a data analyst, I want every individual sample preserved (not averaged),
    so that I can compute spread, variance, and box-plots later.
16. As a data analyst, I want samples on one date kept in file order, so that
    the entry sequence is recoverable.
17. As a data analyst, I want `Yield per plant` and the Dutch `Oogst gewicht
    per plant` treated as the same measure, so that a one-day labelling slip
    does not split the series.
18. As a data analyst, I want fresh vs after-storage measures kept as distinct
    measures (e.g. `brix` vs `brix_after_storage`), so that shelf-life change
    is analysable where 2024 recorded both.
19. As a data analyst, I want 2025's single Brix/firmness mapped to the
    fresh measure, and 2024's pre-storage berry weight merged with 2025's
    per-berry weight into one `berry_weight` series, so that cross-year trends
    are continuous.
20. As a data analyst, I want firmness left unconverted with a documented
    caveat (2024 unit unknown), so that I am warned not to read cross-year
    firmness as biology.
21. As a data analyst, I want the cumulative measures (`Total Yield per plant`,
    2024's `Total Weight (grams)`) dropped, so that derived totals do not
    pollute the dataset.
22. As a data analyst, I want an *unrecognised* measure label to surface as a
    skipped row with a reason (not silently dropped), so that a new measure in
    a future file is noticed.
23. As a data analyst, I want the manual measurements timestamped on the
    correct calendar date in both the daily aggregate and the live dashboard,
    so that they align with automated data on shared time axes.
24. As a viewer, I want manual measurements grouped by treatment `position`
    alongside the automated sensors of the same plot, so that I can correlate
    plant outcomes with the environment.
25. As a platform maintainer, I want the per-year scoped replace and the
    sample-multiplicity behaviour to be opt-in per source, so that insect and
    Sijia ingestion are completely unchanged.
26. As a platform maintainer, I want ~1000 data-driven plant devices enriched
    from a handful of wildcard `metadata.yaml` keys, so that the YAML stays a
    small hand-maintained SSOT.
27. As a platform maintainer, I want wildcard device matching to live in the
    shared `MetadataRegistry`, so that every twin can use it.
28. As a future-source author, I want `long_data` to be one decoder + one
    descriptor + wiring, so that the per-source surface stays small.

## Implementation Decisions

**Target & data**
- `long_data` is a **blue** manual source; categorical value `long_data`
  written to the readings manual-ingest categorical column (the same column the
  insect source uses). `.xlsx` input, single sheet, long/tidy form:
  `Date, Meting, Treatment, Value` (+ `Plant_nr` from 2025 on).
- Each file covers one year; ingest is **per-year scoped replace** (ADR 0002),
  not whole-source replace.

**The `long_data` decoder (the source-specific deep module)**
- Pure `bytes → (readings, skipped rows, ValidationReport)`; no database.
- **Layout detection** by header: `Plant_nr` present ⇒ 2025-style (per-plant),
  absent ⇒ 2024-style (no plant identity). 2026+ is assumed 2025-style.
- **Treatment harmonization** to canonical codes reused from the automated
  sensors' `position` vocabulary: `Organic 1`/`Organisch-1`→`Org1`;
  `Organic 2`/`Organisch-2`→`Org2`; `Standard`/`Standaard`→`Std`;
  `Calcium`/`Ca`→`Ca`; `Kalium`/`K`→`K`; and the four 2025 phenological-stage
  codes (`G_K`, `V_CA`, `V_CA_G_BrPK`, `V_K_G_CaBrP`) pass through unchanged.
- **Measure harmonization** to canonical `sensor_tag`s:
  - `shoot_length` (cm), `brix`/`brix_after_storage` (%),
    `firmness`/`firmness_after_storage` (bar; 2024 unit unknown, **not
    converted**), `berry_weight` (g; 2024 "before storing" + 2025 "per berry"
    merged)/`berry_weight_after_storage` (g),
    `sample_weight_before_storage`/`sample_weight_after_storage` (g),
    `yield_per_plant` (g; `Yield per plant` **and** `Oogst gewicht per plant`
    alias to this), `score`/`budscore`/`flowering_score` (1–10).
  - 2025's single `Brix`/`Firmness` map to the fresh measure (`brix`/
    `firmness`).
  - **Ignore list** (not errors): `Total Yield per plant`, `Total Weight
    (grams)`. **Unrecognised** measure label ⇒ `SkippedRow` with a reason.
- **Device construction**: per-plant measures with a real `Plant_nr` ⇒
  `"{treatment} / plant {nr}"`; everything without a known plant (all of 2024;
  pooled storage samples any year) ⇒ `"{treatment} / plant 0"`. No per-sample
  devices. No year component in the name (perennial; treatment + plant_nr is
  the identity).
- **Sample preservation via timestamp ordinal** (ADR 0001): the decoder does
  **not** use the shared mean-bucketing `bind`. It groups readings by
  `(device_name, date, sensor_tag)` in file order and assigns sample `i`
  (1-based) the timestamp `date 00:00:00 UTC + i seconds`; `00:00:00` is
  reserved/unused. Date-only data is anchored at **UTC midnight, not
  localized**, so both day-bucketing paths file the correct date. Capacity
  86 399 samples/day/device/measure (max observed: 156).

**`replace_scope` seam (shared service + descriptor)**
- `ManualSource` gains an **optional** replace-scope hook; the
  `ManualIngestService` uses it to constrain both the apply DELETE and the
  `validate` existing-facts comparison. Default (absent) = whole-source replace
  (insects/Sijia unchanged). `long_data` supplies "the calendar year(s) present
  in the upload" — scoping by whole calendar year (not the file's exact min/max
  date) for robustness to re-issued files.

**Wildcard device metadata (shared `MetadataRegistry`)**
- `device(key)` resolves **exact match first, then the most-specific (longest)
  matching glob pattern**; no match returns empty defaults (unchanged
  back-compat). One pattern per treatment (e.g. `"Org1 / plant *"` →
  `position: Org1`) enriches every plant device in that plot, including future
  years.

**Metadata & wiring (blue)**
- `metadata.yaml`: ~14 canonical `sensor_tag`s in `sensor_defaults` (units +
  aliases + `source: long_data` for the manual-vs-automated UI split), plus
  wildcard device entries giving each treatment its `position`.
- Register `long_data` in blue's `SOURCES`. The shared admin upload card +
  history page come along via the route factory but are **not** a goal; the
  CLI is the intended path.
- `wp6-blue-ingest-long-data <path>` console script: a thin wrapper delegating
  to the shared single-file CLI runner (single-file is sufficient because each
  yearly file is scoped-replaced independently). CLI and any UI share one apply
  path.

## Testing Decisions

A good test asserts **observable external behaviour** through a module's public
interface, not its internal structure — it survives a behaviour-preserving
refactor and fails only when behaviour changes. Tests use source constants, not
magic numbers, and assert no implementation details.

Modules the developer wants tested:

- **`long_data` decoder — thorough unit tests, no database.** The densest
  coverage, as the pure deep module: 2024-vs-2025 layout detection;
  treatment-label harmonization (English + Dutch → canonical, four 2025 codes
  pass through); measure harmonization (pre/post split, `Oogst`→`yield` alias,
  2025 single Brix/firmness → fresh, berry-weight merge); device construction
  (`plant {nr}` vs `plant 0`); the timestamp-ordinal assignment (i samples →
  `+i` seconds, `00:00:00` unused, UTC anchor, file-order preserved);
  ignore-list silently dropped vs unrecognised label → `SkippedRow`;
  `ValidationReport` facts (totals, valid vs skipped, devices, sensors, date
  range). Prior art: the insect and Sijia parser unit suites.
- **`MetadataRegistry` wildcard matching — unit tests, no database.**
  exact-beats-pattern; longest/most-specific pattern wins; pattern inherits
  `position` to a matching device; unknown device → empty `DeviceMetadata()`
  (back-compat preserved). Prior art: existing metadata tests.
- **CLI smoke test — e2e against the two real `.xlsx` files, real TSDB.** Runs
  `wp6-blue-ingest-long-data` end-to-end (local now, remote/prod-capable):
  ingest 2024 then 2025 and assert **both** years are present (per-year scoped
  replace preserves prior years); assert a high-sample group (e.g. a 2024
  shoot-length date) stores **N rows, not a mean** (sample multiplicity);
  assert expected canonical devices/sensors/date ranges. Prior art: the
  existing manual-ingest-service / blue incremental-sync e2e suites.

Because this work touches the schema/ingest path, the e2e suite is run locally
(`pytest tests/e2e/ -m e2e`) before commit — the default gate skips e2e.

Not separately mandated (covered incidentally): a dedicated route/UI HTTP test
(the upload card is reused, not a goal) and a standalone scoped-replace service
test (the CLI e2e exercises the same apply path and per-year preservation).

## Out of Scope

- A bespoke web upload button/flow for `long_data` (the shared admin card is
  reused if present, but the CLI is the deliverable per the user's request).
- Converting 2024 firmness to 2025 units (the 2024 unit is unknown).
- Reconstructing 2024 plant identity (the source is a fixed-count sampling
  protocol with no plant ids — modelled at treatment level).
- Multi-file ingest in a single command (each yearly file is ingested
  separately under the per-year scoped replace).
- Changes to the insect or red/Sijia sources (whole-source replace and strict
  dedup are unchanged for them; the new behaviours are opt-in).
- A runtime registry for arbitrary new sources; sources are still added in code
  (one decoder + one `ManualSource` + wiring).
- Backfilling/transforming other pre-existing blue data; new dashboard chart
  types beyond what existing sensor plotting already provides.

## Further Notes

- The temporary root files (`Long_Data 2024.xlsx`, `Long_Data 2025.xlsx`, and
  the Excel lock file) must not be committed; they are gitignored and a small
  synthetic fixture is committed for unit tests. Real files are passed to the
  CLI at runtime; the e2e smoke test reads the real files from a local path.
- Domain language is defined in `src/wp6_data/blue/CONTEXT.md` (Treatment,
  Plant, Sample, Measure, the `long_data` source). Decisions are recorded in
  `docs/adr/0001`–`0003`.
- `score` is plant vigour/health (1–10, 10 best), distinct from `budscore`
  (bud count) and `flowering_score` (flower count); all three are 2025+ only.
- `shoot_length` contains some `0.0` values; whether these are dead-plant
  readings or missing-coded-as-zero is to be confirmed during implementation
  (keep vs skip).
- The four 2025 treatments are time-phased fertilizer regimes (`V_` =
  vegetative stage, `G_` = generative stage), not sub-variants of `Ca`/`K`.
