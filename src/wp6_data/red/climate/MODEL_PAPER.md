# Red climate model: weather → greenhouse level → per-height wire

**Version 1**, trained 2026-09-16 on 2025-10-08 → 2026-09-16.

## Abstract

A three-link chain predicting per-height greenhouse climate — temperature,
humidity, CO₂ and PAR at each growth section on each multi-height wire — from
publicly available weather and the greenhouse's own recent state. The chain is
split where the data is, not where the physics is tidiest: the wires have nine
usable summer weeks, the greenhouse-level sensors have eleven months, so only
the smallest link is asked to learn from the wires.

Every score is out-of-fold and reported against the baselines it has to beat.
That is the substance of the work. Fitting a ridge to a slowly-moving indoor
series is easy; producing a number that means something is not.

## 1. Why three links

```
OpenMeteo hourly
      │  Link 1 — calibrate the API to this site
      ▼
   s1000 (local outdoor station, 2025-10-08 →)
      │  Link 2 — greenhouse response; + indoor lags, hour, season
      ▼
greenhouse level (s2103 temp/hum/co2, s2100-02 par)
      │  Link 3 — per-height deviation; the only link needing wire data
      ▼
wire frame (device, height, measurement, time, value)
```

The wires came online late and partly broken
(`docs/red/wire-data-coverage.md`). A direct weather → per-height model would
put the whole weather relationship on nine summer weeks of wire data. Splitting
it means the wires only have to answer a much smaller question: how does this
height differ from the greenhouse-level sensor, right now?

## 2. Design choices

### 2.1 Deviation, not value (link 3)

Link 3 fits `height − reference`, not `height`. The profile shape becomes the
thing being learnt, errors from links 1-2 do not distort it, and a handful of
parameters per height suffice — which is the point, given how little wire data
exists.

The deviation is taken in whatever form is physically additive:

| Measurement | Form | Why |
|---|---|---|
| `temp`, `co2` | difference | Additive quantities. |
| `par` | **ratio** | Canopy attenuation is multiplicative — the same reasoning as the DLI model's constant `attenuation_factor`. |
| `hum` | difference in **absolute** humidity | See below. |

### 2.2 Humidity goes through absolute humidity

Relative humidity is not comparable between two heights at different
temperatures. Air at 20 °C and 80 % RH, warmed to 30 °C, reads **45.6 % RH** —
same air, same moisture, a 34-point "deviation" that is entirely a temperature
artefact. So the deviation is fitted on absolute humidity and converted back to
RH using the *predicted temperature at that height*, which also keeps any later
VPD consistent with the temperature and humidity it comes from. Saturation
vapour pressure is reused from `risk/metrics.py` rather than reimplemented.

Temperature is therefore predicted before humidity at any height.

### 2.3 Direct multi-horizon, not recursive

One model per `(target, horizon)`, fitted directly on that horizon, following
`blue/soil_forecaster.py`. Rolling a one-step model forward would compound its
own error; a direct fit does not.

### 2.4 Hourly

Hourly matches OpenMeteo's native resolution and resolves the diurnal cycle,
which is the thing daily aggregation throws away. Sensors resample cleanly from
their ~5-minute cadence, and resampling also absorbs the relay's burst writes —
`received_at` is insert time and is not unique per device.

### 2.5 Reference chosen by evidence, coverage first

Both declared greenhouse-level candidates are trained and compared. **Coverage
wins over a marginally better score**: `s2101` edges `s2103` on mean skill
(+0.271 vs +0.250) but has no CO₂ sensor, and its larger swing is most of why it
scores better — more variance left to explain. Choosing it would have produced a
model with no CO₂ in it while reporting a slightly better number.

## 3. What the scores are measured against

Three baselines, all reported per target and per horizon:

- **persistence** — carry the value at `t` forward. The hard one at short
  horizons, because indoor temperature barely moves in an hour.
- **climatology** — mean for that hour-of-day and month, built from the training
  rows only.
- **reference-as-is** (link 3) — assume the height equals the greenhouse-level
  sensor. If modelling the gradient does not beat ignoring it, link 3 has earned
  nothing.

Plus a **gradient score**: the H1→H5 profile shape, measured as error on
`value[h] − value[H1]` and the share of comparisons where the gradient points
the same way. A model can be right about every height's average and still draw
the profile upside down.

