# Two-Stage Light Prediction Model for Greenhouse DLI Forecasting

## Abstract

This paper presents a two-stage machine learning model (v7) for predicting Daily Light Integral (DLI) inside a greenhouse using publicly available weather forecast data. The model predicts above-lamp PAR via two Ridge regression stages, then applies a constant attenuation factor to estimate plant-level light. By decomposing the problem into interpretable stages — weather calibration, greenhouse transmission, and internal attenuation — we achieve robust predictions despite limited training data. We document the sensor investigation that led to the current architecture, including failed approaches (direct s2100-02 training, polynomial features) and the key insight that training on the above-lamp sensor with post-hoc attenuation outperforms training on the plant-level sensor directly.

## 1. Introduction

### 1.1 Problem Statement

Predicting indoor light levels in greenhouses is critical for:
- Supplemental lighting scheduling to meet plant DLI targets
- Energy cost optimization
- Crop growth modeling and yield prediction

The challenge: We want to predict indoor Photosynthetically Active Radiation (PAR) using only freely available weather forecasts (OpenMeteo API), without requiring expensive on-site weather stations for prediction (only for training).

### 1.2 Data Sources

| Source | Variables | Resolution | Role |
|--------|-----------|------------|------|
| OpenMeteo API | direct_radiation, diffuse_radiation, cloud_cover | Hourly | Predictor (available for forecasts) |
| s1000 Weather Station | lux | ~10 min | Intermediate target / local calibration |
| s2100-01-par | PAR (μmol/m²/s), above lamps | ~10 min | Stage 2 training target (natural light) |
| s2100-02-par | PAR (μmol/m²/s), under lamps | ~10 min | Attenuation validation (natural + lamp) |

## 2. Sensor Configuration & Investigation

### 2.1 Physical Setup

| Sensor | Position | What It Sees |
|--------|----------|-------------|
| `s2100-01-par` | **Above** lamps | Natural light only (no lamp contamination) |
| `s2100-02-par` | **Under** lamps | Natural light + lamp light (what plants receive) |

### 2.2 The Overestimation Problem

DLI schedule predictions consistently **overestimated** compared to actual plant-level readings:
- Predicted values formed a smooth curve
- Actual values showed "drops" and lower overall readings
- Initial hypothesis: sensor mismatch between training and evaluation

### 2.3 Key Observation: Ratio > 1

During daylight hours (08:00-16:00), `s2100-02-par` receives **more** light than `s2100-01-par`:

| Metric | Value |
|--------|-------|
| Mean ratio (s2100-02 / s2100-01) | ~2.2x |
| Correlation | High (sensors track together) |

During daytime with lamps ON:
- `s2100-01-par` (above lamps): natural light only
- `s2100-02-par` (under lamps): natural light + lamp light

### 2.4 Ratio Varies by Conditions

| Condition | Ratio | Interpretation |
|-----------|-------|----------------|
| Sunny (PAR >= 200) | ~0.8x | Natural light dominates, structural attenuation visible |
| Cloudy (PAR < 200) | ~2.95x | Lamp light dominates for s2100-02 |

This condition-dependent ratio made direct training on s2100-02 problematic — the model cannot separate natural from artificial light.

## 3. Model Architecture

### 3.1 Why Two Stages

A single-stage model (OpenMeteo → Indoor PAR) achieves poor performance because it must simultaneously learn:
1. How global weather data maps to local conditions
2. How outdoor light transmits through the greenhouse structure

By decomposing into two stages, each model learns a simpler, more interpretable relationship:

```
┌─────────────┐     Stage 1     ┌─────────────┐     Stage 2     ┌─────────────┐    ×atten.   ┌─────────────┐
│  OpenMeteo   │ ─────────────► │    s1000     │ ─────────────► │ s2100-01-par│ ──────────► │ Plant-Level │
│  Weather     │  Ridge CV      │   Outdoor    │  Ridge CV      │ (above lamp)│   ×factor    │  Estimate   │
│  Forecast    │                │   Lux        │                │             │             │             │
└─────────────┘                 └─────────────┘                 └─────────────┘             └─────────────┘
```

