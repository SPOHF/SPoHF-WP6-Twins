# Wire sensor: height modelled as device, served by a third provider leg

## Status

accepted

## Context

The multi-height wire reports four measurement types (PAR, temp, humidity, CO₂)
at five heights from a single physical device (`WS_01_01`) into a new, *wide*
external MySQL table `wire_sensors` (20 height-indexed value columns per row).
The platform's data contract is strictly `(device, sensor)` — there is no
"height" axis — and the generic home explorer / `fetch_data` are built on it.

## Decision

Model each **height as its own device** (`WS_01_01-h1` … `WS_01_01-h5`), reusing
the existing measurement tags (`par`, `temp`, `hum`, `co2`) as sensors. The wire
devices are declared in `metadata.yaml` with `type: "wire"`; the red provider
treats `type: "wire"` as a **third routing leg** (alongside legacy MySQL
`SENSOR_TABLES` and TSDB), reading `wire_sensors` and reshaping the wide row back
into `(device, sensor, time, value)` — the height is parsed from the `-hN` id
suffix. This fully replaces the older PAR-only per-height sensors
(`s2100-10..15`); the DLI model is unaffected (it uses `s2100-01/02` only).

## Considered Options

- **Height as sensor tag** (`par_h1`…`co2_h5`, one device): rejected — pollutes
  the measurement-tag namespace and breaks measurement-based queries
  (`get_readings_by_measurement("par")` would miss `par_h1`).
- **Coexist with `s2100-10..15`**: rejected by the team in favour of a clean
  cutover, since nothing safety-critical (DLI) depends on the old entries.

## Consequences

- The `(device, sensor)` contract stays intact platform-wide; the wire's wide
  shape is contained entirely within the red provider/db.
- A naming convention (`<device>-h<n>`) now carries semantic meaning the
  provider parses — renaming wire devices requires updating the parse helper.
- A second physical wire is a future change: enumeration is metadata-driven, so
  it means new `type: "wire"` entries, not new code.