## 4. Results (v1)

### Link 1 — OpenMeteo → s1000, 8,012 hourly rows

| Sensor | R² (out-of-fold) | RMSE | Fed to link 2 |
|---|---|---|---|
| temp | 0.980 | 1.11 °C | yes |
| hum | 0.849 | 6.00 % | yes |
| lux | 0.840 | 10,725 lx | yes |
| wind_sp | **−0.538** | 70.1 | **dropped** |

Local wind is not predictable from OpenMeteo's 10 m wind at this site. A stage
that cannot beat its own mean is noise, and noise handed to link 2 is a feature
that can only cost it — so it is reported and then excluded.

### Link 2 — greenhouse level (`s2103`), 344 days, 46 excluded

| Target | Horizon | RMSE | R² | vs persistence | vs climatology |
|---|---|---|---|---|---|
| temp | +1 h | 1.28 °C | 0.930 | +0.19 | +0.52 |
| temp | +3 h | 2.95 | 0.631 | +0.23 | −0.10 |
| temp | +6 h | 3.59 | 0.457 | +0.42 | −0.33 |
| temp | +12 h | 2.58 | 0.721 | +0.67 | +0.05 |
| temp | +24 h | 2.43 | 0.750 | +0.05 | +0.10 |
| temp | +48 h | 2.76 | 0.679 | +0.11 | −0.02 |
| hum | +1 h | 3.47 % | 0.947 | +0.19 | +0.64 |
| hum | +12 h | 7.79 | 0.732 | +0.62 | +0.18 |
| hum | +48 h | 8.94 | 0.648 | +0.18 | +0.07 |
| co2 | +1 h | 57.7 ppm | 0.679 | +0.04 | +0.21 |
| co2 | +6 h | 99.9 | 0.040 | +0.23 | −0.36 |
| co2 | +12 h | 76.4 | 0.439 | +0.44 | −0.04 |

Read the skill columns, not R². **CO₂ is weak and says so** — it is driven by
venting, dosing and photosynthesis far more than by weather, and at +3 to +6 h
it is beaten outright by the hour-of-day-and-month mean. That is a finding about
how the house is run, not a defect.

Note the shape of the temp column: skill against persistence *rises* to a peak
at +12 h and then collapses at +24 h. Twelve hours out, the model knows
something persistence cannot (the day is turning); twenty-four hours out, "same
time yesterday" is already a strong guess.

Three-hourly horizons through the 12-48 h range resolve that into something
sharper than a dip (temperature, skill vs persistence):

| +12 | +15 | +18 | +21 | **+24** | +27 | +30 | +33 | +36 | +42 | **+48** |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.63 | 0.60 | 0.56 | 0.34 | **−0.09** | 0.27 | 0.44 | 0.54 | 0.59 | 0.51 | **−0.01** |

**Persistence is only competitive at near-exact 24-hour alignment.** Three hours
either side of it — +21 h and +27 h — the model is comfortably ahead again, and
+36 h reaches a second peak of 0.59 because it is anti-phase. This is a property
of the *baseline*, not a weakness of the model: a diurnal quantity repeats, so
yesterday's value at this hour is a strong guess and at no other hour is.

Seventeen horizons cost ~57 s to train against ~40 s for six. Each is a
separately fitted and separately scored model, so the denser grid is measurement
rather than interpolation.

### Link 3 — per height, 65 days of wire data, summer only

Averaged over all fitted heights:

| Measurement | Fits | RMSE | vs reference | vs constant offset |
|---|---|---|---|---|
| temp | 10 | 0.91 °C | +0.55 | **+0.44** |
| hum | 10 | 1.86 % | +0.74 | +0.09 |
| co2 | 10 | 29.3 ppm | +0.24 | +0.09 |
| par | 10 | 113 µmol/m²/s | +0.70 | −0.02 |

**All 40 height fits beat reference-as-is.** The vertical gradient is real and
worth modelling.

But the last column is the more interesting one. Only **temperature** clearly
beats a single constant offset per height (+0.44) — its gradient genuinely
varies through the day. Humidity, CO₂ and PAR are close to a fixed offset or
ratio; for PAR the hour-varying model is marginally *worse* (−0.02). A constant
per-height factor would do nearly as well for three of the four.