**Benefits:**
- Each stage is interpretable (weather calibration vs. transmission vs. attenuation)
- Errors can be diagnosed to specific stages
- Stage 1 could be reused for other outdoor predictions
- Stage 2 captures greenhouse-specific transmission
- Attenuation factor is physically meaningful and independently verifiable

### 3.2 Stage 1: Weather API Calibration

**Purpose:** Translate global weather model predictions to local ground-truth measurements.

**Input Features:**
- `direct_radiation_sum` - Daily sum of direct solar radiation (W/m²)
- `diffuse_radiation_sum` - Daily sum of diffuse/scattered radiation (W/m²)
- `cloud_cover_avg` - Daily average cloud cover (%)
- `day_of_year_sin`, `day_of_year_cos` - Cyclical seasonal encoding

**Output:** Predicted daily lux sum from the s1000 outdoor weather station.

**Rationale:** OpenMeteo provides modeled radiation values that may differ from actual ground measurements due to local terrain, microclimate, or model biases. This stage learns the systematic offset.

### 3.3 Stage 2: Roof Transmission

**Purpose:** Model how outdoor light transmits through the greenhouse roof to the above-lamp sensor.

**Input Features:**
- `lux_sum` - Daily outdoor lux (from Stage 1 prediction or actual s1000)
- `day_of_year_sin`, `day_of_year_cos` - Cyclical seasonal encoding

**Output:** Predicted daily above-lamp PAR sum (μmol/m²) at s2100-01-par position.

**Training target:** s2100-01-par — the sensor above the lamps that sees only natural light. This is key: it provides a clean signal free of lamp contamination.

**Rationale:** Greenhouse transmission varies with:
- Sun angle (captured by day-of-year features)
- Glass/covering transmissivity
- Structural shading patterns

### 3.4 Attenuation Factor

**Purpose:** Convert above-lamp PAR prediction to plant-level estimate.

The attenuation factor represents the ratio of lamp-corrected plant-level light to above-lamp light. It captures structural attenuation from lamps, fixtures, and other obstacles between the roof sensor and plant canopy.

**Why a constant factor works:**
- The rolling median of daily attenuation ratios is stable over time
- The ratio is computed from lamp-corrected data only, eliminating artificial light contamination
- Initial median ≈ 0.622, but this includes days where leaves partially occlude the plant-level sensor, dragging the median down

**Computation:**
1. Derive daily lamp profile from s2100-01 (daylight detection) and s2100-02 (lamp power from pre-sunrise/post-sunset readings)
2. Subtract lamp contribution from s2100-02 readings to get natural-only plant-level PAR
3. Compute daily ratio: corrected_plant_daily / above_lamp_daily
4. Use median of filtered days as the constant factor
5. Days >2σ below rolling median are flagged as occlusion events (excluded from median)

**Observation: 0.622 underestimates on high-light days.** Testing with 0.8 produced better predictions on days with strong natural light peaks. The likely cause: the current >2σ outlier filter is too conservative — many days with partial leaf occlusion still pass the filter and pull the median down. More aggressive filtering of low-ratio days (e.g., a minimum ratio threshold or tighter σ cutoff) should bring the computed median closer to the true structural attenuation, without the plant canopy effect. This is a planned improvement.

## 4. Design Choices

### 4.1 Daily vs. Hourly Aggregation

We train on **daily aggregates** rather than hourly data.

| Aggregation | Correlation (r) | Samples |
|-------------|-----------------|---------|
| Hourly | 0.685 | 579 |
| Daily | 0.906 | 88 |

**Justification:**
- Hourly data has high noise from transient clouds, sensor lag, timestamp misalignment
- Daily totals smooth out noise while preserving the signal
- DLI is inherently a daily metric — we care about total light per day
- Fewer samples but much higher signal-to-noise ratio

### 4.2 Cyclical Day-of-Year Encoding

We encode day-of-year as sine/cosine pairs rather than a linear feature:

```python
day_of_year_sin = sin(2π × day / 365)
day_of_year_cos = cos(2π × day / 365)
```

