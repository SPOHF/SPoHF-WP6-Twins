# `long_data` models one device per treatment

`long_data` originally minted one device per `(treatment, plant_nr)` (plus a
`"{treatment} / plant 0"` device for plant-less and pooled-sample rows). This
produced an unbounded, year-varying device family: every yearly upload
introduced a fresh set of plant devices, the admin upload preview warned of
"removed devices" whenever a new year's plant set differed, and nothing in the
app ever drilled down per plant — charts aggregate by treatment.

We **drop `plant_nr` from device identity**: the device is the treatment code
(`"Org1"`), a fixed set of nine. Any `Plant_nr` column is read past and
discarded. Individual values are not lost — every plant and pooled sample of a
treatment coexists on its one device as ordinal-timestamped samples, exactly the
mechanism that already carried 2024's plant-less data (ADR 0001).

## Considered Options

- **Keep per-plant devices** — rejected: the cumbersome, year-varying device
  set was the problem, and per-plant identity was never consumed.
- **Move `plant_nr` into a `readings` column** — rejected: a schema change and
  query complexity to preserve an identity nothing reads.

## Consequences

- Per-plant identity is discarded; `(treatment, date, measure)` samples are
  preserved but no longer labelled by plant. Acceptable — no consumer queried
  below the treatment.
- `blue/metadata.yaml` lists nine literal treatment devices instead of wildcard
  patterns. This removes `long_data` as the consumer of wildcard device
  metadata (ADR 0003); that generic capability is intentionally retained.
- Migration is free: ingest replaces per calendar year (ADR 0002), so
  re-ingesting each yearly file swaps old `"{treatment} / plant {nr}"` rows for
  treatment-only rows with no manual SQL.