Gradient scores (profile shape):

| Wire | Measurement | Profile RMSE | Sign agreement |
|---|---|---|---|
| WS_01_02 | temp | 1.10 °C | 84.9 % |
| WS_01_02 | hum | 1.69 % | 93.3 % |
| WS_01_02 | co2 | 17.4 ppm | 99.9 % |
| WS_01_02 | par | 173 | 84.6 % |
| WS_01_03 | par | 148 | 92.0 % |

## 5. Rejected and learned

*Kept live during implementation. A failure recorded the day it happens costs a
paragraph; reconstructed later it costs a re-run.*

### 5.1 Measuring link 3's coverage from the joined frame (bug, fixed)

Link 3's span was taken from the reference-plus-heights frame, which carries the
reference's full year. It reported **343 days** of wire coverage instead of 65,
and on that basis suggested enabling a seasonal term — exactly the false
confidence the rest of the design guards against. Now measured from the wire's
own non-null rows. Regression test:
`test_span_reflects_wire_coverage_not_the_references_history`.

### 5.2 Choosing a reference on skill alone (bug, fixed)

Ranking candidate references by mean skill picked `s2101`, which has no CO₂
sensor — silently dropping a target while reporting a better number. Coverage is
now the primary key. Regression test:
`test_wider_coverage_wins_over_a_marginally_better_score`.

### 5.3 Feeding every link-1 stage onward (fixed)

Wind was fitted at R² = −0.54 and still handed to link 2 as a feature. Stages
that cannot beat their own mean are now reported but not used.

### 5.4 A configured seasonality switch (rejected — measured instead)

Link 3 first shipped with `climate_model.link3_seasonal: false`, on the
reasoning that with one summer of wire data a day-of-year coefficient would fit
the trend *within* that season — confounded with canopy development — and
extrapolate it into months it had never seen.

That reasoning was half right and the default was wrong. Challenged on it, the
comparison was actually run:

| Measurement | RMSE without | with | Heights improved |
|---|---|---|---|
| temp | 0.995 °C | 0.927 | 5/10 |
| hum | 1.862 % | 1.933 | 3/10 |
| co2 | 29.85 ppm | 29.76 | 6/10 |
| **par** | **136.1** | **113.2** | **10/10** |

PAR improved at *every* height, by 17 %: sun angle shifts markedly between July
and September, and that genuinely changes how light reaches each level. Humidity
was the only measurement it hurt.

So neither setting of a global switch was right, and the honest resolution was
neither: **each (wire, measurement, height) is now fitted both ways and the
better out-of-fold score wins.** Per-height selection beats both fixed options
on every measurement (temp 0.907, hum 1.855, co2 29.27, par 113.2), and the
choice re-decides itself on every retrain — so a term that only starts helping
once the wires have seen a winter switches on without anyone remembering a flag.

What survives of the original caution: the folds are contiguous blocks, so a
chosen seasonal term has demonstrably generalised *forward in time* within the
observed range. That is the operative question for a 24-48 h forecast under
regular retraining. It is still not evidence that the term extrapolates to an
unobserved season, and it is not used that way.

### 5.5 Random cross-validation (avoided)

`dli/model.py` uses `RidgeCV(cv=5)` with random folds — tolerable on daily
aggregates, a serious leak on hourly lagged data where adjacent rows are near
duplicates. All folds here are contiguous blocks of whole calendar days.

### 5.6 Combined R² as a product of stages (avoided)

`dli/model.py` reports `stage1.r2 × stage2.r2`. That is an estimate of compounded
error, not a measurement of one, and it hides the train/serve mismatch where a
stage learns on measured inputs and is served predicted ones. Link 2 here trains
on **link 1's predictions**, and no product appears anywhere.

## 6. Limitations

1. **Link 3 is summer-calibrated.** 65 days, June–September 2026. It must be
   revalidated once the wires have seen a winter — including the day-of-year
   terms it currently selects, which have only ever been tested inside summer.
2. **Only one wire is complete.** `WS_01_02` alone reports all four measurements
   at all five heights; `WS_01_03` has lost temp/hum/CO₂, `WS_01_01` has lost PAR
   above H5. The per-wire intercept has very little to vary over.
