"""Link 3: greenhouse-level reference → per-height wire values.

This is the only link that needs wire data, and the wires have roughly nine
summer weeks of it (``docs/red/wire-data-coverage.md``). So it is deliberately
the smallest model in the chain: it learns how each height *differs* from the
greenhouse-level reference, not how weather makes a greenhouse.

**Deviation, not value.** Fitting ``height − reference`` rather than ``height``
means the profile shape is the thing being learnt, errors in links 1-2 do not
distort it, and a handful of parameters per height suffice. The deviation is
taken in whatever form is physically additive for the measurement:

- ``temp``, ``co2`` — a difference.
- ``par`` — a **ratio**. Attenuation down a canopy is multiplicative, the same
  reasoning behind the DLI model's constant ``attenuation_factor``.
- ``hum`` — a difference in **absolute** humidity, converted back to RH with the
  predicted temperature at that height. See ``humidity.py`` for why RH itself is
  not comparable between heights.

**The baseline that matters is ``reference``** — assume the height simply equals
the greenhouse-level sensor. If modelling the gradient does not beat ignoring
the gradient, this link has earned nothing, and the status page says so rather
than quietly reporting a healthy R².

Note the direction: red's ``CONTEXT.md`` records that Height DLI never feeds the
DLI model. This runs the other way — greenhouse PAR predicts wire PAR — and must
never feed back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from wp6_data.red.climate.config import ClimateModelConfig
from wp6_data.red.climate.features import hourly_frame, seasonal_columns
from wp6_data.red.climate.humidity import absolute_humidity, relative_humidity
from wp6_data.red.fitting import (
    GradientScore,
    StageStats,
    fit_ridge,
    gradient_error,
    out_of_fold_predictions,
    reference_baseline,
    rmse,
    score_holdout,
)

# How a measurement's deviation from the reference is expressed.
DIFFERENCE = "difference"
RATIO = "ratio"
ABSOLUTE_HUMIDITY = "absolute_humidity"

DEVIATION_MODE: dict[str, str] = {
    "temp": DIFFERENCE,
    "co2": DIFFERENCE,
    "par": RATIO,
    "hum": ABSOLUTE_HUMIDITY,
}

# Fewer rows than this and the height is not reported rather than reported with
# a score nobody should read.
MIN_HEIGHT_ROWS = 100

# Ratios beyond this are instrument or occlusion artefacts, not attenuation.
MAX_PAR_RATIO = 5.0

# Whether a day-of-year term helps is decided per fit, by out-of-fold score,
# rather than configured. See MODEL_PAPER.md §5.4: on the first real training
# run it helped PAR at every height (RMSE 136 -> 113) and hurt humidity, so a
# single global switch would have been wrong either way it was set.
SEASONAL_OPTIONS: tuple[bool, ...] = (False, True)


@dataclass
class HeightFit:
    """One (wire, measurement, height) deviation model and its verdict."""

    wire: str
    measurement: str
    height: int
    mode: str
    stats: StageStats
    seasonal: bool = False

    @property
    def beats_reference(self) -> bool:
        """Whether modelling the gradient beat ignoring it. The whole question."""
        return self.stats.skill.get("reference", 0.0) > 0.0


@dataclass
class DownscaleStats:
    """What a Link 3 training run produced, per wire and per measurement."""

    trained_at: datetime
    reference_key: str
    fits: list[HeightFit] = field(default_factory=list)
    gradients: dict[tuple[str, str], GradientScore] = field(default_factory=dict)
    span: tuple[object, object] = (None, None)
    days_covered: int = 0

    @property
    def seasonal_chosen(self) -> dict[str, tuple[int, int]]:
        """Per measurement, how many fits kept the day-of-year term.

        Reported rather than configured: the chain re-decides on every retrain,
        so a term that only starts helping once the wires have seen a winter
        switches itself on without anyone remembering to flip a flag.
        """
        counts: dict[str, tuple[int, int]] = {}
        for fit in self.fits:
            kept, total = counts.get(fit.measurement, (0, 0))
            counts[fit.measurement] = (kept + int(fit.seasonal), total + 1)
        return counts

    @property
    def wires(self) -> list[str]:
        return sorted({fit.wire for fit in self.fits})

    def for_wire(self, wire: str, measurement: str) -> list[HeightFit]:
        return sorted(
            (f for f in self.fits if f.wire == wire and f.measurement == measurement),
            key=lambda f: f.height,
        )

    @property
    def earned_its_place(self) -> list[HeightFit]:
        return [fit for fit in self.fits if fit.beats_reference]


def deviation(
    values: np.ndarray, reference: np.ndarray, mode: str
) -> np.ndarray:
    """Express ``values`` as a deviation from ``reference`` in ``mode``."""
    if mode == RATIO:
        return values / reference
    return values - reference


def reconstruct(
    deviations: np.ndarray, reference: np.ndarray, mode: str
) -> np.ndarray:
    """Inverse of :func:`deviation` — put a predicted deviation back on the reference."""
    if mode == RATIO:
        return deviations * reference
    return deviations + reference


class WireDownscaler:
    """Per-height deviation models for one greenhouse-level reference."""

    def __init__(self, config: ClimateModelConfig, reference_key: str):
        self.config = config
        self.reference_key = reference_key
        self.models: dict[tuple[str, str, int], tuple[object, object, list[str], str]] = {}
        self.stats: DownscaleStats | None = None

    def is_trained(self) -> bool:
        return bool(self.models)

    def _features(
        self, reference: pd.Series, *, seasonal: bool
    ) -> tuple[np.ndarray, list[str]]:
        """Reference level, time of day, and their interaction.

        The interaction is what lets the gradient itself vary through the day —
        a canopy that is two degrees cooler at dawn and five at midday. Without
        it the model could only learn a single constant offset per height, which
        is exactly the baseline it has to beat.
        """
        encodings = seasonal_columns(
            pd.DatetimeIndex(reference.index), with_day_of_year=seasonal
        )
        built = {"reference": reference.to_numpy(dtype=float)}
        for column in encodings.columns:
            built[column] = encodings[column].to_numpy(dtype=float)
            built[f"reference_x_{column}"] = built["reference"] * built[column]
        return np.column_stack(list(built.values())), list(built)

    def train(
        self,
        reference_series: dict[str, pd.DataFrame],
        wire_series: dict[tuple[str, str], dict[str, pd.DataFrame]],
    ) -> DownscaleStats:
        """Fit every (wire, measurement, height) the config says is available.

        ``reference_series`` maps a measurement to the greenhouse-level series it
        is compared against; ``wire_series`` maps ``(wire, measurement)`` to that
        wire's per-height frames, as ``data.wire_frames`` returns them.
        """
        fits: list[HeightFit] = []
        gradients: dict[tuple[str, str], GradientScore] = {}
        spans: list[pd.Timestamp] = []

        for (wire, measurement), heights in sorted(wire_series.items()):
            if measurement not in reference_series or not heights:
                continue
            mode = DEVIATION_MODE.get(measurement, DIFFERENCE)
            # Humidity needs the temperature at the *same height*, not the
            # reference's: absolute humidity is a property of that air.
            height_temps = (
                wire_series.get((wire, "temp"), {}) if measurement == "hum" else {}
            )
            frame = self._aligned(
                reference_series, measurement, heights, height_temps
            )
            if frame.empty:
                continue
            # Span of the *wire's* own readings, not of the joined frame: the
            # reference carries a year of history the wire does not, and taking
            # the join's span would credit link 3 with coverage it never had.
            reported = frame[list(heights)].dropna(how="all")
            if reported.empty:
                continue
            spans.extend([reported.index.min(), reported.index.max()])

            predicted_wide: dict[int, pd.Series] = {}
            actual_wide: dict[int, pd.Series] = {}

            for key in sorted(heights):
                height = int(key.lstrip("h"))
                fit = self._train_height(
                    wire, measurement, height, mode, frame, key,
                    predicted_wide, actual_wide,
                )
                if fit is not None:
                    fits.append(fit)

            if len(predicted_wide) >= 2:
                gradients[(wire, measurement)] = gradient_error(
                    pd.DataFrame(predicted_wide), pd.DataFrame(actual_wide),
                    base_height=min(predicted_wide),
                )

        span = (
            (min(spans).date(), max(spans).date()) if spans else (None, None)
        )
        self.stats = DownscaleStats(
            trained_at=datetime.now(UTC),
            reference_key=self.reference_key,
            fits=fits,
            gradients=gradients,
            span=span,
            days_covered=_days_covered(spans),
        )
        return self.stats

    def _aligned(
        self,
        reference_series: dict[str, pd.DataFrame],
        measurement: str,
        heights: dict[str, pd.DataFrame],
        height_temps: dict[str, pd.DataFrame] | None = None,
    ) -> pd.DataFrame:
        """Hourly frame of the reference plus every height, on one index.

        For humidity each height's own temperature rides along, and the
        reference's too — absolute humidity is a property of the air at that
        height, so it cannot be computed from the reference temperature.
        """
        series = {"reference": reference_series[measurement], **heights}
        if measurement == "hum":
            if "temp" in reference_series:
                series["reference_temp"] = reference_series["temp"]
            for key, frame in (height_temps or {}).items():
                series[f"{key}_temp"] = frame
        frame = hourly_frame(series)
        if frame.empty:
            return frame
        return self.config.drop_excluded(
            frame.reset_index(), time_col="time"
        ).set_index("time")

    def _train_height(
        self, wire: str, measurement: str, height: int, mode: str,
        frame: pd.DataFrame, key: str,
        predicted_wide: dict[int, pd.Series], actual_wide: dict[int, pd.Series],
    ) -> HeightFit | None:
        needed = ["reference", key]
        temp_column = f"{key}_temp" if f"{key}_temp" in frame else "reference_temp"
        if mode == ABSOLUTE_HUMIDITY:
            needed.append(temp_column)
            if "reference_temp" in frame:
                needed.append("reference_temp")
        usable = frame[[c for c in needed if c in frame]].dropna()
        if mode == ABSOLUTE_HUMIDITY and temp_column not in usable:
            return None
        if mode == RATIO:
            usable = usable[usable["reference"] > self.config.par_floor]
        if len(usable) < MIN_HEIGHT_ROWS:
            return None

        reference = usable["reference"]
        values = usable[key].to_numpy(dtype=float)
        if mode == ABSOLUTE_HUMIDITY:
            # Compare moisture content, not RH: the same air reads a different
            # RH at a different temperature.
            # Reference moisture from the reference's own temperature; the
            # height's from the height's. Mixing them would fold a temperature
            # difference into what is supposed to be a moisture difference.
            height_temp = usable[temp_column].to_numpy(dtype=float)
            reference_temp = usable.get(
                "reference_temp", usable[temp_column]
            ).to_numpy(dtype=float)
            reference_values = absolute_humidity(reference_temp, reference.to_numpy())
            target_values = absolute_humidity(height_temp, values)
        else:
            reference_values = reference.to_numpy(dtype=float)
            target_values = values

        deviations = deviation(target_values, reference_values, mode)
        height_temp = (
            usable[temp_column].to_numpy(dtype=float)
            if mode == ABSOLUTE_HUMIDITY else None
        )
        if mode == RATIO:
            keep = np.isfinite(deviations) & (np.abs(deviations) < MAX_PAR_RATIO)
            if keep.sum() < MIN_HEIGHT_ROWS:
                return None
            usable, reference = usable[keep], reference[keep]
            deviations, reference_values = deviations[keep], reference_values[keep]
            values = values[keep]

        days = np.array([ts.date() for ts in usable.index])
        baseline_reference = reference.to_numpy(dtype=float)

        # Fit with and without a day-of-year term and keep whichever predicts
        # held-out blocks better *in the measurement's own units*. Which one
        # wins is not the same for every measurement — see MODEL_PAPER §5.4 —
        # so a single configured switch would have been wrong either way.
        best: tuple[float, dict] | None = None
        for seasonal in SEASONAL_OPTIONS:
            X, feature_names = self._features(reference, seasonal=seasonal)
            model, scaler, stats = fit_ridge(X, deviations, feature_names, days=days)
            oof, mask = out_of_fold_predictions(X, deviations, feature_names, days)
            if not mask.any():
                candidate_error = float("inf")
                rebuilt = actual = None
            else:
                rebuilt = reconstruct(oof[mask], reference_values[mask], mode)
                if mode == ABSOLUTE_HUMIDITY:
                    rebuilt = relative_humidity(height_temp[mask], rebuilt)
                actual = values[mask]
                candidate_error = rmse(actual, rebuilt)
            entry = {
                "seasonal": seasonal, "model": model, "scaler": scaler,
                "feature_names": feature_names, "stats": stats,
                "mask": mask, "rebuilt": rebuilt, "actual": actual,
            }
            if best is None or candidate_error < best[0]:
                best = (candidate_error, entry)

        assert best is not None
        chosen = best[1]
        stats = chosen["stats"]
        self.models[(wire, measurement, height)] = (
            chosen["model"], chosen["scaler"], chosen["feature_names"], mode,
            chosen["seasonal"],
        )

        mask = chosen["mask"]
        if not mask.any():
            return HeightFit(
                wire, measurement, height, mode, stats, seasonal=chosen["seasonal"]
            )

        rebuilt, actual = chosen["rebuilt"], chosen["actual"]

        baselines = {
            "reference": reference_baseline(baseline_reference[mask]),
            "constant_offset": reconstruct(
                np.full(int(mask.sum()), float(np.mean(deviations[~mask]) if (~mask).any()
                                               else np.mean(deviations))),
                reference_values[mask], mode,
            ),
        }
        if mode == ABSOLUTE_HUMIDITY:
            baselines["constant_offset"] = relative_humidity(
                height_temp[mask], baselines["constant_offset"]
            )
        score_holdout(stats, actual, rebuilt, baselines)

        index = usable.index[mask]
        predicted_wide[height] = pd.Series(rebuilt, index=index)
        actual_wide[height] = pd.Series(actual, index=index)
        return HeightFit(
            wire, measurement, height, mode, stats, seasonal=chosen["seasonal"]
        )

        # Score in the measurement's own units, not in deviation units: a
        # deviation R² would flatter a model that merely learnt the mean offset.
        rebuilt = reconstruct(oof[mask], reference_values[mask], mode)
        if mode == ABSOLUTE_HUMIDITY:
            rebuilt = relative_humidity(height_temp[mask], rebuilt)
        actual = values[mask]

        baselines = {
            "reference": reference_baseline(reference.to_numpy(dtype=float)[mask]),
            "constant_offset": reconstruct(
                np.full(int(mask.sum()), float(np.mean(deviations[~mask]) if (~mask).any()
                                               else np.mean(deviations))),
                reference_values[mask], mode,
            ),
        }
        if mode == ABSOLUTE_HUMIDITY:
            baselines["constant_offset"] = relative_humidity(
                height_temp[mask], baselines["constant_offset"]
            )
        score_holdout(stats, actual, rebuilt, baselines)

        index = usable.index[mask]
        predicted_wide[height] = pd.Series(rebuilt, index=index)
        actual_wide[height] = pd.Series(actual, index=index)
        return HeightFit(wire, measurement, height, mode, stats)

    def predict(
        self, wire: str, measurement: str, height: int,
        reference: pd.Series,
        reference_temp: pd.Series | None = None,
        height_temp: pd.Series | None = None,
    ) -> pd.Series:
        """Per-height values for a predicted reference series.

        Humidity needs both: ``reference_temp`` to turn the reference RH into
        moisture content, and ``height_temp`` — this height's own predicted
        temperature — to turn the result back into an RH. Predict temperature
        for a height before predicting its humidity.
        """
        entry = self.models.get((wire, measurement, height))
        if entry is None:
            raise KeyError(f"no model for {wire} {measurement} h{height}")
        model, scaler, feature_names, mode, seasonal = entry

        X, _ = self._features(reference, seasonal=seasonal)
        deviations = model.predict(scaler.transform(X))

        base = reference.to_numpy(dtype=float)
        if mode == ABSOLUTE_HUMIDITY:
            if reference_temp is None or height_temp is None:
                raise ValueError(
                    "humidity prediction needs reference_temp and height_temp"
                )
            base = absolute_humidity(reference_temp.to_numpy(dtype=float), base)

        rebuilt = reconstruct(deviations, base, mode)
        if mode == ABSOLUTE_HUMIDITY:
            rebuilt = relative_humidity(height_temp.to_numpy(dtype=float), rebuilt)
        return pd.Series(rebuilt, index=reference.index, name=f"h{height}")


def _days_covered(spans: list[pd.Timestamp]) -> int:
    """Calendar days between the first and last wire reading seen."""
    if not spans:
        return 0
    return int((max(spans) - min(spans)).days) + 1


def profile_rmse(fits: list[HeightFit]) -> float:
    """Mean held-out RMSE across a set of height fits, in the measurement's units."""
    errors = [f.stats.holdout_rmse for f in fits if f.stats.holdout_rmse is not None]
    return round(float(np.mean(errors)), 3) if errors else float("nan")


__all__ = [
    "DEVIATION_MODE",
    "DownscaleStats",
    "HeightFit",
    "WireDownscaler",
    "deviation",
    "profile_rmse",
    "reconstruct",
    "rmse",
]