**Justification:**
- Day 1 and day 365 are adjacent (winter), but linear encoding treats them as maximally distant
- Sine/cosine encoding preserves cyclical continuity
- Two features capture both position in cycle and rate of change
- Standard practice in time series ML

### 4.3 Direct + Diffuse Radiation

We use both direct and diffuse radiation rather than just total shortwave.

**Justification:**
- Direct radiation comes from the sun's disk; diffuse is scattered by atmosphere
- They have different transmission characteristics through glass
- On cloudy days, diffuse dominates; on clear days, direct dominates
- Separating them gives the model more information to work with

### 4.4 Ridge Regression with Cross-Validation

We use `RidgeCV` rather than ordinary least squares (OLS) or other models.

**Why Ridge over OLS:**
- Features are correlated (direct/diffuse radiation, sin/cos pairs)
- Ridge regularization prevents coefficient explosion from multicollinearity
- Small dataset benefits from regularization to prevent overfitting

**Why Ridge over Lasso:**
- We don't need feature selection (all features are meaningful)
- Ridge keeps all features with shrunk coefficients
- More stable predictions

**Why Linear over Complex Models:**
- Limited training data is insufficient for deep learning or ensemble methods
- Linear relationships are physically plausible (light transmission is roughly linear)
- Interpretable coefficients aid debugging
- Polynomial features were tested but caused overfitting (see Section 5.3)

**Cross-Validation:**
- `RidgeCV` tests alphas [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]
- 5-fold CV selects optimal regularization strength automatically
- Prevents manual tuning and adapts to data characteristics

### 4.5 Feature Scaling

All features are standardized (zero mean, unit variance) before Ridge regression.

**Justification:**
- Ridge penalty is scale-dependent; unscaled features would bias regularization
- Features have vastly different scales (radiation in thousands, cloud cover 0-100)
- Standardization ensures equal regularization pressure across features

## 5. Experiments & Lessons Learned

### 5.1 Training on s2100-02-par Directly (Failed)

**Approach:** Train Stage 2 on raw s2100-02-par (plant-level sensor).