3. **CO₂ is weakly predictable** at every horizon, and beaten by climatology in
   the middle of the range.
4. **A 46-day exclusion sits inside the training span** (2026-05-28 → 2026-07-12)
   whose cause is measured but unconfirmed — see
   `docs/red/wire-data-coverage.md`.
5. **Nothing here is validated against risk thresholds**, by design — see
   `red/docs/adr/0003-model-quality-scored-in-physical-units.md`.
6. **The chain cannot reach back before 2025-10-08.** Autoregressive features
   need a seeded indoor state, so the pre-sensor period stays unreachable until a
   weather-only variant exists.

## 7. The forecast view

`/climate/forecast` carries two charts, because they answer different
questions. It is listed in the **Multi Height** hub alongside the other
per-growth-section views, and the measured Crop Climate page links across to
it carrying the selected wire — the measured day and the forecast are the
same subject at different times.

**The lead: every section against the horizon, over the crop's envelope.**
Five lines, one per growth section, drawn over a neutral wash spanning the
coolest to the warmest — so the width of the shading is the vertical gradient at
a glance, while each section stays individually readable.

Three things are deliberate:

- **Sections take a single-hue ramp; outdoor takes neutral ink.** Light at the
  head, dark at the root: the sections are ordinal and the ramp says so, and
  with outdoor in grey the whole chart is one hue plus neutral.

  This is a deliberate tradeoff rather than a clean pass. Adjacent steps of a
  five-step one-hue ramp sit at **~9.7 ΔE**, under the 15 floor for telling two
  series apart *by colour alone*, and the lightness range is boxed in at both
  ends so widening does not help. Identity rests on the other channels instead,
  all of which are present: every line is direct-labelled at its end, the lines
  are stacked in the same order as the ramp, and the same numbers appear in the
  table beneath.

  Two alternatives were built and measured before settling here:

  - *Five categorical hues* (blue, aqua, violet, green, magenta) cleared the
    floor comfortably — ΔE 24.0 light / 20.9 dark — but read as a set rather
    than an order, which is the wrong thing to say about a crop profile.
  - *A red → blue gradient*, overlaid, collapses under red-green colour
    blindness: adjacent steps measure **CVD ΔE 1.9-3.0**, because a protanope
    cannot see the red component separating violet from blue. Structural, not
    tuning — it is why perceptual ramps such as viridis run blue → yellow.
    Viridis was tried too: its light end is built for heatmap fills and sits at
    1.85:1 on a white page, too faint for a 2 px line. Faceting into one panel
    per section would make the gradient work, and was built and then reverted —
    five stacked panels cost far more vertical space than the comparison was
    worth.

  Searching every five-step subset of the ramp confirmed the ceiling: ~9.8 ΔE
  between neighbours while keeping a light end still visible against the page,
  against 14.4 only if the top line falls to 1.29:1, which is too faint to
  trace. A surface-coloured halo under each line was tried as a way to separate
  them by an edge instead of by hue; it was reverted, because cutting five gaps
  through the envelope band looked worse than the problem it solved.

  Ramp step is keyed by **height, not by position among the sections present**,
  so a wire that has lost H4 does not repaint H5 with H4's step.

  The lightest step sits under 3:1 against the page, so the relief rule applies
  — and that made a latent bug load-bearing. Assigning the whole annotation list
  clobbered whichever label shared an index with the annotation `add_vline`
  attaches to the forecast divider, and **H1 silently lost its label**. Labels
  are appended one at a time now, and the dark-mode recolour matches them by
  text rather than by index.

- **One real time axis, −48 h to +48 h.** The measured half is drawn at the
  sensors' own cadence (resampled to 10 minutes, because the relay writes in
  bursts and raw points draw a ragged line); the forecast half shows only the
  horizons the chain was fitted and scored at. So the left of the chart is a
  dense record and the right is a handful of predicted points fanning out from
  it, parted by a marked "now".

  An earlier version spaced the horizons *evenly* on an ordinal axis, which
  needed the caveat that slope was not a rate of change. On a real time axis
  that caveat is gone — but the dashes between forecast markers are still drawn
  rather than predicted, and the page says so.

  The model still trains on hourly data; only the drawing is finer. Ten-minute
  *forecast* steps would mean fitting ~288 horizons per target instead of six,
  for interpolation between things the data barely distinguishes.

