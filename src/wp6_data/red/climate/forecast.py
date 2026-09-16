"""Assemble a per-height climate forecast for one wire.

The chain predicts the greenhouse-level reference at a set of **fitted
horizons**, and link 3 maps that reference onto each height at the same instant.
So a forecast is a handful of vertical *profiles* — the crop as it will stand at
+1 h, +6 h, +24 h — rather than a continuous curve.

That is not a presentational preference. The chain was fitted and scored at six
horizons; a smooth line between them would draw 42 hours nobody validated. What
is drawn instead is what was measured, carrying the uncertainty that was
measured with it:

    uncertainty(height, horizon) ≈ √( link2_rmse(horizon)² + link3_rmse(height)² )

Quadrature assumes the two errors are independent, which is an approximation —
link 3 was scored against a *measured* reference, so its error genuinely excludes
link 2's, but nothing guarantees the two are uncorrelated. It is stated on the
page as approximate rather than presented as a confidence interval.

A horizon where link 2 does not beat persistence is carried through and flagged,
not hidden: "no better than the value now" is a useful thing for a grower to
know about the next 24 hours.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from wp6_data.red.climate import data as climate_data
from wp6_data.red.climate.config import ClimateModelConfig
from wp6_data.red.climate.downscale import WireDownscaler
from wp6_data.red.climate.features import hourly_frame, resample_hourly
from wp6_data.red.climate.model import PREDICTED_OUTDOOR_PREFIX, IndoorClimateModel
from wp6_data.red.climate.training import TrainedChain
from wp6_data.red.lamp import LampModel
from wp6_data.shared.aggregation import resample_to
from wp6_data.shared.weather import OpenMeteoClient

# Measured history pulled in to fill the model's lags. The longest lag is 24 h;
# three days leaves room for the gaps red's sensors actually have.
HISTORY_DAYS = 3

# Forecast days requested from OpenMeteo. The longest horizon is 48 h; the extra
# day covers the gap between the last reading and "now".
FORECAST_DAYS = 3

# The measured history is drawn at close to the sensors' own cadence rather
# than the model's hourly grid: the model resamples to hours because that is
# what it trains on, but the chart is showing what actually happened and there
# is no reason to throw detail away.
HISTORY_RESOLUTION = "10min"

# Humidity at a height needs the temperature at that height, so temp is always
# predicted first even when the page is showing humidity.
TEMP = "temp"
HUMIDITY = "hum"
PAR = "par"

# Display names, deliberately red's own vocabulary: CONTEXT.md defines **PAR**,
# so the page says PAR rather than inventing "Light" beside it.
MEASUREMENT_LABELS = {
    "temp": "Temperature",
    "hum": "Humidity",
    "co2": "CO₂",
    "par": "PAR",
}
UNITS = {"temp": "°C", "hum": "%RH", "co2": "ppm", "par": "µmol/m²/s"}


def history_offsets(horizons: list[int]) -> list[int]:
    """Past offsets mirroring the fitted horizons, furthest back first.

    Mirroring rather than choosing independently keeps the axis symmetric about
    "now", so the eye reads the same distance either side of the hinge — and it
    stays symmetric if the configured horizons change.
    """
    return [-h for h in sorted(horizons, reverse=True)]

# Physically impossible readings a linear model can still produce. A ridge fit
# on PAR will predict below zero on a dark hour, and "-1.8 µmol/m²/s of light"
# is not an honest uncertainty — it is a value outside the quantity's domain.
# Clamped at the point the number becomes a physical reading, not inside the
# model, so the fit's own residuals stay untouched.
PHYSICAL_FLOOR: dict[str, float] = {"par": 0.0, "co2": 0.0, "hum": 0.0}
PHYSICAL_CEILING: dict[str, float] = {"hum": 100.0}


@dataclass(frozen=True)
class HeightPoint:
    """One growth section's predicted (or measured) value."""

    height: int
    label: str
    value: float
    uncertainty: float | None = None


@dataclass(frozen=True)
class ProfileSnapshot:
    """The vertical profile at one moment."""

    at: datetime
    horizon_hours: int
    points: list[HeightPoint]
    measured: bool = False
    skill_vs_persistence: float | None = None

    @property
    def label(self) -> str:
        return _offset_label(self.horizon_hours)

    def clock(self, tz) -> str:
        """When this profile is, in the dashboard's display timezone.

        What a grower acts on is "Thursday 18:00", not "+12 h" — but the axis is
        evenly spaced rather than a real time axis, so both are shown: the clock
        time to act on, the offset to explain the spacing.
        """
        if self.at is None:
            return self.label
        return self.at.astimezone(tz).strftime("%a %H:%M")

    @property
    def is_now(self) -> bool:
        """The last measured moment — the hinge the forecast continues from."""
        return self.measured and self.horizon_hours == 0

    @property
    def beats_persistence(self) -> bool | None:
        if self.measured or self.skill_vs_persistence is None:
            return None
        return self.skill_vs_persistence > 0


