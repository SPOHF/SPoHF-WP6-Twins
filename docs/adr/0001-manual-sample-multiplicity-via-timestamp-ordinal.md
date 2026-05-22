# Preserve manual sample multiplicity via a timestamp ordinal

The `long_data` blueberry source records many samples (e.g. 156 shoot-length
measurements) per treatment/date with no per-sample identity, but blue's
`readings` has a `UNIQUE (device_name, sensor_tag, time)` index, so multiple
samples at one device+date+measure cannot coexist. Because the source is
**date-only**, we repurpose the unused time-of-day: sample *i* (1-based file
order) is stored at `date 00:00:00 UTC + i seconds`. This preserves every
sample and its entry order, satisfies the existing unique index (no schema
change, other sources unaffected), and avoids minting a device per sample.

## Considered Options

- **Per-sample devices** (`Std / sample 7`) — rejected: ~1000 meaningless
  devices, bloats metadata, and `sample 7` isn't a stable entity.
- **A `sample_index` column on `readings`** — rejected: shared schema change,
  weakens the dedup guarantee for every twin.
- **Mean-bucket to one value** — rejected: loses the distribution the user
  explicitly wants for spread/box-plots.

## Consequences

The sub-day time component is synthetic and must not be read as a real
measurement time (00:00:00 UTC is reserved/unused as a sentinel). Date-only
data is anchored at UTC midnight (not localized) so both day-bucketing paths —
the UTC continuous aggregate and the Amsterdam-tz live query — file it under
the correct calendar date. Capacity is 86 399 samples/day/device/measure.