- **Uncertainty is stated once per horizon, not drawn five times.** Combined
  error is `√(link2² + link3²)` and link 2 dominates, so at a given horizon every
  section carries almost the same spread — measured at ±3.49 to ±3.53 across all
  five sections at +6 h. It is therefore a property of the *horizon*. Five
  nearly identical error ranges would bury the gradient the chart exists to
  show; a line of text under the axis does not. Per-section figures stay in the
  hover and the table.

An earlier version tracked one selectable section with error bars and drew the
rest only as an envelope. It was rejected as clumsy: with five sections, a
control to see one at a time costs more than it saves.

**Below it: the profile at each horizon**, extending the `wire_profile_chart`
idiom (value against height, H1 at the top, H5 at the root) that the
crop-climate views already use. Five near-parallel lines with overlapping error
bars is hard to read as a lead view, but it is the right view for reading the
shape of the crop at one moment.

**Profiles, not a curve.** The chain is fitted and scored at six horizons; a line
through time between them would draw forty-two hours nobody validated. Each
horizon is its own profile, and the axis is height.

**Error bars are the measured spread**, `√(link2_rmse² + link3_rmse²)` — an
approximation that assumes the two links' errors are independent. Link 3 was
scored against a *measured* reference so its error genuinely excludes link 2's,
but nothing guarantees they are uncorrelated. The page says "measured spread",
not "confidence interval".

**Horizons are ordinal, so colour is one hue.** A single-hue ramp steps away from
the page surface as the horizon grows; the measured profile is drawn in ink
because it is not a horizon. Both ramps are validated (one hue, monotone
lightness, worst-pair normal-vision ΔE 19.5 light / 19.2 dark). Dark steps are
selected for the dark surface, not flipped.

A horizon where link 2 does not beat persistence is drawn dotted and labelled
"no better than now" rather than dropped.

### 7.1 What the forecast reveals that the score table did not

- **The vertical gradient survives the chain.** At every horizon the predicted
  profile keeps its shape — head warmest, substrate coolest; humidity inverse.
  That is links 2 and 3 composing correctly end to end.
- **PAR is not usefully forecastable at plant level.** Predicted values around
  17-40 µmol/m²/s carry a combined spread of **±190-270**. The number is not
  wrong, it is uninformative, and the page shows it that way. Light at a height
  is the product of two weak links: CO₂-like weather dependence at link 2 and
  the constant-ratio-is-nearly-as-good result at link 3 (§4). Anyone wanting
  canopy light should read the DLI model, which predicts the *daily integral*
  and is a far better-posed question than the instantaneous value 48 h out.
- **A linear model predicts negative light.** Clamped where the number becomes a
  physical reading, not inside the fit, so residuals stay untouched.
- **The greenhouse's lift over outside is not a constant.** Visible only once
  the outdoor line was drawn: on one run the house ran **~2 °C above outside at
  05:00 and ~9 °C above at Tuesday midday**, with ~6 °C overnight. Whatever a
  model of the house is doing, it is not adding a fixed offset to the weather —
  which is why link 2 carries the time-of-day terms and the recent indoor state
  rather than a single transmission coefficient.
- **The crop is far more uniform at night**, and the measured history confirms
  it rather than the model asserting it. On one run the spread across sections
  was **5.8 °C at Tuesday midday and 0.9 °C at Wednesday 05:00** — measured, not
  predicted — with the forecast band narrowing the same way overnight. With no
  solar gradient to stratify it the greenhouse evens out, which also means a
  per-height model earns most of its keep during the day. Neither the profile
  chart nor the score table could show this: one plots a single moment, the
  other averages over all of them.

### 7.2 The model page

Performance is shown as matrices rather than tables, because the question is
"where does this work" and a grid answers that in one look:

- **Skill against each baseline**, target × horizon, on the **diverging** scale
  with grey at zero — blue beat the baseline, red lost to it. Two matrices, one
  per baseline: a model can beat "the value now" and still lose to "the average
  for this hour and month", and those are different failures. The range is
  symmetric about zero and floored at ±0.3, so a run where everything scored
  ±0.03 looks weak instead of painting itself in strong colour.