**Result:** Poor correlation (r ≈ 0.523). The model could not separate natural light from lamp light in the training signal, leading to systematic overestimation during prediction (when lamps aren't modeled).

**Lesson:** When the training target contains mixed signals, the model learns the wrong relationship.

### 5.2 Lamp-Corrected s2100-02-par (Partial Success)

**Approach:** Derive lamp power from pre-sunrise/post-sunset readings of s2100-02, subtract from all readings, then train on the corrected signal.

**Algorithm:**
1. Use s2100-01-par to define daylight hours (clean reference)
2. Measure lamp PAR during lamp-only hours (before sunrise / after sunset)
3. Subtract lamp power from s2100-02-par during lamp-on hours
4. Aggregate corrected values to daily sums for training

**Result:** Improved correlation compared to raw, but still noisier than s2100-01. Plant-level sensor experiences variable occlusion from canopy growth, moving equipment, and other greenhouse operations that introduce irreducible noise.

**Lesson:** Lamp correction improves the signal but cannot remove physical occlusion noise.

### 5.3 Polynomial Features (Failed)

**Approach (v6):** Add degree-2 polynomial interaction features to capture non-linear relationships.

**Result:** R² jumped to 0.978 on training data — classic overfitting. Predictions degraded significantly on held-out data. With only ~88 training samples, polynomial features create far too many parameters relative to observations.

**Lesson:** At small sample sizes, model complexity is the enemy. Linear models with regularization outperform complex models that memorize training noise.

### 5.4 Retargeting to s2100-01-par (Current — v7)

**Approach:** Train Stage 2 on s2100-01-par (above-lamp, natural light only), then apply a constant attenuation factor to reach plant-level estimates.

**Why this works:**
- s2100-01-par provides a clean signal — no lamp contamination, no canopy occlusion
- The above-lamp to plant-level ratio is stable once low-ratio (occluded) days are filtered
- Splitting transmission and attenuation into separate steps matches physical reality
- The attenuation factor can be independently validated against the ratio time series

**Result:** This is the current production model with the best real-world prediction accuracy.

### 5.5 Summing readings instead of integrating time (bug, fixed — v10)

**Approach (v4-v9):** a daily total was `groupby("date").sum()` over the raw
sensor rows — `lux_sum` for stage 1's target, `par_sum` for stage 2's.

**Result:** the target measured how often the sensor reported, not how much light
there was. Red's s1000 fell from ~270 readings a day to **97 in June 2026** while
its mean lux was the highest of the year; its summed daily lux collapsed to a
third on the brightest days of the year. Stage 1 was being asked to predict a
sampling schedule from the weather, which is why it had no out-of-fold skill at
all (R² −0.04, worse than its own mean).

It also flattered stage 2. Both its input and its target were reading-sums from
sensors behind the same gateway, so the cadence artefact partly cancelled
between them: stage 2's honest out-of-fold R² is 0.978, but it reached that only
once *both* sides were integrals. Fixing one side alone dropped it to 0.852.

**Fix:** `calculator.integrate_over_time` — a trapezoidal integral over the
timestamps, in one place, used by `calculate_daily_dli` and by both daily
aggregates. Stage 1's target is now lux-hours and stage 2's is a PAR integral in
μmol/m², which also removes the last reading-cadence assumption from
`predict_dli`: a DLI is that integral divided by 10⁶, with no `readings_per_day`
in it.

**Lesson:** a daily total of a sampled quantity is an integral. A sum of rows is
a measurement of the sampler.

### 5.6 Seasonal features in stage 1 (rejected — measured, not argued)

Stage 1 carried `day_of_year_sin/cos` from v5. Holding the weather constant and
moving only the date, the fitted chain predicted **×2.15** more light in June
than December — while a **16×** change in actual beam radiation moved it only
×1.74. The calendar outweighed the weather, so within any month the model could
barely tell a brilliant day from a dull one, and it regressed to the seasonal
mean. That is what clipped the summer peaks.

The cause is collinearity, not a bad approximation: radiation and day-of-year say
the same thing over a year, ridge spreads weight across both, and the radiation
coefficient is left too small. Every candidate was scored end to end, out of
fold, across 4-10 fold counts (chain skill against persistence, mean):

| stage 1 features | mean | min |
|---|---|---|
| shortwave alone | **+0.239** | +0.213 |
| direct + diffuse + cloud | +0.232 | +0.198 |
| shortwave + cloud | +0.227 | +0.209 |
| clear-sky index + TOA envelope + beam + cloud | +0.185 | +0.152 |
| clear-sky index + TOA envelope + cloud | +0.124 | +0.106 |
| direct + diffuse + cloud + day-of-year (v5-v9) | +0.069 | −0.018 |

An **exact** top-of-atmosphere envelope from OpenMeteo's `terrestrial_radiation`
scored *worse* than no seasonal feature at all, so this is not about the harmonic
being crude — it is that stage 1 must carry no calendar term of any kind. The
radiation already is the season.

Beam and diffuse were split in §4.3 because they transmit through glass
differently. That is stage 2's concern: stage 1 maps a modelled sky onto a lux
sensor standing in the open, where no glass is involved, and splitting them there
only costs it. Stage 1 is now **global horizontal irradiance alone**.

Stage 2 keeps its day-of-year term — the one place a seasonal feature earns its
place, standing in for the angle sunlight strikes the glass at. Dropping it, and
swapping it for a clear-sky index, each made the *chain* worse even where they
improved the stage in isolation.

## 6. Performance

### 6.1 Version Evolution

Everything from v8 is **out-of-fold** on day-blocked folds, scored through
`red/fitting.py`. Earlier figures are in-sample and not comparable; they are kept
to show what the gap was.

| Version | Stage 1 | Stage 2 | Chain | Changes |
|---------|---------|---------|-------|---------|
| v5-v7 | 0.786* | 0.914* | 0.719* | *in-sample; chain was the product of the two |
| v8 | −0.036 | 0.977 | 0.655 | first out-of-fold scores; chain measured, not derived |
| v9 | 0.213 | 0.977 | 0.805 | stage 1 loses its day-of-year term (§5.6) |
| **v10** | **0.917** | **0.978** | **0.926** | daily totals are time integrals (§5.5) |

Skill against the baselines, v10, out-of-fold:

| Stage | vs persistence | vs climatology |
|---|---|---|
| 1 — weather → s1000 lux | +0.532 | +0.684 |
| 2 — lux → indoor PAR | +0.735 | +0.829 |
| **chain — weather → indoor PAR** | **+0.517** | **+0.688** |

At v7 the chain was level with "same as yesterday" (−0.018 against persistence)
while reporting a combined R² of 0.719. The product was never a bound on
anything: it assumed an error propagation nobody had measured, and credited
stage 2 with an input it never receives. The chain figure above is obtained by
fitting stage 2 on measured lux and predicting held-out days from stage 1's
*predicted* lux, which is what serving does.

### 6.2 Summer peaks

The symptom that started the v9/v10 work: on the brightest days the measured DLI
ran far above the prediction. Over 2026-07-13 → 09-10, above-lamp, the eight
brightest days:

| | mean bias on the 8 brightest | MAPE, all 60 days |
|---|---|---|
| v8 | −30.6% | 23.4% |
| v9 (no seasonal term in stage 1) | −19.9% | 19.0% |
| **v10 (+ time integrals)** | **−12.3%** | **18.9%** |

A residual compression remains — the model still underpredicts the top of the
range and overpredicts the bottom. Stage 2 is now the place to look: it is linear
in lux, and the brightest days are where a linear transmission model has least
room.

### 6.3 Correlation Analysis

| Level | Pearson r | Notes |
|-------|-----------|-------|
| Hourly (raw) | 0.685 | High noise |
| Daily (aggregated) | 0.906 | Used for training |

## 7. Limitations

### 7.1 Sample Size
- ~317 days for stage 1 and ~271 for stage 2 (training starts 2025-11-01)
- Still thin for anything richer than a regularised linear fit; §5.3's
  polynomial failure was at 88 days, and the margin has not grown much
- One full year of seasonal coverage, no more: nothing here has been validated
  against a second spring

### 7.2 Sensor Specificity
- Model is trained for specific sensor positions
- Different greenhouse locations would need recalibration
- Assumes consistent sensor operation (no drift, no obstructions)

### 7.3 Attenuation Factor Sensitivity
- Current >2σ outlier filter is too conservative — many partial-occlusion days pass and drag the median down (0.622 vs ~0.8 observed as better fit on high-light days)
- Next step: more aggressive filtering of low-ratio days (minimum ratio threshold or tighter σ) to isolate the true structural attenuation from canopy interference
- May need periodic recalibration as growing conditions change

### 7.4 No Lamp Modeling
- Model predicts natural light only
- Supplemental lamp contribution is inferred separately from historical data
- Lamp schedule changes require re-inference

### 7.5 Weather Forecast Accuracy
- Stage 1 calibration cannot correct for weather forecast errors
- Prediction accuracy degrades with forecast horizon
- Model trained on historical (actual) weather, applied to forecasts

## 8. Conclusion

The two-stage architecture with post-hoc attenuation successfully decomposes a complex prediction problem into physically interpretable components. The key insight from our sensor investigation is that **training on the cleanest signal (above-lamp) and applying a constant attenuation factor outperforms training on the noisier plant-level signal directly** — even with lamp correction. This is because the above-lamp sensor avoids both lamp contamination and plant canopy occlusion, producing a training signal that better represents the physical relationship between outdoor and indoor natural light.

By aggregating to daily resolution and using regularized linear regression, we achieve robust predictions despite limited training data. The model's simplicity is a feature, not a bug — it generalizes well and provides interpretable coefficients that can be validated against physical intuition.

**Data quality beats model complexity at small sample sizes.**

---

*Model Version: 10 (time-integrated daily totals, no seasonal term in stage 1)*
*Results above measured 2026-09-18*
*Data Range: November 2025 – February 2026*
