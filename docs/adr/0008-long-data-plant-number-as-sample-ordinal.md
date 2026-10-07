# `long_data` stores the plant number as the sample ordinal

ADR 0004 discarded `Plant_nr` because nothing read below the treatment. The
harvest page is the first consumer that needs it: a plant's season yield is the
sum of its picks, and its distribution across plants is what the per-treatment
box plot shows. That needs one plant's values joinable across pick dates.

Every 2025 and 2026 file has exactly one value per (date, measure, treatment,
plant), so the plant number is itself a unique ordinal. When the file has a
`Plant_nr` column we store sample *i* at `date 00:00:00 UTC + plant_nr seconds`
instead of file order (ADR 0001); files without it (2024) keep file order. The
plant is read back with `long_data.plant_nr(time)`.

## Considered Options

- **Per-plant devices** — rejected again for ADR 0004's reasons: a
  year-varying device family and "removed devices" upload warnings.
- **A plant column on `readings`** — rejected: a shared schema change for all
  twins and a change to the unique index, for one blue source.
- **Ingest the file's `Total Yield per plant`** — rejected: it fixes one chart
  only, the cell has no date to anchor it, and it equals the sum of picks
  anyway (verified for 2025 and 2026).

## Consequences

- Devices stay the fixed treatment set; no schema change.
- A file with two values for one plant+measure+date (or a non-numeric
  `Plant_nr`) reports those rows as skipped instead of colliding.
- The ordinal's meaning depends on the year: plant number where the file had
  `Plant_nr`, file order otherwise. Only plant-numbered years may be joined
  per plant.
- Data ingested before this change carries file-order ordinals. Re-uploading
  each plant-numbered yearly file fixes it (the per-year replace of ADR 0002
  swaps the rows); until then per-plant joins on that year are wrong.