- **Link 3's skill against the no-gradient baseline**, height × (wire,
  measurement), same scale.
- **Held-out RMSE by hour of day**, horizon × hour, on the **sequential** scale.

Values are printed in every cell as well as encoded as colour, so each matrix is
also its own table, and the full numeric tables remain below.

### 7.3 What the hour-of-day matrix revealed

This diagnostic was specified in the plan, built as a helper, and then left
unwired until the page was redesigned — which is exactly how a diagnostic nobody
looks at gets skipped. Wiring it up changed the reading of the headline numbers.

Temperature at +6 h reports an overall RMSE of ~3.4 °C. By hour of day:

| hour | 04 | 06 | 09 | 12 | 15 | 18 | 22 |
|---|---|---|---|---|---|---|---|
| RMSE (°C) | 2.22 | **2.11** | 3.57 | **5.08** | 4.30 | 3.45 | 2.67 |

**The error is 2.4× larger at midday than before dawn.** The single figure is an
average over two quite different regimes: overnight, when the house is flat and
the model does well, and the middle of the day, when the solar swing is exactly
what it struggles with. That is also when persistence is easiest to beat and
when a grower most needs the forecast, so the honest summary is that the model
is weakest where it matters most.

It points somewhere specific too: the hours that fail are the hours the
greenhouse is being actively vented, which is the one input the chain does not
have (`air vent %` exists for nine dates in a spreadsheet — see the follow-ups).

### 7.4 Is the PAR/temperature difference seasonal?

Asked directly, and worth recording because the answer was not the obvious one.

**PAR is the *least* seasonal target, in relative terms.** Monthly-mean spread
as a fraction of overall spread: temp 0.339, hum 0.474, co2 0.405, **par 0.302**.
PAR's variance is dominated by the day/night cycle, which swamps the seasonal
component; indoor temperature is actively controlled, so its diurnal swing is
small and the seasonal drift is proportionally larger.

**Blocked folds do not single PAR out.** Blocked against random 5-fold CV, the
penalty is 13-30 % for temp, 20-32 % for par, 4-20 % for co2, 13-24 % for hum —
a broadly uniform honesty tax, which is the point of keeping blocked folds. A
random split would have hidden 13-32 % of the error for every target.

**But PAR's absolute error does swing with the season, because its magnitude
does.** Held-out RMSE at +1 h by month:

| | Jan | Mar | May | Jul | Sep | Nov |
|---|---|---|---|---|---|---|
| PAR (µmol/m²/s) | 62.7 | 130.1 | 207.3 | **240.8** | 161.3 | **63.6** |
| Temp (°C) | 1.1 | 1.3 | 1.5 | 1.4 | 1.2 | 0.9 |

**4.0× across the year for PAR against 1.6× for temperature.** PAR's headline
RMSE of ~164 is an average over that range — it overstates winter error and
understates summer error, and it is partly a property of the month rather than
of the model.

The first explanation offered for the winter figure — *"there is little light in
December, so there is little to get wrong"* — was **wrong**, and §7.5 records
why. There is plenty of light at the canopy in December; most of it is
artificial.

Two consequences, both now on the page:

- A **by-month matrix** beside the by-hour one. Like the hour diagnostic, it was
  specified in the plan and left unbuilt until someone asked the question it
  answers.
- Comparing RMSE *between* targets was never meaningful (different units), but
  this shows it is not reliably meaningful *within* PAR either. A relative error
  measure would be the honest way to state PAR's accuracy — filed as a
  follow-up rather than swapped in silently, because every recorded figure in
  this paper is absolute.

### 7.5 The PAR reference was lamp-contaminated (fixed)

**The defect.** `climate_model.par_reference` was **`s2100-02-par`**, the
under-lamp sensor — which `CONTEXT.md` defines as natural **+ lamp**. Link 2
predicted it from weather. Lamp hours are an operator's decision that weather
cannot explain.

Measured, per month, using hours where the above-lamp sensor reads zero natural
light and the canopy sensor still reads above 10 µmol/m²/s:

