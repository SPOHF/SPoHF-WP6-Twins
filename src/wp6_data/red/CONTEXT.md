# Red

The tomato-greenhouse digital twin: monitors light and the growing microclimate.

## Language

**DLI** (Daily Light Integral):
The sum of photosynthetically active radiation (PAR) received over a day; the key plant-growth metric. Modelled from the above-lamp/under-lamp pair, not the wire.
_Avoid_: using bare "DLI" for the wire's per-height integral — that is **Height DLI** (below), a different quantity.

**Height DLI**:
The day's integral of PAR *measured at one height* on the wire (what the multi-height views compute per height). Distinct from the modelled, whole-greenhouse **DLI**: Height DLI is observed per height, never feeds the DLI model. The top height (H1, just above the canopy) approximates the light arriving *at* the crop; lower heights are not yet calibrated for light penetration.

**Canopy light deficit** (recommendation):
H1's **Height DLI** for the day falling below a configured tomato DLI target — flagged only at the top growth section (H1), since judging lower heights against a target needs the not-yet-known light-penetration relationship.

**PAR** (Photosynthetically Active Radiation):
The instantaneous light intensity sensors report; integrated over a day it yields DLI.

**Natural light / Total light**:
The above-lamp PAR sensor (`s2100-01-par`, natural light only) and the under-lamp sensor (`s2100-02-par`, natural + lamp). The DLI model trains on these and nothing else.

**Position**:
A labelled location/zone in the greenhouse a sensor belongs to (e.g. "B"). Horizontal placement, not vertical.
_Avoid_: height (height is vertical — see below).

**Height**:
One of the vertical measurement levels on the multi-height wire. Modelled as a **device** (`WS_01_01-h1` … `WS_01_01-h5`), so each height carries its own four sensors. Vertical *ordering* is now asserted by config (H1 highest, H5 lowest — see **Growth section**); real physical distances between levels are still unknown.
_Avoid_: treating height as a separate data axis — the platform has no height dimension; height *is* a device.

**Growth section**:
A named canopy zone the plant is divided into for the prescriptive view, mapped one-to-one onto a **Height** in fixed top-to-bottom order, identical for every wire: H1 "Head" (just above the canopy top), H2 "Flowering", H3 "Fruit set", H4 "Ripening", H5 "Substrate" (the root zone). The label and ordering are a horticultural assumption declared in config, not a measured distance. H1 sits *above* the plant, so it reads incoming light before the canopy attenuates it.
_Avoid_: equating a growth section with a physical distance, or assuming the order is sensor-confirmed.

**Multi-height wire** (a *wire sensor* device):
A single physical device on a vertical wire (`WS_01_01`) that measures four **measurement types** at five **heights**, landing in the wide external `wire_sensors` table. Surfaced as five per-height devices typed `wire`. Which wires exist is declared in `metadata.yaml`, never inferred from the data — a wire that reports without being declared is invisible to every view, so startup logs `wire_sensors_undeclared`.
_Avoid_: multi-height PAR sensor (the retired PAR-only `s2100-10..15` predecessor).

**Measurement type**:
One of the four quantities the wire reports — PAR, temperature, humidity, CO₂ — reused as the sensor tags `par`, `temp`, `hum`, `co2`.

**VPD** (Vapour Pressure Deficit):
A derived dryness-of-air metric computed from temperature and humidity *at the same height*. Shown per growth section as a trendline against a configured *healthy band*; excursions out of the band signal transpiration stress.

**Fungal-risk** (wet-hours):
A derived Botrytis-pressure proxy: a rolling accumulation of how long humidity at a height has stayed above a high-RH threshold within a trailing window. Rendered as a continuous trendline — its level/slope, not a hard cutoff, conveys risk. Encodes "humidity too high *for too long*" as one curve.

**Risk episode**:
A contiguous span where a risk metric (Fungal-risk, out-of-band VPD, canopy light deficit) at one growth section stayed above its "active" threshold — bounded by when the problem was first *present/observed* and when it was *resolved/gone*. A configured minimum duration suppresses flapping.
Episodes are **persisted in a rebuildable cache**, maintained by two admin actions: **Update** (incremental — extend the log up to now, the manual stand-in for a scheduled job) and **Rebuild** (recompute a *selectable date range* from the forever-retained raw wire data, used after retuning thresholds). Each episode stamps the threshold-set it was computed under. The page reads the last-built state, so the live per-section verdict is *"as of the last Update/Rebuild"* (automatic refresh via a scheduled job is a deferred upgrade). Rebuilding a range rewrites its episodes under current rules — the log is reproducible, not immutable.

## Relationships

- A **Multi-height wire** is surfaced as five per-**Height** devices, each carrying the four **Measurement type** sensors.
- A **Growth section** is a labelled view over a **Height** (1:1, fixed order H1→H5 = top→root, same for every wire).
- **VPD**, **Fungal-risk**, and **Height DLI** are derived per **Growth section** from its **Measurement type** readings (temp+hum; hum-over-time; PAR-over-day).
- **Canopy light deficit** compares the top section's **Height DLI** to a target; it is the PAR-based **Risk episode** condition.
- A **Risk episode** is a discrete on/off span derived from a risk metric crossing its active threshold; the admin audit lists episodes over a chosen range.
- The wire **replaced** the retired PAR-only per-height sensors (`s2100-10..15`).
- **DLI** is derived from **Natural/Total light**, independently of the wire.

## Example dialogue

> **Dev:** "For the wire, is each line a different sensor?"
> **Domain expert:** "Each line is a different **height** — and a height is its own device with par/temp/hum/co2. Don't confuse height with **position**; position is which zone of the greenhouse it's in."

## Flagged ambiguities

- "height" vs "position" — resolved: **position** is horizontal (zone); **height** is vertical (level on the wire, modelled as a device).
- "height ordering unknown" — resolved: ordering is now declared by config (H1 highest … H5 root) as a horticultural assumption; only the inter-level *distances* remain unknown. See **Growth section**.

