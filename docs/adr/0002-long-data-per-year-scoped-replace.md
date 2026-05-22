# long_data ingest replaces by calendar-year scope

The generic manual-ingest apply is whole-source full-replace
(`DELETE FROM readings WHERE source = <slug>` then insert one file). `long_data`
arrives as one file per year (2024, 2025, soon 2026) under a single source, so
whole-source replace would delete prior years when ingesting a new one. Instead,
`long_data` apply deletes only the **calendar year(s) present in the uploaded
file**, then inserts — so adding 2026 leaves 2024/2025 intact. This is exposed
as an optional `replace_scope` seam on the `ManualSource` descriptor; the shared
service stays year-agnostic and other sources keep whole-source replace.

## Considered Options

- **Re-ingest all files together each year** (whole-source replace of the
  union) — viable, but requires always having every historical file on hand and
  a multi-file CLI; rejected in favour of independent yearly uploads.
- **One source per year** (`long_data_2024`, …) — zero service change, but
  multiple upload cards/metadata tags and contradicts the single-source intent.

## Consequences

The year scope also threads through `validate`: its existing-data comparison
(row counts, removed devices/sensors) must be scoped to the same year(s), or a
single-year upload would report every other year as "removed". Scoping by whole
calendar year (not the file's exact min/max date) keeps re-issued files robust
to date-range drift.
