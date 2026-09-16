"""What red's lamps are doing, read off the two PAR sensors.

The lamps are a greenhouse fact, not a DLI concept or a climate concept. Both
models need the same two numbers — how much natural light survives the trip to
the canopy, and how much light the lamps add — so both read them from here.

    canopy PAR = natural above lamp × attenuation + lamp contribution

- **attenuation** is measured on lamp-corrected days, so it describes structure
  (glass, fixtures, the gap between the two sensors) rather than lighting.
- **lamp contribution** is *observed, not modelled*: the level the lamps run at
  and the hours they have recently been on.

**Lamp light is never inferred from model error.** An earlier design derived it
as ``max(0, measured − modelled)`` per hour. That estimator cannot return zero:
it keeps positive residuals and discards negative ones, so any disagreement
between the greenhouse's intraday shape and the open-field radiation curve is
rectified into light, and the bias grows with model error instead of shrinking.
On a long June day with the lamps off it invented ~5 mol/m²/day of lighting,
placed on plausible-looking morning and evening hours. Reading the lamps off
the sensors is indifferent to how good the light model is.

**The forward assumption is that the recent schedule continues.** The model does
not know tomorrow's lamp plan, it knows the last fortnight's. A schedule change
makes the light forecast wrong in a way no amount of weather data would catch,
which is why pages say where the lamp figure came from.

Hours are held as a **set of hours-of-day** rather than a start/end pair, because
a winter schedule runs across midnight and a start/end pair has to special-case
the wrap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import IntEnum

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from wp6_data.shared.aggregation import resample_hourly

# An hour counts as lamp-lit when the canopy sensor reads above this while the
# above-lamp sensor sees effectively no daylight.
#
# The lamp bar is deliberately higher than ``LAMP_SUBTRACTION_THRESHOLD``, which
# is tuned for subtracting a lamp already known to be on. Here the question is
# whether the lamps are running at all, and at 10.0 the detector fired on
# pre-dawn twilight: 20.4 µmol/m²/s at 04:00 in September, against a measured
# winter lamp level of 155-168. A single spurious hour becomes a lamp
# contribution added to every future forecast, so the bar sits well above the
# noise and well below the real level.
DAYLIGHT_THRESHOLD = 5.0
LAMP_THRESHOLD = 50.0

# How far back the schedule is read, and how often an hour must have been lit
# across that window to be carried forward.
RECENT_DAYS = 14
HOUR_ON_SHARE = 0.5

# Days either side of a date whose residuals decide whether that date's daylight
# hours were lit, for the calendar. Thresholding each cell on its own speckles:
# 12% of red's December daylight cells fall the wrong side of the bar, up to 30%
# at noon where attenuation error is largest, which draws as lamps flickering
# hour to hour. A rolling median cleans that up without freezing one schedule
# across a calendar that spans seasons.
SCHEDULE_ROLLING_DAYS = 15

# What the bootstrap slope needs before it is worth fitting: enough bright hours,
# and enough variation in the above-lamp reading among them for a slope to mean
# anything. Expressed as the interquartile spread relative to the median.
# A sunlit hour is lamp-lit when the canopy outshines the roof sensor above it.
# That is a physical impossibility for a passive loss, not a tuned threshold, and
# it needs no attenuation estimate — which is what keeps the daylight test free
# of the circularity that dogged every alternative (the lamp must be known to
# measure attenuation, and attenuation was needed to find the lamp).
#
# A residual test was tried first and fails across seasons: its error scales with
# the above-lamp reading while its bar does not, so summer mornings — genuine
# attenuation ~0.77 against a year-wide estimate of 0.52 — read as lamps. With
# the ratio test, May/July/August detect exactly zero daylight lamp hours while
# Nov-Feb detect 8.1-9.6 per day.
LAMP_RATIO_CEILING = 1.0

# Thresholds for the per-day profile used by attenuation. Lower than
# ``LAMP_THRESHOLD`` on purpose: by the time these run, the day has already been
# split into daylight and dark, so the question is how much lamp to remove
# rather than whether any lamp is on.
LAMP_SUBTRACTION_THRESHOLD = 10.0
MIN_LAMP_READINGS = 3


@dataclass(frozen=True)
class LampModel:
    """What the lamps are doing, as far as the sensors can tell."""

    attenuation: float
    attenuation_days: int
    power_par: float | None
    hours_on: frozenset[int]
    observed_days: int
    schedule_from: date | None = None
    attenuation_source: str = "measured"  # "measured" | "supplied" | "unknown"

    @property
    def is_lighting(self) -> bool:
        return bool(self.hours_on) and self.power_par is not None

    def lamp_par_at(self, moment: datetime) -> float:
        """Lamp PAR at ``moment``, assuming the recent schedule continues."""
        if not self.is_lighting:
            return 0.0
        return float(self.power_par) if moment.hour in self.hours_on else 0.0

    def hourly_schedule(self) -> dict[int, float]:
        """Lamp PAR per hour-of-day — all zeros when the lamps are not running.

        The shape ``dli.schedule`` wants: every hour present, so a caller can
        sum it into a daily lamp DLI without worrying about missing keys.
        """
        if not self.is_lighting:
            return dict.fromkeys(range(24), 0.0)
        return {h: (float(self.power_par) if h in self.hours_on else 0.0) for h in range(24)}

    def canopy_par(self, natural_above_lamp: float, moment: datetime) -> float:
        """Canopy PAR from a predicted above-lamp natural value."""
        natural = max(0.0, natural_above_lamp) * self.attenuation
        return natural + self.lamp_par_at(moment)


def derive_lamp_model(
    above_lamp_df: pd.DataFrame,
    canopy_df: pd.DataFrame,
    *,
    recent_days: int = RECENT_DAYS,
    attenuation: float | None = None,
) -> LampModel:
    """Read the lamps off the two PAR sensors.

    ``above_lamp_df`` and ``canopy_df`` are ``time``/``value`` frames for
    ``s2100-01-par`` and ``s2100-02-par``. Returns a model with attenuation 1.0
    and no lighting when the sensors cannot tell — a greenhouse that is not
    lighting and one whose sensors are silent both yield "no lamp", so the
    caller is told how many days were actually observed.

    **The two halves want different windows, and only one of them is
    ``recent_days``.** The *schedule* is an operator decision, so it is read from
    the trailing ``recent_days`` of the frames. *Attenuation* is structure —
    glass, fixtures, the gap between the sensors — so it is measured over
    everything the frames contain, and needs lamp-free daylight to be
    identifiable at all. A fortnight of January contains none: the lamps run
    through the short day, inflating the canopy sum until the ratio comes out
    above 1, which is impossible for a loss.

    So a caller holding a value fitted over a long window — the trained DLI
    model keeps one — should pass it as ``attenuation`` rather than let a short
    or seasonal window try to rediscover it. ``attenuation_source`` records
    which happened.
    """
    if above_lamp_df.empty or canopy_df.empty:
        return LampModel(1.0, 0, None, frozenset(), 0, attenuation_source="unknown")

    if attenuation is not None:
        attenuation_days, attenuation_source = 0, "supplied"
    else:
        attenuation, attenuation_days = compute_attenuation(above_lamp_df, canopy_df)
        attenuation_source = "measured" if attenuation_days else "unknown"

    above = _hourly(above_lamp_df)
    canopy = _hourly(canopy_df)
    joined = pd.concat([above.rename("above"), canopy.rename("canopy")], axis=1).dropna()
    if joined.empty:
        return LampModel(attenuation, attenuation_days, None, frozenset(), 0,
                         attenuation_source=attenuation_source)

    cutoff = joined.index.max() - pd.Timedelta(days=recent_days)
    recent = joined[joined.index >= cutoff]
    if recent.empty:
        return LampModel(attenuation, attenuation_days, None, frozenset(), 0,
                         attenuation_source=attenuation_source)

    hours_on, power_par = _schedule_over(recent)
    if power_par is None:
        return LampModel(
            attenuation, attenuation_days, None, frozenset(),
            observed_days=int(recent.index.normalize().nunique()),
            schedule_from=recent.index.max().date(),
            attenuation_source=attenuation_source,
        )

    return LampModel(
        attenuation=attenuation,
        attenuation_days=attenuation_days,
        power_par=power_par,
        hours_on=hours_on,
        observed_days=int(recent.index.normalize().nunique()),
        schedule_from=recent.index.max().date(),
        attenuation_source=attenuation_source,
    )


def _min_indoor_par() -> float:
    """The daily PAR sum below which the indoor sensor was not really measuring.

    Imported lazily: ``red.dli``'s package ``__init__`` imports ``dli.schedule``,
    which imports this module, so reaching into ``red.dli.constants`` at module
    level would close a cycle. The dependency runs dli -> lamp, and stays that
    way.
    """
    from wp6_data.red.dli.constants import MIN_INDOOR_PAR

    return MIN_INDOOR_PAR


class LampState(IntEnum):
    """What one hour of the greenhouse looked like.

    Ordered so the value doubles as a heatmap level: recessive night, then
    daylight, then the two lamp states on top.
    """

    DARK = 1          # no daylight reaching the greenhouse, and no lamp either
    DAYLIGHT = 2      # sun, and the lamps are off
    DAYLIGHT_LIT = 3  # sun *and* lamps — winter's supplementary lighting
    LIT = 4           # canopy is bright while the above-lamp sensor is dark: lamps


def lamp_state_grid(
    above_lamp_df: pd.DataFrame,
    canopy_df: pd.DataFrame,
) -> pd.DataFrame:
    """One row per observed hour: which state it was in, and the readings behind it.

    The same two-sensor test :func:`derive_lamp_model` uses to measure the lamps,
    exposed per hour so it can be looked at rather than trusted. Hours where
    either sensor is silent are **absent** from the frame, so a reader can tell a
    dark greenhouse from a dead sensor.

    Sunlit hours the lamps were also running are marked ``DAYLIGHT_LIT``. Red
    runs its lamps through the short winter day, so without that distinction a
    winter schedule reads as about half its real length.

    Days whose above-lamp sensor saw less than ``MIN_INDOOR_PAR`` in total are
    **dropped**, because a sensor that is switched off or out of the greenhouse
    reports zeros rather than nothing, and zeros are indistinguishable from a
    dark greenhouse once they reach a chart. Red's PAR sensors were out for six
    weeks in summer 2026, which would otherwise draw as solid midsummer night.
    The same gate the model's training uses, and it separates cleanly: the
    dimmest real December day still reads 25x it.

    Returns ``date, hour, state, above_par, canopy_par``.
    """
    if above_lamp_df.empty or canopy_df.empty:
        return pd.DataFrame(columns=["date", "hour", "state", "above_par", "canopy_par"])

    above = _hourly(above_lamp_df)
    canopy = _hourly(canopy_df)
    joined = pd.concat([above.rename("above_par"), canopy.rename("canopy_par")], axis=1).dropna()
    if joined.empty:
        return pd.DataFrame(columns=["date", "hour", "state", "above_par", "canopy_par"])

    # Drop days the above-lamp sensor was not really measuring (see docstring).
    measuring = joined.groupby(joined.index.date)["above_par"].transform("sum")
    joined = joined[measuring > _min_indoor_par()]
    if joined.empty:
        return pd.DataFrame(columns=["date", "hour", "state", "above_par", "canopy_par"])

    is_daylight = joined["above_par"] >= DAYLIGHT_THRESHOLD
    is_lit = ~is_daylight & (joined["canopy_par"] > LAMP_THRESHOLD)

    grid = joined.reset_index()
    grid["date"] = grid["time"].dt.date
    grid["hour"] = grid["time"].dt.hour
    daylight_lit = _lit_mask(
        joined.rename(columns={"above_par": "above", "canopy_par": "canopy"})
    ) & is_daylight.to_numpy()
    grid["state"] = np.select(
        [is_lit.to_numpy(), daylight_lit, is_daylight.to_numpy()],
        [int(LampState.LIT), int(LampState.DAYLIGHT_LIT), int(LampState.DAYLIGHT)],
        default=int(LampState.DARK),
    )
    return grid[["date", "hour", "state", "above_par", "canopy_par"]]


def _lit_mask(joined: pd.DataFrame) -> np.ndarray:
    """Per ``(date, hour)`` verdict: were the lamps on?

    Dark hours are judged per cell — canopy light with no sun to explain it.

    Sunlit hours are judged on ``canopy / above`` exceeding
    :data:`LAMP_RATIO_CEILING`, taken as a **rolling median** across
    ``SCHEDULE_ROLLING_DAYS`` around each date. Rolling because the schedule is
    seasonal: a single ``hours_on`` for a long window is wrong in both
    directions at once — over red's Nov-Sep training range no daylight hour is
    lit on half the days, so it collapses to 8 night hours, leaving winter's
    daytime lamps unsubtracted *and* subtracting those hours from summer daylight.

    A median rather than each cell alone because 12% of December's daylight cells
    fall the wrong side of the bar, which draws as lamps flickering hour to hour.
    """
    above, canopy = joined["above"], joined["canopy"]
    dark_lit = ((above < DAYLIGHT_THRESHOLD) & (canopy > LAMP_THRESHOLD)).to_numpy()

    daylight = (above >= DAYLIGHT_THRESHOLD).to_numpy()
    if not daylight.any():
        return dark_lit

    frame = pd.DataFrame({
        "date": joined.index.normalize(),
        "hour": joined.index.hour,
        "ratio": np.where(daylight, canopy / above.where(above > 0, np.nan), np.nan),
    })
    grid = frame.pivot_table(index="date", columns="hour", values="ratio", aggfunc="median")
    rolled = grid.rolling(SCHEDULE_ROLLING_DAYS, center=True, min_periods=1).median()
    lit_lookup = rolled > LAMP_RATIO_CEILING

    day_lit = np.array([
        bool(lit_lookup.at[d, h]) if d in lit_lookup.index and h in lit_lookup.columns else False
        for d, h in zip(frame["date"], frame["hour"], strict=True)
    ])
    return dark_lit | (day_lit & daylight)


def _schedule_over(frame: pd.DataFrame) -> tuple[frozenset[int], float | None]:
    """The lamp schedule and level over ``frame``, as far as the sensors can tell.

    One rule, used both by :func:`derive_lamp_model` over a recent fortnight and
    by :func:`compute_attenuation` over everything it was given — the two differ
    in window, never in what counts as a lamp.

    Dark hours set the level; daylight hours are added by :func:`_lit_mask`,
    which asks only whether the canopy outshone the roof and so needs no
    attenuation of its own.

    Returns ``(hours_on, power_par)``; ``(frozenset(), None)`` when the dark
    hours show no lamp, which is the only evidence that can establish a level.
    """
    dark_lit = (frame["above"] < DAYLIGHT_THRESHOLD) & (frame["canopy"] > LAMP_THRESHOLD)
    if not dark_lit.any():
        return frozenset(), None

    # An hour is carried forward when it was lit on most of the days that could
    # have shown it lit — a single unusual night does not become the schedule.
    share = pd.DataFrame(
        {"hour": frame.index.hour, "lit": dark_lit.to_numpy()}, index=frame.index
    ).groupby("hour")["lit"].mean()
    hours_on = frozenset(int(hour) for hour, value in share.items() if value >= HOUR_ON_SHARE)

    power_par = round(float(np.median(frame.loc[dark_lit, "canopy"])), 1)

    # Hours of day the rolling ratio test found lit while the sun was up.
    lit = _lit_mask(frame)
    daylight_lit = lit & (frame["above"] >= DAYLIGHT_THRESHOLD).to_numpy()
    if daylight_lit.any():
        share = pd.Series(daylight_lit, index=frame.index).groupby(frame.index.hour).mean()
        hours_on |= frozenset(
            int(h) for h, v in share.items() if v >= HOUR_ON_SHARE
        )
    return hours_on, power_par


def _hourly(df: pd.DataFrame) -> pd.Series:
    return resample_hourly(df).set_index("time")["value"]


def derive_daily_lamp_profile(
    above_lamp_df: pd.DataFrame,
    plant_level_df: pd.DataFrame,
    daylight_threshold: float = DAYLIGHT_THRESHOLD,
    lamp_threshold: float = LAMP_SUBTRACTION_THRESHOLD,
    min_lamp_readings: int = MIN_LAMP_READINGS,
) -> pd.DataFrame:
    """Derive daily lamp profile from above-lamp and plant-level sensors.

    Uses s2100-01-par (above lamps) to determine sunrise/sunset, then measures lamp power
    from s2100-02-par during lamp-only hours (before sunrise / after sunset).

    Args:
        above_lamp_df: PAR readings from sensor above lamps (s2100-01-par).
            Columns: device, sensor, time, value
        plant_level_df: PAR readings from sensor at plant level (s2100-02-par).
            Columns: device, sensor, time, value
        daylight_threshold: PAR threshold to detect daylight on above-lamp sensor.
        lamp_threshold: Minimum PAR on plant-level sensor to count as lamp-on.
        min_lamp_readings: Minimum lamp-only readings needed; fewer → lamps treated as off.

    Returns:
        DataFrame with columns: date, sunrise, sunset, lamp_hours, lamp_start,
        lamp_end, lamp_power_par, n_lamp_only_readings.

        ``lamp_hours`` is the **set** of hours-of-day that were lamp-lit and is
        what callers should subtract against. ``lamp_start``/``lamp_end`` are its
        min and max, kept for display only: a schedule that runs across midnight
        (23:00-06:00, red's real December one) has min 0 and max 23, which as a
        range means the whole day and as a wrap means nothing.
    """
    above = above_lamp_df.copy()
    plant = plant_level_df.copy()

    above["time"] = pd.to_datetime(above["time"], utc=True)
    plant["time"] = pd.to_datetime(plant["time"], utc=True)

    above["date"] = above["time"].dt.date
    above["hour"] = above["time"].dt.hour
    plant["date"] = plant["time"].dt.date
    plant["hour"] = plant["time"].dt.hour

    # Get unique dates present in both sensors
    common_dates = sorted(set(above["date"]) & set(plant["date"]))

    records = []
    for day in common_dates:
        day_above = above[above["date"] == day]
        day_plant = plant[plant["date"] == day]

        # Determine sunrise/sunset from above-lamp sensor (hourly aggregation)
        hourly_above = day_above.groupby("hour")["value"].mean()
        daylight_hours = hourly_above[hourly_above > daylight_threshold].index.tolist()

        if daylight_hours:
            sunrise = min(daylight_hours)
            sunset = max(daylight_hours)
        else:
            # No daylight detected — entire day is dark (winter edge case)
            sunrise = None
            sunset = None

        # Find lamp-only hours on plant-level sensor: outside daylight, PAR > lamp_threshold
        if sunrise is not None and sunset is not None:
            lamp_only_mask = (
                ((day_plant["hour"] < sunrise) | (day_plant["hour"] > sunset))
                & (day_plant["value"] > lamp_threshold)
            )
        else:
            # No daylight — all hours with PAR above threshold are lamp-only
            lamp_only_mask = day_plant["value"] > lamp_threshold

        lamp_only = day_plant[lamp_only_mask]
        n_lamp_only = len(lamp_only)

        if n_lamp_only >= min_lamp_readings:
            lamp_power_par = float(np.median(lamp_only["value"]))
            lamp_hours = frozenset(int(h) for h in lamp_only["hour"].unique())
            lamp_start = min(lamp_hours)
            lamp_end = max(lamp_hours)
        else:
            lamp_power_par = None
            lamp_hours = frozenset()
            lamp_start = None
            lamp_end = None

        records.append({
            "date": day,
            "sunrise": sunrise,
            "sunset": sunset,
            "lamp_hours": lamp_hours,
            "lamp_start": lamp_start,
            "lamp_end": lamp_end,
            "lamp_power_par": lamp_power_par,
            "n_lamp_only_readings": n_lamp_only,
        })

    return pd.DataFrame(records)


def subtract_lamp_from_sensor(
    plant_level_df: pd.DataFrame,
    lamp_profile: pd.DataFrame,
) -> pd.DataFrame:
    """Subtract lamp contribution from plant-level PAR readings.

    For each reading, looks up that day's lamp profile. If the reading falls during
    lamp-on hours and lamp_power is known, subtracts the lamp power (clamped to 0).

    Args:
        plant_level_df: PAR readings from plant-level sensor (s2100-02-par).
            Columns: device, sensor, time, value
        lamp_profile: Output from derive_daily_lamp_profile().

    Subtracts only on the hours the profile actually saw lit. An earlier version
    read a ``lamp_start``-to-``lamp_end`` range, which for red's real December
    schedule (23:00-06:00) spans min 0 to max 23 — the whole day — and stripped
    the lamp power out of every daylight hour too, collapsing attenuation.

    Returns:
        DataFrame with same structure, corrected values.
    """
    df = plant_level_df.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["date"] = df["time"].dt.date
    df["hour"] = df["time"].dt.hour

    # Build lookup: date → (set of lamp hours, measured power)
    lamp_lookup: dict = {}
    for _, row in lamp_profile.iterrows():
        if row["lamp_power_par"] is not None and pd.notna(row["lamp_power_par"]):
            lamp_lookup[row["date"]] = (
                _profile_hours(row),
                row["lamp_power_par"],
            )

    def correct_value(row):
        profile = lamp_lookup.get(row["date"])
        if profile is None:
            # No profile for this day; without a schedule, don't subtract (safer).
            return row["value"]

        lamp_hours, lamp_power = profile
        if row["hour"] in lamp_hours:
            return max(0.0, row["value"] - lamp_power)
        return row["value"]

    df["value"] = df.apply(correct_value, axis=1)
    df = df.drop(columns=["date", "hour"])

    return df


def _profile_hours(row) -> frozenset[int]:
    """The lit hours of one profile row, from the set or an older start/end pair."""
    hours = row.get("lamp_hours") if hasattr(row, "get") else None
    if hours is not None and not isinstance(hours, float):
        return frozenset(hours)
    start, end = row.get("lamp_start"), row.get("lamp_end")
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return frozenset()
    start, end = int(start), int(end)
    if start <= end:
        return frozenset(range(start, end + 1))
    return frozenset(range(start, 24)) | frozenset(range(0, end + 1))


def compute_attenuation(
    above_lamp_df: pd.DataFrame, plant_level_df: pd.DataFrame
) -> tuple[float, int]:
    """Above-lamp → plant-level ratio, from lamp-corrected daily sums.

    The share of natural light that survives the trip from the roof sensor down
    past the lamps and fixtures to the canopy — structure, not lighting. Stays a
    **daily** ratio because its consumer scales a daily sum; hourly the same
    quantity swings 0.49-0.78 with sun azimuth, daily it settles to an 8% spread.

    Removing the lamp is the whole difficulty, and it takes three steps because
    the lamp and the ratio each need the other:

    1. **Bootstrap** with the slope of canopy on above-lamp, fitted with a free
       intercept. A constant lamp offset lands in the intercept rather than the
       slope, so unlike a raw ratio this cannot be dragged above 1 by lighting.
       It is biased low in winter (0.40 against a true ~0.58) and that is fine —
       it is only used to find *which* hours were lit, a decision with a wide
       margin either side.
    2. **Detect** the schedule with it, daylight hours included.
    3. **Subtract** the measured lamp level from those hours and take the daily
       ratio of what is left.

    Converges in one pass on real data: December 2025 gives 0.580 at step 3 and
    0.580 again if fed back through.

    Why not the obvious filters:

    - *Overcast hours only* looks ideal in summer (0.672, six times tighter) and
      is the worst option in winter: overcast means a small above-lamp reading
      against an unchanged lamp, so the ratio reaches **1.762**.
    - *Lamp-free hours only* has nothing to work with — red's winter lamps run
      23:00-15:00, leaving no lamp-free daylight hour at all.

    Returns ``(median_ratio, n_days_used)``; ``(1.0, 0)`` when nothing qualifies
    or the window cannot identify it. Callers should read ``n_days_used == 0`` as
    "unknown", not as "attenuation is 1.0".
    """
    min_indoor_par = _min_indoor_par()
    above = _hourly(above_lamp_df)
    canopy = _hourly(plant_level_df)
    joined = pd.concat([above.rename("above"), canopy.rename("canopy")], axis=1).dropna()
    if joined.empty:
        return 1.0, 0

    _, power_par = _schedule_over(joined)  # the level, from the dark hours
    lit = _lit_mask(joined)
    clean = (joined["canopy"] - np.where(lit, power_par or 0.0, 0.0)).clip(lower=0.0)

    daily = pd.DataFrame(
        {"above_sum": joined["above"], "plant_sum": clean}
    ).groupby(joined.index.date).sum()
    daily = daily[(daily["above_sum"] > min_indoor_par) & (daily["plant_sum"] > 0)]
    if daily.empty:
        return 1.0, 0

    ratio = float((daily["plant_sum"] / daily["above_sum"]).median())

    # The canopy cannot receive more light than the roof sensor above it, so a
    # ratio at or above 1 is not a high attenuation — it is a window whose lamp
    # contribution was not removed. Refuse it rather than hand back a number a
    # caller would go on to multiply by.
    if not 0.0 < ratio < 1.0:
        return 1.0, 0

    return ratio, len(daily)
