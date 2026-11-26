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
The above-lamp PAR sensor (`s2100-01-par`, natural light only) and the under-lamp sensor (`s2100-02-par`, natural + lamp). These are the DLI model's *targets*; its predictor is OpenMeteo shortwave radiation, fitted straight to `s2100-01-par` (the `s1000` station step was dropped in v11). `s2100-02-par` is also the **Reference sensor** for the climate model's per-height light deviation.

**Lamp model**:
What the lamps are doing, read off the **Natural light**/**Total light** pair in `red/lamp.py`: the level they run at, and the hours-of-day they have recently been on. An hour counts as lamp-lit when the canopy sensor is bright *while the above-lamp sensor sees no daylight* — light at the crop with no sun to explain it. Lamp light is **measured, never inferred** from the gap between a prediction and a reading: a residual clamped at zero can only ever add light, and manufactured a lamp schedule on long summer days when the lamps were off. Both the DLI forecast and the climate model take their lamp contribution from here, so the two cannot disagree about whether the lamps are running.
_Avoid_: "inferred lamp schedule" — the former residual method, removed.
_On/off from LetsGrow_: for any hour **LetsGrow** has delivered, whether the lamps ran — and at what share of the installation — is read from its switch (`metadata.yaml` `lamps`), not from the sensors. It agrees with the sensor test on 93% of a year's hours, and where they differ it is almost always a lit hour the sensors missed: on a bright midday the sun hides the lamp from any PAR test, not from the switch. The **level** is still measured from PAR (canopy reading on dark hours LetsGrow says were fully lit), because it depends on where the canopy sensor hangs: 188 µmol/m²/s through winter 2025-26, 140 from September 2026, the lamps at 100% both times. Hours after LetsGrow's last delivery (it is ~2 days late) fall back to the sensor test.
_Forecast pattern_: hours **ahead** take the per-hour **median of LetsGrow's last 3 complete days** times the level; hours that have happened take the lamps as they ran. The median keeps the switch-on edge sharp and follows a schedule that moves week by week (02:35 → 00:00 UTC over Oct–Nov 2026): lamp-hours/day error 1.40 against 1.91 for the fortnight's mean share, which smeared that moving edge into a ramp. Three days rather than one so a single odd day cannot set tomorrow. Weighting each hour by the *forecast* radiation (the switch-off below) was measured to gain only 0.02–0.18 mol/m²/day even with perfect weather; not built (issue 075).
_Switched on sunlight_: the grower turns the lamps off as outdoor radiation rises — lit 81-92% of winter daylight hours below 200 W/m², 57% at 300-400, 21% at 400-600, never above 600. A fixed hour-of-day schedule cannot represent that, which is why a forecast built on one over-adds lamps on bright days and under-adds them on dull ones.
_Daytime lamps_: red runs its lamps **through** the short winter day (measured 23:00–15:00 in December 2025), so dark-hour detection alone finds 8 of 17 hours and understates winter lamp DLI by 53%. A sunlit hour counts as lamp-lit when **the canopy outshines the roof sensor above it** — physically impossible for a passive loss, so it needs no **Attenuation** estimate and carries no circularity (the lamp would have to be known to measure attenuation, and attenuation to find the lamp). Judged on a rolling median per hour-of-day, never a single cell.
_Rejected_: testing the residual `canopy − above × attenuation` against half the lamp level. Its error grows with brightness while the bar does not, so summer mornings — genuine ratio ~0.77 against a year-wide estimate of 0.52 — read as lamps. The ratio test gives **zero** detections in May, July and August and 8–10 daylight hours a day in Nov–Feb.

**Attenuation**:
The share of natural light surviving the trip from the above-lamp sensor down to the canopy — structure (glass, fixtures, the gap between the two sensors), not lighting. Measured ~0.63. It is **not one number**: hourly it swings 0.49–0.78 with sun azimuth, tightening to 0.66–0.71 under overcast, when light is isotropic and both sensors see the same hemisphere. Daily it averages out to an 8% spread, which is why `TwoStageLightModel` can scale a daily prediction with a single constant while the climate model, applying it at one hour, cannot.
_It moves_: daily, over Oct 2025 – Nov 2026, it ran from ~0.4 (February) to 0.7–0.8 (autumn) — the crop growing over the canopy sensor after a rotation, and probably screens — so the DLI model uses a **rolling measured ratio** (`attenuation_by_date`: (canopy − LetsGrow lamps) / roof, 14-day median) and keeps its fitted constant only as the fallback. For forecasts the roof in that ratio is the one the model *predicted*, so the ratio also corrects the weather link's own seasonal miss; it can then exceed 1, and is not the physical share any more. The single constant is what made `/dli/performance` overshoot in spring and undershoot in autumn.
_Timescale_: the fitted constant is **structural, so it wants the longest window available**; the **Lamp model**'s schedule is an operator decision and wants the last few days. `derive_lamp_model` reads them from the same frames but different spans, and a caller holding a long-window value (the trained DLI model keeps one) should supply it rather than let a short window rediscover it.
_Measured by removing the lamp, not by avoiding it_: deep winter has no lamp-free daylight hour, so a raw ratio comes out **above 1** — more light at the canopy than at the roof. The lamp is instead detected per hour and subtracted before the ratio is taken. Full year 0.625 over 268 days, summer 0.630, December 0.609 — agreeing with the 0.622/0.629 arrived at independently by both model papers. A window that still cannot identify it is refused and reported as unknown, never returned as 1.0.
_Rejected_: measuring it on overcast hours only. Six times tighter in summer, and the worst option in winter (1.762) — overcast means a small above-lamp reading against an unchanged lamp.

**Lamp calendar**:
The `/dli/lamps` page: every hour of every day coloured dark / daylight / daylight+lamps / lamps-only, and below it the lamp-hours and light-hours of each day, one line per year on a shared Jan–Dec axis. **Entirely LetsGrow**: lamp on/off from its switch (`metadata.yaml` `lamps`), the sun from its outdoor weather station (`daylight`, any radiation above 0 W/m²). Not red's PAR sensors, so it reaches back to February 2023 instead of late 2025, and survives the sensors' summer-2026 outage. An hour LetsGrow did not report is a gap, never dark.
_Why not the roof sensor for daylight_: it agrees with the station on 96.9% of hours, and the rest are dawn/dusk hours where it read more light than reached the station outside — lamp spill from just below it, not sun. A LetsGrow outage (25 Oct – 2 Nov 2026) now draws blank; the sensor fallback it used to have could not rule lamps out under the sun anyway.

**Energy page**:
`/energy`: what red spends energy on — lamp-hours and the **Heat-output index** — per day, every LetsGrow year laid on one Jan–Dec calendar with a running total below, the same chart as the **Lamp calendar**'s (`shared.charts.make_daily_by_year_chart`). Lamp-hours are counted exactly as there.

**Heat-output index**:
How hard the heating ran, relative — the line gas cost follows, since LetsGrow has no gas meter. Per reading, each heating pipe's excess over the greenhouse air, `max(pipe − air, 0) ** 1.25` (the standard pipe heat-transfer relation), averaged per hour, summed over the circuits and over the day (`metadata.yaml` `heating`, `red/heating.py`).
_Why not heating hours_: red keeps its pipes warm ~22–24 h/day most of the year (minimum-pipe operation; even "pipe more than 5 °C above air" counts 19–24 h/day outside June 2026), so hours are flat while the bill is not. The index swings 2–3× between seasons.
_Why the measured pipe, not the request_: the `_calc` request tags sit at a 20 °C floor for hours, which is no heat at all; the measured pipe against the air says what was delivered.
_Sensor faults_: a pipe reading above `max_pipe` (95 °C; a hot-water loop stays below that, and the real maximum seen is ~85) is dropped, so its day becomes a gap. Over 2023–2026 that catches exactly one fault: the growing pipe at a flat 150 °C for 31 h on 30 Jun – 1 Jul 2024, which otherwise drew as the year's hottest heating day.
_Relative_: both circuits weigh equally and no pipe size, boiler efficiency or gas price is in it. Those are constants to multiply in later (kWh/m² → m³ gas → €); the shape will not change.

**Heat balance**:
The `/greenhouse` page's physics (`red/greenhouse/physics.py`): every 15 minutes, the heat coming in — sun kept inside (through the glass, less what the crop reflects back out), the lamps' electrical power, and the **pipe heat** — set against the heat going out through the cover, with the ventilation air, and as evaporated water. Quasi-steady: no heat capacity is modelled, so storage lands in the **Residual**. Every parameter in `metadata.yaml` `greenhouse` is marked CALIBRATED (with the script that did it) or LITERATURE (with the source).
_Pipe heat_: estimated from the measured pipe temperature against the air (Bot 1983 convection plus radiation, GreenLight's pipe geometry) — an estimate in W/m², unlike the relative **Heat-output index**. Both follow the same pipes; the index compares days, the pipe heat is booked against the losses.
_Calibrated on red_: the cover's loss (4.8 W/m² floor per K, closed dark nights) and the ventilation curve (air exchange against vent opening, from the vapour the crop measurably transpires having to leave with the air).
_Avoid_: euros. The page has none: the energy contract and the crop's value are unknown, so heat stays in MJ/m², light in J/cm² and lamps in lamp-hours. The lamps' heat rests on an assumed LED efficacy, the pipe heat on an assumed pipe geometry; neither is a meter reading.

**Residual**:
What the **Heat balance** does not account for: heat the air, crop and structure store or release, plus model error. Shown, never hidden or spread over the other flows. Small on winter days (~2% of the heat in on 20 Nov 2026), large on sunny summer days, when wide-open vents move more air than the night-calibrated ventilation curve knows.

**What-if**:
The **Heat balance** under other vent, screen or lamp settings, holding the air temperature LetsGrow measured: how much pipe heat would that have needed, and what humidity would it have left. Reported as a change against the balance under the real settings, so the model's own offset cancels.
_Avoid_: calling a what-if a forecast — it replays a day that happened.

**Crop activity**:
The crop's transpiration as the substrate scale measures it: between irrigation pulses, once the slab has stopped draining, the scale's weight loss over the ~4 m² it carries (4.0-4.3 kg per l/m² irrigated, `scale_area_m2`). Where pulses disturb the scale, a configured shape fills in, scaled so the day matches the water balance (irrigation − drain − weight change).
_Wake-up_: after lamps switch on in the dark, or sunrise, the time transpiration has covered half the way from its level before to its plateau 2-4 h later — ~20-60 minutes. Each switch-on therefore costs ~0.5 lamp-hour of activity, which the lamp planner charges.
_Avoid_: LetsGrow's "water uptake" for activity — it is irrigation minus drain, and the drain gauge lags the pulses by hours.

**Prescription** (advice):
What the twin would have done differently on a day (`red/greenhouse/advice.py`), each tied to one greenhouse component (lamps, pipes, vents, screen, crop, substrate) and sized in physical units (MJ/m² of pipe heat, lamp-hours, J/cm², hours). Graded act / consider / note / ok; a rule with nothing to say says "ok", so a quiet day reads as checked. For a past day it is a replay ("would have advised"); only tomorrow's light looks forward.

**Day length**:
The hours of light in a calendar day: natural light (outside radiation above 0 — LetsGrow's station reads 0 until the sun is ~5° up, so it is shorter than sunrise-to-sunset) plus the hours the lamps ran with no sun. The rest is dark; the longest unbroken dark spell may cross midnight and must last at least `dark_min_h` (the grower's rest rule).
_Lamp-hours the target needed_: the fewest whole lamp-hours that bring the day's sun to `light_target_jcm2` under the dark rule, the sun cut-off and the wake-up cost — the planner with every hour costing the same. Lamp-hours beyond it serve the longest-day rule.

**Measuring spot**:
Where LetsGrow measures the inside: one measuring box (air temperature, RH, CO₂) and one scale under one gutter section (weight, so transpiration). Lamps, pipes, vents and screen are set for the whole block. Everything the twin says about air and crop therefore rests on one spot while the actuators act everywhere; microclimates (walls, gables, under open vents, over the pipe rail) are invisible to it. The `/greenhouse` view greys the crop beyond a radius around the spot (in the overview and the sensors' view); the radius is an illustration, not a measured representativeness. The box's real position is not logged.
_Avoid_: reading a greenhouse temperature as the block's temperature.

**Position**:
A labelled location/zone in the greenhouse a sensor belongs to (e.g. "B"). Horizontal placement, not vertical. Declared per device in `metadata.yaml` and used only to group the explorer's device table; every red device currently shares one position, so the field is declared but not yet discriminating.
_Avoid_: height (height is vertical — see below).

**Height**:
One of the vertical measurement levels on the multi-height wire. Modelled as a **device** (`WS_01_01-h1` … `WS_01_01-h5`), so each height carries its own four sensors. Vertical *ordering* is now asserted by config (H1 highest, H5 lowest — see **Growth section**); real physical distances between levels are still unknown.
_Avoid_: treating height as a separate data axis — the platform has no height dimension; height *is* a device.

**Growth section**:
A named canopy zone the plant is divided into for the prescriptive view, mapped one-to-one onto a **Height** in fixed top-to-bottom order, identical for every wire: H1 "Head" (just above the canopy top), H2 "Flowering", H3 "Fruit set", H4 "Ripening", H5 "Substrate" (the root zone). The label and ordering are a horticultural assumption declared in config, not a measured distance. H1 sits *above* the plant, so it reads incoming light before the canopy attenuates it.
_Avoid_: equating a growth section with a physical distance, or assuming the order is sensor-confirmed.

**Multi-height wire** (a *wire sensor* device):
A single physical device on a vertical wire (`WS_01_01`) that measures four **measurement types** at five **heights**, landing in the wide external `wire_sensors` table. Surfaced as five per-height devices typed `wire`. Which wires exist is upstream's `wire_sensor_map` (a wire with an `active` sensor is installed), never inferred from `wire_sensors` — that table keeps rows, even all-NULL ones, for a wire that was retired. Which heights a wire reports is not declared anywhere: a height it never filled simply has no readings. `metadata.yaml` only *describes* wire heights, by pattern.
_Avoid_: multi-height PAR sensor (the retired PAR-only `s2100-10..15` predecessor).

**Measurement type**:
One of the four quantities the wire reports — PAR, temperature, humidity, CO₂ — reused as the sensor tags `par`, `temp`, `hum`, `co2`. Each is measured at every **Height**, so the external table indexes them (`par1`…`co25`).

**Solar radiation** (`wire_sensors.rad`):
A single radiation sensor per **Multi-height wire**, hanging *above* H1 — above the wire's measured heights, not on one of them. Hence one unindexed `rad` column rather than `rad1`…`rad5`, and not a **Measurement type** (those are all height-indexed). Modelled as **height 0**, a virtual device `WS_01_0N-h0` carrying `rad` alone: this keeps it inside the `-hN` naming the provider already parses, and because H0 maps onto no **Growth section**, the charts and risk engine (which iterate H1…H5) skip it untouched. It surfaces only in the device explorer, coverage grid and CSV export. WP1 will populate it later; today the column holds zeros and stopped being written on 2026-07-02, so it is wired up but empty.
_Avoid_: calling it PAR, or treating it as H1's reading — it sits above H1 and measures a different quantity.

**Reading time** (`wire_sensors.received_at`):
When the relay *inserted* a wire reading, not when the sensor measured it — it equals `created_at` on virtually every row. It is **not unique per device**: the relay writes in bursts, so several genuinely different readings routinely share one second. A wire reading is therefore identified by its source row, never by `(device, received_at)`. Trapezoidal **Height DLI** integration is unharmed — a burst spans zero seconds and contributes no area, so the burst's last reading carries the interval — but any consumer that pivots or groups on time will silently average away real readings.
_Avoid_: treating `received_at` as a measurement timestamp, or as a key.

**Crop cycle**:
One planting-to-clearing season, declared in `metadata.yaml` under `crop_cycles`
(red ADR 0006). Cycles are separated by crop-free weeks — red's counterpart to
the yearly framing blue uses. The declared dates are PROVISIONAL until Neurath
confirms them; the crop-cycles view reports any measurement that attaches to no
**Fruit cohort**, which is how a wrong date announces itself.
_Avoid_: treating a crop cycle as a calendar year — it is neither year-aligned
nor one-per-year.

**Fruit cohort**:
The fruit that set in one week, harvested about eight weeks later. A new cohort
starts every week while a cycle runs, so with the configured 8-week duration
**eight cohorts are in flight in parallel**, each a different number of weeks
along. Derived
per request from config arithmetic — deliberately *not* persisted, unlike a
**Risk episode**, because there is nothing expensive to detect.
_Avoid_: "crop cycle" for a cohort — the cycle is the season, the cohort is one
week's fruit within it.

**Day length**:
Hours in a local day that the canopy sensor (`s2100-02-par`, total light) reads
above the DLI photoperiod threshold — the day minus the time *all* light, sun and
lamps, is off. It is the DLI history page's "photoperiod at plant level", so the
two can't disagree. A day of flat zeros is an outage, not a zero-hour day, and is
left absent.
_Avoid_: deriving it from DLI or PAR level — it is a duration, not an amount.

**Development window**:
A **Fruit cohort**'s `[start, end)` span — the period over which its climate
exposure is aggregated. Paired with a *coverage* fraction, since red's
greenhouse sensors began reporting partway through the first measured season, so
early cohorts have only partly-observed windows and are drawn faded.

**VPD** (Vapour Pressure Deficit):
A derived dryness-of-air metric computed from temperature and humidity *at the same height*. Shown per growth section as a trendline against a configured *healthy band*; excursions out of the band signal transpiration stress.

**Fungal-risk** (wet-hours):
A derived Botrytis-pressure proxy: a rolling accumulation of how long humidity at a height has stayed above a high-RH threshold within a trailing window. Rendered as a continuous trendline — its level/slope, not a hard cutoff, conveys risk. Encodes "humidity too high *for too long*" as one curve.

**Wire spread**:
At one **Growth section**, the gap between the highest and lowest reading of a metric across the declared **Multi-height wires** — the quantity the uniformity view exists to show. Computed only from wires with enough of the day observed, and only where at least two of them reported: one wire is not a comparison. A configured *notable spread* per metric says how far apart is worth reporting; it is both the colour scale's saturation point and the verdict threshold, so the tint and the sentence can never disagree.
_Avoid_: reading a spread as a fault — the wires hang in different places, so some of it is the greenhouse, not the instrument. Which it is, is what **Consistent offset** distinguishes.

**Consistent offset**:
A wire reading the same distance from the other wires' median at *every* height. Because the drift does not depend on the section, it points at the wire — how it hangs, or how it is calibrated — rather than at the crop. Its opposite is a wire that disagrees at one section more than elsewhere, which is a genuinely different local microclimate there. The distinction is the uniformity view's finding; the raw spread alone cannot make it.

**Risk episode**:
A contiguous span where a risk metric (Fungal-risk, out-of-band VPD, canopy light deficit) at one growth section stayed above its "active" threshold — bounded by when the problem was first *present/observed* and when it was *resolved/gone*. A configured minimum duration suppresses flapping.
Episodes are **persisted in a rebuildable cache**, maintained by two admin actions: **Update** (incremental — extend the log up to now, the manual stand-in for a scheduled job) and **Rebuild** (recompute a *selectable date range* from the forever-retained raw wire data, used after retuning thresholds). Each episode stamps the threshold-set it was computed under. The page reads the last-built state, so the live per-section verdict is *"as of the last Update/Rebuild"* (automatic refresh via a scheduled job is a deferred upgrade). Rebuilding a range rewrites its episodes under current rules — the log is reproducible, not immutable.

**LetsGrow**:
Neurath's own climate computer — the system the grower steers the greenhouse with. Read through the SPoHF relay (`letsgrow-data`), never directly, and stored in red's `readings` as `source = 'letsgrow'`. It sees what red's own sensors cannot: the **actuators** (heating pipes, vents, screens, lamps, irrigation) and their setpoints, alongside its own climate and weather-station readings. A LetsGrow *module* (one screen, e.g. "Climate B4") is a device, `letsgrow-climate-b4`; a *column* in it is an `lg_*` sensor. Automated, not a manual upload, even though it routes by `source` like Sijia. Exported nightly like every other device: one wide CSV per module (`letsgrow-climate-b4.csv`), listed on the explorer's **Exports** tab.
_Local time_: LetsGrow exports the greenhouse wall clock, not UTC — outdoor radiation peaks at ~13:15 in October. It is localised to Europe/Amsterdam on ingest; the autumn DST night's repeated hour collapses onto one set of rows.
_Daily delivery_: data arrives once a day — day D reaches the relay late on D+1 — so a healthy feed is up to ~51 h behind. Its freshness budget is 54 h/78 h, not yookr's 2 h/6 h.
_History_: the relay holds LetsGrow from 2023-02-11 — earlier than the sync's default full-sync start, so a backfill must set `WP6_SYNC_START` explicitly.
_Running totals_: sums (radiation, PAR, irrigation, drain, water uptake, irrigation starts) climb through the day and reset at midnight, so they aggregate with `max`, never `avg`.
_Avoid_: comparing `lg_par` / `lg_temp_greenhouse` with the s2100/s2101 readings as if they were one instrument — LetsGrow's sensors hang wherever Neurath put them, which WP1 has yet to say.

**Reference sensor**:
The greenhouse-level sensor a per-height prediction is expressed relative to — `s2103-01-temp-hum-co2` for temp/hum/CO₂, `s2100-02-par` for light. Chosen by evidence, not decree: every candidate declared in `climate_model.references` is trained and compared, and coverage beats a marginally better score. It is a *whole-house* reading, not a **Height** reading, and the gap between the two is the **Deviation**.

**Deviation**:
How one **Height** differs from the **Reference sensor** at the same moment — the quantity the climate model actually fits, rather than the height's absolute value. Taken in whatever form is physically additive: a difference for temperature and CO₂, a *ratio* for PAR (canopy attenuation is multiplicative), and a difference in **absolute** humidity for RH, because the same air reads a different RH at a different temperature. Fitting the deviation makes the profile shape the thing being learnt.

**Horizon**:
How far ahead a prediction reaches, in hours. Each horizon is a separate model fitted directly on that distance, never a one-step model rolled forward — rolling forward compounds its own error. A prediction is only meaningful paired with its horizon: the same target is easy at +1 h and hard at +6 h.

**Skill**:
The fraction of a baseline's error a model removes. Zero means no better than the baseline; **negative means worse, and is reported as such**. Skill, not R², is how a climate prediction is judged here, because a slowly-moving indoor quantity scores a high R² simply by echoing the present. The baselines are *persistence* (the value now, carried forward), *climatology* (the mean for this hour and month), and — for a per-height model — *reference-as-is* (assume the height equals the **Reference sensor**, i.e. ignore the **Deviation** entirely).

**Excluded window**:
A dated span no model may train on, declared in `climate_model.exclusions`. Not low-quality data to be down-weighted: a period the sensors were not measuring what their names say. The current one (2026-05-28 → 2026-07-12) has measured boundaries and an unconfirmed cause — see `docs/red/wire-data-coverage.md`.

**Forecast profile**:
The predicted value at every **Growth section** of one wire at a single **Horizon** — the crop as a shape, the same way the measured crop-climate profile is read. The chain is fitted and scored only at its horizons, so the hours between them are not predicted: on the forecast chart the forecast half is marked at those horizons and the dashes between the markers are drawn, not predicted. Each horizon carries the two links' combined held-out error as a *measured spread*, which is not a confidence interval.

## Relationships

- A **Multi-height wire** is surfaced as five per-**Height** devices, each carrying the four **Measurement type** sensors.
- A **Growth section** is a labelled view over a **Height** (1:1, fixed order H1→H5 = top→root, same for every wire).
- **VPD**, **Fungal-risk**, and **Height DLI** are derived per **Growth section** from its **Measurement type** readings (temp+hum; hum-over-time; PAR-over-day).
- **Canopy light deficit** compares the top section's **Height DLI** to a target; it is the PAR-based **Risk episode** condition.
- A **Growth section** is comparable *across* **Multi-height wires**: the H→section mapping is declared identical on every wire, so H3 on one wire and H3 on another name the same canopy zone. That is what makes a **Wire spread** a reading about the greenhouse rather than an artefact of the model.
- A **Wire spread** is observed per **Growth section** per metric; a **Consistent offset** is a claim about a whole wire, read off those spreads across every section it reported.
- A **Risk episode** is a discrete on/off span derived from a risk metric crossing its active threshold; the admin audit lists episodes over a chosen range.
- The wire **replaced** the retired PAR-only per-height sensors (`s2100-10..15`).
- **DLI** is derived from **Natural/Total light**, independently of the wire.
- A **Crop cycle** contains overlapping **Fruit cohorts**, one starting each week.
- A Sijia measurement attaches to the **Fruit cohort** whose completion week contains
  its date; one that attaches to nothing is surfaced, never dropped.
- Each **Height** is exported as its own CSV (`WS_01_01-h1.csv`), one row per source row — because **Reading time** cannot identify a reading.
- **Solar radiation** belongs to the **Multi-height wire**, not to a measured **Height** — it hangs above H1, modelled as the virtual **height 0** device (`WS_01_0N-h0`) so it fits the `(device, sensor)` contract without a per-wire device kind.

## Example dialogue

> **Dev:** "For the wire, is each line a different sensor?"
> **Domain expert:** "Each line is a different **height** — and a height is its own device with par/temp/hum/co2. Don't confuse height with **position**; position is which zone of the greenhouse it's in."

## Flagged ambiguities

- "height" vs "position" — resolved: **position** is horizontal (zone); **height** is vertical (level on the wire, modelled as a device).
- "height ordering unknown" — resolved: ordering is now declared by config (H1 highest … H5 root) as a horticultural assumption; only the inter-level *distances* remain unknown. See **Growth section**.
- "is `received_at` the measurement time?" — resolved (2026-07, while adding wire CSV exports): no, it is the relay's *insert* time and is not unique per device. See **Reading time**. The true measurement time is not recorded anywhere, so sub-burst ordering is unrecoverable.
- "does every wire sit in the same **Position**?" — now *measurable*, still unconfirmed: `WS_01_03` was declared as position "B" to match the others, and WP1 has yet to confirm it. The uniformity view supplies the evidence — a wire that carries a **Consistent offset** at every height is somewhere the others are not — but a declared position is WP1's to state, not ours to infer.
- "do all the wires measure the same things?" — resolved (2026-10): yes, and the gaps were neither installation nor fault. Upstream's `wire_sensor_map` had filed `WS_01_03`'s climate and H4 PAR sensors under a `WS_01_01` that was never installed, so one real wire appeared as two partial ones. A **Wire spread** is still computed only over the wires that actually observed the metric. The history from 2026-07-13 to 2026-10-02 is still misfiled; see `docs/red/wire-data-coverage.md`.
- "**Cohort phase** vs **Growth section** — same labels, different axis?" — dissolved
  (2026-09, same week): cohort phases were modelled, then removed entirely. Their
  boundaries were fixed offsets from the set date, so they said nothing the start date
  did not, and they spent the waterfall's colour on a known schedule. That colour now
  carries the climate each cohort lived through. **Growth section** is again the only
  user of those labels. See [ADR 0006](../../../docs/adr/0006-cycles-and-cohorts-shared-model.md).
- "where does **Solar radiation** hang in the device model?" — resolved: modelled as virtual **height 0** (`WS_01_0N-h0`), a level above H1 that carries `rad` alone and maps onto no growth section. Its **unit** is still unconfirmed with WP1 — declared W/m² because `decimal(5,0)` admits no fraction, but not verified.

