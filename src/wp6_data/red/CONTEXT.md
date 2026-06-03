# Red

The tomato-greenhouse digital twin: monitors light and the growing microclimate,
centred on PAR and Daily Light Integral (DLI).

## Language

**DLI** (Daily Light Integral):
The sum of photosynthetically active radiation (PAR) received over a day; the key plant-growth metric. Modelled from the above-lamp/under-lamp pair, not the wire.

**PAR** (Photosynthetically Active Radiation):
The instantaneous light intensity sensors report; integrated over a day it yields DLI.

**Natural light / Total light**:
The above-lamp PAR sensor (`s2100-01-par`, natural light only) and the under-lamp sensor (`s2100-02-par`, natural + lamp). The DLI model trains on these and nothing else.

**Position**:
A labelled location/zone in the greenhouse a sensor belongs to (e.g. "B"). Horizontal placement, not vertical.
_Avoid_: height (height is vertical — see below).

**Height**:
One of the vertical measurement levels on the multi-height wire. Modelled as a **device** (`WS_01_01-h1` … `WS_01_01-h5`), so each height carries its own four sensors. Real distances/ordering are not yet known.
_Avoid_: treating height as a separate data axis — the platform has no height dimension; height *is* a device.

**Multi-height wire** (a *wire sensor* device):
A single physical device on a vertical wire (`WS_01_01`) that measures four **measurement types** at five **heights**, landing in the wide external `wire_sensors` table. Surfaced as five per-height devices typed `wire`.
_Avoid_: multi-height PAR sensor (the retired PAR-only `s2100-10..15` predecessor).

**Measurement type**:
One of the four quantities the wire reports — PAR, temperature, humidity, CO₂ — reused as the sensor tags `par`, `temp`, `hum`, `co2`.

## Relationships

- A **Multi-height wire** is surfaced as five per-**Height** devices, each carrying the four **Measurement type** sensors.
- The wire **replaced** the retired PAR-only per-height sensors (`s2100-10..15`).
- **DLI** is derived from **Natural/Total light**, independently of the wire.

## Example dialogue

> **Dev:** "For the wire, is each line a different sensor?"
> **Domain expert:** "Each line is a different **height** — and a height is its own device with par/temp/hum/co2. Don't confuse height with **position**; position is which zone of the greenhouse it's in."

## Flagged ambiguities

- "height" vs "position" — resolved: **position** is horizontal (zone); **height** is vertical (level on the wire, modelled as a device).
- "switch to the new table" — resolved: the wire **replaces** `s2100-10..15` in the explorer and the Simple Greenhouse view; the DLI model is untouched (it never used those sensors).