@dataclass(frozen=True)
class OutdoorPoint:
    """The outdoor reading at one moment on the timeline."""

    label: str
    value: float
    measured: bool


@dataclass(frozen=True)
class ForecastView:
    """Everything the forecast page draws."""

    wire: str
    measurement: str
    unit: str
    issued_at: datetime
    reference_key: str
    snapshots: list[ProfileSnapshot] = field(default_factory=list)
    outdoor: list[OutdoorPoint] = field(default_factory=list)
    # Measured history at something close to the sensors' own cadence, keyed by
    # height, for drawing. The snapshots above stay coarse because the profile
    # chart and the table want one value per horizon, not three hundred.
    measured_trace: dict[int, list[tuple[datetime, float]]] = field(default_factory=dict)
    outdoor_trace: list[tuple[datetime, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def predicted(self) -> list[ProfileSnapshot]:
        return [s for s in self.snapshots if not s.measured]

    @property
    def history(self) -> list[ProfileSnapshot]:
        """Measured profiles before ``now``, oldest first."""
        return sorted(
            (s for s in self.snapshots if s.measured and s.horizon_hours < 0),
            key=lambda s: s.horizon_hours,
        )

    @property
    def now(self) -> ProfileSnapshot | None:
        return next((s for s in self.snapshots if s.is_now), None)

    @property
    def has_content(self) -> bool:
        return any(snapshot.points for snapshot in self.snapshots)

    @property
    def quantity(self) -> str:
        """What is being shown, with its unit."""
        return quantity(self.measurement)

    @property
    def heights(self) -> list[int]:
        """Sections with at least one value, top of the crop first."""
        return sorted({p.height for s in self.snapshots for p in s.points})

    def label_for(self, height: int) -> str:
        for snapshot in self.snapshots:
            for point in snapshot.points:
                if point.height == height:
                    return point.label
        return f"H{height}"


def envelope(view: ForecastView) -> list[tuple[str, float, float]]:
    """Per snapshot, the coolest and warmest section — the vertical gradient.

    The band's width *is* the gradient, which is why it is computed from the
    sections present at that snapshot rather than from a fixed H1/H5 pair: a
    wire that has lost a height must not read as a narrower crop.
    """
    rows = []
    for snapshot in view.snapshots:
        if not snapshot.points:
            continue
        values = [point.value for point in snapshot.points]
        rows.append((snapshot.label, min(values), max(values)))
    return rows


def series_for_height(
    view: ForecastView, height: int
) -> list[tuple[str, float, float | None]]:
    """One section's value across the horizons, with its uncertainty."""
    rows = []
    for snapshot in view.snapshots:
        point = next((p for p in snapshot.points if p.height == height), None)
        if point is not None:
            rows.append((snapshot.label, point.value, point.uncertainty))
    return rows


def clamp_physical(measurement: str, value: float) -> float:
    """Hold a predicted value inside the quantity's physical range."""
    floor = PHYSICAL_FLOOR.get(measurement)
    ceiling = PHYSICAL_CEILING.get(measurement)
    if floor is not None:
        value = max(floor, value)
    if ceiling is not None:
        value = min(ceiling, value)
    return value


def _combined_uncertainty(link2_rmse: float | None, link3_rmse: float | None) -> float | None:
    """Quadrature of the two links' held-out errors; ``None`` if either is absent."""
    if link2_rmse is None or link3_rmse is None:
        return None
    return round(float(np.hypot(link2_rmse, link3_rmse)), 3)


async def build_forecast(
    config: ClimateModelConfig,
    chain: TrainedChain,
    model: IndoorClimateModel,
    downscaler: WireDownscaler,
    weather_client: OpenMeteoClient,
    *,
    wire: str,
    measurement: str,
    sections: dict[int, str],
    now: datetime | None = None,
) -> ForecastView:
    """Predict the vertical profile at each fitted horizon for one wire."""
    now = now or datetime.now(UTC)
    unit = _unit_for(measurement)
    notes: list[str] = []

    notes.extend(_known_caveats(measurement, now, chain.lamp))

    heights = config.wire_availability[wire].heights(measurement)
    if not heights:
        return ForecastView(
            wire, measurement, unit, now, chain.chosen_reference,
            notes=[f"{wire} does not report {measurement} at any height."],
        )

    frame, reference_now = await _assemble_frame(
        config, chain, model, weather_client, now
    )
    if frame is None or reference_now is None:
        return ForecastView(
            wire, measurement, unit, now, chain.chosen_reference,
            notes=["Not enough recent greenhouse readings to seed a forecast."],
        )

    snapshots = await _measured_snapshots(
        wire, measurement, heights, sections, reference_now,
        history_offsets(config.horizons_hours),
    )
    for horizon in sorted(config.horizons_hours):
        snapshot = _predict_snapshot(
            config, chain, model, downscaler, frame,
            wire=wire, measurement=measurement, heights=heights,
            sections=sections, at=reference_now, horizon=horizon,
            lamp=chain.lamp,
        )
        if snapshot is not None:
            snapshots.append(snapshot)

    offsets = history_offsets(config.horizons_hours)
    hours_back = abs(min(offsets)) if offsets else 0
    outdoor = await _outdoor_series(
        config, frame, measurement, reference_now, offsets, config.horizons_hours,
    )
    measured_trace = await _measured_trace(
        wire, measurement, heights, reference_now, hours_back
    )
    outdoor_trace = await _outdoor_trace(
        config, measurement, reference_now, hours_back
    )

    if not any(not s.measured for s in snapshots):
        notes.append(
            "The chain has no model for this measurement at the fitted horizons."
        )
    return ForecastView(
        wire, measurement, unit, now, chain.chosen_reference,
        snapshots=snapshots, outdoor=outdoor,
        measured_trace=measured_trace, outdoor_trace=outdoor_trace,
        notes=notes,
    )


def _known_caveats(
    measurement: str, now: datetime, lamp: LampModel | None = None
) -> list[str]:
    """What a reader must know before acting on the number.

    For light that is the lamp assumption: link 2 predicts only the natural
    part, and the lamp contribution is carried forward from the recent observed
    schedule. Weather cannot tell you the grower changed the lamp plan, so the
    page says where the lamp figure came from rather than presenting the total
    as if it were all forecast.
    """
    if measurement != PAR:
        return []
    if lamp is None or not lamp.is_lighting:
        return [
            "PAR is the natural light weather predicts, scaled to canopy level. "
            "The lamps were not seen running recently, so nothing is added for "
            "them — if they are switched on, this will read low."
        ]
    hours = ", ".join(
        f"{hour:02d}:00" for hour in sorted(lamp.hours_on)
    ) if len(lamp.hours_on) <= 6 else f"{len(lamp.hours_on)} hours a day"
    return [
        f"PAR is natural light predicted from weather, scaled to canopy level, "
        f"plus an observed lamp contribution of {lamp.power_par:g} µmol/m²/s "
        f"during {hours}. That schedule is carried forward from the last "
        f"{lamp.observed_days} days — a change to the lamp plan is not "
        f"something weather can predict."
    ]


def _unit_for(measurement: str) -> str:
    return UNITS.get(measurement, "")


def quantity(measurement: str) -> str:
    """Display name and unit, e.g. ``"Temperature (°C)"``.

    Axis titles, card headings and colour-bar labels all go through here, so a
    reader never has to know that ``temp`` is degrees and ``par`` is
    µmol/m²/s — and the three can never disagree.
    """
    name = MEASUREMENT_LABELS.get(measurement, measurement)
    unit = UNITS.get(measurement, "")
    return f"{name} ({unit})" if unit else name


async def _assemble_frame(
    config: ClimateModelConfig,
    chain: TrainedChain,
    model: IndoorClimateModel,
    weather_client: OpenMeteoClient,
    now: datetime,
) -> tuple[pd.DataFrame | None, pd.Timestamp | None]:
    """Recent indoor readings joined to link-1 output reaching into the future.

    The exogenous columns must extend past the longest horizon, so the weather
    comes from the *forecast* endpoint with ``past_days`` covering the history
    the lags need — the same assembly blue's GDD uses to bridge the archive's lag.
    """
    start = now - timedelta(days=HISTORY_DAYS)

    # Exactly the series link 2 was fitted on — taken from the model, not
    # rebuilt from config, so a target added to training cannot go missing here.
    indoor = await climate_data.sensor_frames(model.link2_sources, start, now)
    if not indoor:
        return None, None

    weather = await weather_client.get_hourly(
        _weather_variables(),
        forecast_days=FORECAST_DAYS,
        past_days=HISTORY_DAYS + 1,
    )
    predicted_outdoor = model.predict_outdoor(weather)
    if predicted_outdoor.empty:
        return None, None

    frame = hourly_frame(indoor).join(predicted_outdoor, how="outer")
    # "Now" is the last hour every fitted input reported: a lag built from a
    # column that has gone quiet would be missing, not stale.
    measured = frame[list(indoor)].dropna(how="any")
    if measured.empty:
        return None, None
    return frame, measured.index.max()


def _weather_variables() -> list[str]:
    from wp6_data.red.climate.model import WEATHER_VARIABLES

    return list(WEATHER_VARIABLES)


async def _measured_trace(
    wire: str,
    measurement: str,
    heights: list[int],
    at: pd.Timestamp,
    hours_back: int,
) -> dict[int, list[tuple[datetime, float]]]:
    """Measured values per height over the history window, densely.

    Resampled to :data:`HISTORY_RESOLUTION` rather than left raw: the relay
    writes in bursts and ``received_at`` is not unique per device, so raw points
    would draw a ragged line with vertical jumps where a burst landed.
    """
    frames = await climate_data.wire_frames(
        wire, measurement, heights,
        (at - pd.Timedelta(hours=hours_back)).to_pydatetime(),
        (at + pd.Timedelta(hours=1)).to_pydatetime(),
    )
    trace: dict[int, list[tuple[datetime, float]]] = {}
    for key, frame in frames.items():
        dense = resample_to(frame, HISTORY_RESOLUTION)
        if not dense.empty:
            trace[int(key.lstrip("h"))] = [
                (row.time.to_pydatetime(), round(float(row.value), 2))
                for row in dense.itertuples(index=False)
            ]
    return trace


async def _outdoor_trace(
    config: ClimateModelConfig,
    measurement: str,
    at: pd.Timestamp,
    hours_back: int,
) -> list[tuple[datetime, float]]:
    """The outdoor station over the same window, at the same resolution."""
    if measurement not in config.outdoor.sensors:
        return []
    raw = await climate_data.sensor_series(
        config.outdoor.device, measurement,
        (at - pd.Timedelta(hours=hours_back)).to_pydatetime(),
        (at + pd.Timedelta(hours=1)).to_pydatetime(),
    )
    dense = resample_to(raw, HISTORY_RESOLUTION)
    return [
        (row.time.to_pydatetime(), round(float(row.value), 2))
        for row in dense.itertuples(index=False)
    ]


async def _outdoor_series(
    config: ClimateModelConfig,
    frame: pd.DataFrame,
    measurement: str,
    at: pd.Timestamp,
    offsets: list[int],
    horizons: list[int],
) -> list[OutdoorPoint]:
    """The outdoor reading across the same timeline as the crop.

    Measured from the site's own station for the past, and link 1's prediction
    for the future — the same measured/predicted split the crop lines use, so
    the two are read on equal terms.

    Only measurements the outdoor station actually reports in the same unit get
    a line. Lux is not PAR and CO₂ is not in the configured sensor set, so light
    and CO₂ have no outdoor context rather than a converted approximation.
    """
    if measurement not in config.outdoor.sensors:
        return []

    furthest = min(offsets) if offsets else 0
    measured_raw = await climate_data.sensor_series(
        config.outdoor.device, measurement,
        (at + pd.Timedelta(hours=furthest - 1)).to_pydatetime(),
        (at + pd.Timedelta(hours=1)).to_pydatetime(),
    )
    points: list[OutdoorPoint] = []
    if not measured_raw.empty:
        hourly = resample_hourly(measured_raw).set_index("time")["value"]
        for offset in [*offsets, 0]:
            moment = (at + pd.Timedelta(hours=offset)).floor("h")
            if moment in hourly.index:
                points.append(
                    OutdoorPoint(
                        label=_offset_label(offset),
                        value=round(float(hourly.loc[moment]), 2),
                        measured=True,
                    )
                )

    column = f"{PREDICTED_OUTDOOR_PREFIX}{measurement}"
    if column in frame:
        for horizon in sorted(horizons):
            moment = at + pd.Timedelta(hours=horizon)
            if moment in frame.index and pd.notna(frame.loc[moment, column]):
                points.append(
                    OutdoorPoint(
                        label=_offset_label(horizon),
                        value=round(float(frame.loc[moment, column]), 2),
                        measured=False,
                    )
                )
    return points


def _offset_label(offset: int) -> str:
    """The x-axis key for an offset — must match ``ProfileSnapshot.label``."""
    if offset == 0:
        return "now"
    return f"{'+' if offset > 0 else '−'}{abs(offset)} h"


async def _measured_snapshots(
    wire: str,
    measurement: str,
    heights: list[int],
    sections: dict[int, str],
    at: pd.Timestamp,
    offsets: list[int],
) -> list[ProfileSnapshot]:
    """Measured profiles at ``now`` and at each past offset.

    One fetch covers the whole window. Each offset takes the reading from that
    hour if the sensor reported it — an hour with no reading yields no point for
    that section rather than the nearest one, so a gap in the record shows as a
    gap rather than as a flat stretch.
    """
    furthest = min(offsets) if offsets else 0
    frames = await climate_data.wire_frames(
        wire, measurement, heights,
        (at + pd.Timedelta(hours=furthest - 1)).to_pydatetime(),
        (at + pd.Timedelta(hours=1)).to_pydatetime(),
    )
    if not frames:
        return []

    hourly = {
        int(key.lstrip("h")): resample_hourly(df).set_index("time")["value"]
        for key, df in frames.items()
    }

    snapshots = []
    for offset in [*offsets, 0]:
        moment = (at + pd.Timedelta(hours=offset)).floor("h")
        points = [
            HeightPoint(
                height=height,
                label=sections.get(height, f"H{height}"),
                value=round(float(series.loc[moment]), 2),
            )
            for height, series in sorted(hourly.items())
            if moment in series.index
        ]
        if points:
            snapshots.append(
                ProfileSnapshot(
                    at=moment.to_pydatetime(), horizon_hours=offset,
                    points=points, measured=True,
                )
            )
    return snapshots


def _predict_snapshot(
    config: ClimateModelConfig,
    chain: TrainedChain,
    model: IndoorClimateModel,
    downscaler: WireDownscaler,
    frame: pd.DataFrame,
    *,
    wire: str,
    measurement: str,
    heights: list[int],
    sections: dict[int, str],
    at: pd.Timestamp,
    horizon: int,
    lamp: LampModel | None = None,
) -> ProfileSnapshot | None:
    """One horizon: reference forecast, then each height's deviation on top."""
    reference_value = model.predict_target(frame, measurement, horizon, at=at)
    if reference_value is None:
        return None
    target_time = at + pd.Timedelta(hours=horizon)

    # Light arrives from link 2 as *natural above-lamp* PAR — the part weather
    # explains. The canopy reference link 3 needs is that, attenuated down past
    # the lamps, plus whatever the lamps are contributing at that hour.
    if measurement == PAR and lamp is not None:
        reference_value = lamp.canopy_par(reference_value, target_time)
    reference_value = clamp_physical(measurement, reference_value)

    # Humidity needs the temperature at the same height, so the temperature
    # profile is predicted first whether or not it is the one being shown.
    reference_temp = (
        model.predict_target(frame, TEMP, horizon, at=at)
        if measurement == HUMIDITY else None
    )
    if measurement == HUMIDITY and reference_temp is None:
        return None

    index = pd.DatetimeIndex([target_time])
    link2 = chain.stats.fit_for(measurement, horizon) if chain.stats else None

    points: list[HeightPoint] = []
    for height in sorted(heights):
        height_temp = None
        if measurement == HUMIDITY:
            height_temp = _height_series(
                downscaler, wire, TEMP, height, reference_temp, index
            )
            if height_temp is None:
                continue

        try:
            predicted = downscaler.predict(
                wire, measurement, height,
                pd.Series([reference_value], index=index),
                reference_temp=(
                    pd.Series([reference_temp], index=index)
                    if reference_temp is not None else None
                ),
                height_temp=height_temp,
            )
        except KeyError:
            continue

        link3 = next(
            (f.stats.holdout_rmse for f in (downscaler.stats.fits if downscaler.stats else [])
             if f.wire == wire and f.measurement == measurement and f.height == height),
            None,
        )
        points.append(
            HeightPoint(
                height=height,
                label=sections.get(height, f"H{height}"),
                value=round(
                    clamp_physical(measurement, float(predicted.iloc[0])), 2
                ),
                uncertainty=_combined_uncertainty(
                    link2.stats.holdout_rmse if link2 else None, link3
                ),
            )
        )

    if not points:
        return None
    return ProfileSnapshot(
        at=target_time.to_pydatetime(),
        horizon_hours=horizon,
        points=points,
        skill_vs_persistence=(
            link2.stats.skill.get("persistence") if link2 else None
        ),
    )


def _height_series(
    downscaler: WireDownscaler,
    wire: str,
    measurement: str,
    height: int,
    reference_value: float | None,
    index: pd.DatetimeIndex,
) -> pd.Series | None:
    """This height's predicted temperature, needed to convert humidity back."""
    if reference_value is None:
        return None
    try:
        return downscaler.predict(
            wire, measurement, height, pd.Series([reference_value], index=index)
        )
    except KeyError:
        return None