| month | lamp-only hours | lamp level | lamp share of canopy PAR |
|---|---|---|---|
| Oct 2025 | 6.3 % | 158 | 13.7 % |
| Nov 2025 | 26.4 % | 164 | 27.8 % |
| **Dec 2025** | **38.1 %** | 168 | **39.7 %** |
| Jan 2026 | 33.9 % | 157 | 34.3 % |
| Feb 2026 | 26.8 % | 154 | 24.4 % |
| Mar-Sep 2026 | ~0 % | — | ~0 % |

Lamps run November to February and are off from March. **Those shares are a
floor**: the method only counts hours with *no* natural light, so lamps
supplementing during daylight are invisible to it.

Two consequences:

1. **The winter PAR accuracy is flattered.** December's RMSE of 59.7 is low
   partly because ~40 % of the target is a near-constant lamp level that a
   day-of-year term can absorb. It is not evidence the model understands winter
   light, and it would degrade the moment the grower changed the lamp schedule.
2. **This is a documented failure being repeated.** `dli/MODEL_PAPER.md` §5.1
   records training on `s2100-02-par` directly as *failed* (r ≈ 0.523): "the
   model could not separate natural light from lamp light in the training
   signal". The DLI model therefore trains on `s2100-01-par` and applies
   attenuation afterwards. The climate model did not inherit that lesson.

The reference remained defensible for **link 3**, where it is like-for-like:
the wire PAR sensors hang under the lamps too. The defect was specifically link
2 predicting a partly-artificial quantity from weather.

**The fix — light is assembled, not predicted whole.** Config now names two PAR
references, and the chain splits at the lamp:

    canopy PAR = natural above lamp × attenuation + lamp contribution

- Link 2 predicts `s2100-01-par`, the **natural** part, which is what weather
  explains — the same target `dli/model.py` settled on for the same reason.
- **Attenuation** reuses `red/lamp.py`'s `compute_attenuation`, promoted out of
  `TwoStageLightModel` so both models share one number instead of computing
  their own. Measured 0.629 over 280 days, against the DLI paper's 0.622 and a later independent 0.625 over 268 days once daytime lamps were removed.
- **The lamp contribution is observed, not modelled**: `red/lamp.py` reads
  the level and the hours off the two sensors over a trailing fortnight, and the
  forecast assumes that schedule continues. Verified in both directions —
  December 2025 detects 190.7 µmol/m²/s over 23:00-06:00, April 2026 detects
  nothing. **That 23:00-06:00 was half the truth**: red runs the lamps through
  the short winter day too, which dark-hour detection cannot see. Sunlit hours
  are now judged on the above-lamp/canopy gap against half the measured lamp
  level, recovering 23:00-15:00 and 12.21 rather than 5.43 mol/m²/day of lamp
  DLI (`issues/054`).
- Link 3's reference is unchanged.

Hours are held as a **set of hours-of-day**, not a start/end pair: the winter
schedule runs across midnight, and a pair needs a wrap special-case that a set
does not.

**The detection bar had to be raised to 50 µmol/m²/s.** At the subtraction
threshold's 10.0 —
which is tuned for subtracting a lamp already known to be on — the detector
fired on 20.4 µmol/m²/s of pre-dawn September twilight, and a single spurious
hour becomes a lamp contribution added to every future forecast.

**The honest cost of the fix: PAR's reported numbers got worse.** At +1 h,
RMSE moved from 164 to 207 and the seasonal range widened from 4.0× to 5.1×.
Nothing regressed — the old figures were flattered by a near-constant lamp
floor that a day-of-year term could absorb. The chain now predicts a quantity
weather can actually explain, and says separately what the lamps are assumed to
add. A change to the lamp plan is not something weather can predict, so the
forecast page states the level, the hours, and where they came from.

## 8. Retraining

A full refit every time, from `climate_model.training_start` to now. The fits are
cheap (~30 s for the whole chain) and the record grows, so each run widens what
the model has seen. Two things make that improvement visible rather than
implicit: the span and row counts on the status page, and `TrainedChain.suggestions`
— config that has become improvable, such as a wire now reporting heights the
config does not declare. Whether link 3 uses a day-of-year term is not among
them: that is re-measured per fit on every run (§5.4).

Models live on ephemeral storage and are retrained on boot, so a restart costs a
background fit, never a stale artifact.
