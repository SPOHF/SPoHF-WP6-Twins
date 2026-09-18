"""Two-stage ML model for predicting daily indoor light from weather data.

Stage 1: OpenMeteo daily weather → s1000 daily lux (calibrates API to local)
Stage 2: s1000 daily lux → daily indoor PAR sum (greenhouse transmission)

Features:
- Stage 1: direct_radiation_sum, diffuse_radiation_sum, cloud_cover_avg, day_of_year
- Stage 2: lux_hours, day_of_year

Trained on daily aggregates for better correlation (0.9+) vs hourly (0.7).
Uses Ridge regression to handle correlated features.
"""

import contextlib
import os
import pickle
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from wp6_data.red.dli.aggregation import (
    add_day_of_year_features,
    align_outdoor_to_indoor_daily,
    align_weather_to_outdoor_daily,
    encode_day_of_year,
)
from wp6_data.red.dli.constants import (
    DEFAULT_TRAINING_START,
    NATURAL_LIGHT_SENSOR,
    TOTAL_LIGHT_SENSOR,
    UMOL_TO_MOL,
    WEATHER_STATION_SENSOR,
)
from wp6_data.red.fitting import (
    DEFAULT_CV_FOLDS,
    StageStats,
    climatology_baseline,
    climatology_table,
    fit_ridge,
    out_of_fold_predictions,
    persistence_baseline,
    score_holdout,
    time_blocked_splits,
)
from wp6_data.shared.artifacts import fingerprint

# Bumped for a deliberate break: a change in the pickle layout, or in what the
# stored numbers mean when their shape is unchanged. Unlike earlier revisions
# this is an *equality* check, not a floor — see `load`.
MODEL_VERSION = 10


# What each stage is fitted on. Chosen by measurement, not argument: every
# candidate was scored end to end, out of fold, across 4-10 fold counts
# (MODEL_PAPER §5.6).
#
# Stage 1 gets global horizontal irradiance and nothing else. The radiation *is*
# the season, so any calendar feature alongside it lets ridge spread weight
# across the two, leaving the radiation coefficient too small to separate a
# bright day from a dull one within a month — which is what clipped the summer
# peaks. The effect is not about the term being crude: an exact top-of-atmosphere
# envelope scored worse than no seasonal feature at all. Beam and diffuse are
# split in stage 2's world because they transmit through glass differently;
# stage 1 never sees glass, and splitting them there only costs it.
STAGE1_FEATURES: tuple[str, ...] = ("shortwave_sum",)

# Stage 2 keeps its day-of-year term — the one place a seasonal feature earns
# its place, standing in for the angle sunlight strikes the glass at. Dropping
# it, and swapping it for a clear-sky index, each made the *chain* worse even
# where they improved the stage in isolation.
STAGE2_FEATURES: tuple[str, ...] = ("lux_hours", "day_of_year_sin", "day_of_year_cos")


def fit_fingerprint() -> str:
    """Identifies the inputs this model would be fitted from today.

    Not a config object like the climate chain's, because the DLI model's inputs
    are still module constants (moving them into `metadata.yaml` is filed as
    follow-up work). What matters is that they are all here: change the training
    start, swap a sensor, or alter which weather variables are requested, and a
    model fitted before that change is refused rather than served.
    """
    return fingerprint(
        [
            MODEL_VERSION,
            DEFAULT_TRAINING_START.isoformat(),
            NATURAL_LIGHT_SENSOR,
            TOTAL_LIGHT_SENSOR,
            WEATHER_STATION_SENSOR,
            # What `train_model_from_db` asks OpenMeteo for.
            ["shortwave_radiation", "cloud_cover"],
            list(STAGE1_FEATURES),
            list(STAGE2_FEATURES),
        ]
    )


def _default_model_path() -> Path:
    """Get default model path in user's home directory."""
    return Path.home() / ".wp6" / "models" / "light_model.pkl"


_env_path = os.getenv("WP6_RED_DLI_MODEL_PATH", "")
MODEL_PATH = Path(_env_path) if _env_path else _default_model_path()


def _previous_day(days: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Each row's value from the calendar day before, NaN where there isn't one.

    Built from a date lookup rather than ``shift(1)``: the daily frames drop
    days that failed a quality gate, so the previous *row* is often not the
    previous *day*, and persistence has to mean yesterday.
    """
    lookup = dict(zip(days, values, strict=True))
    return np.array(
        [lookup.get(day - timedelta(days=1), np.nan) for day in days], dtype=float
    )


def _score_stage(
    stats: StageStats,
    days: np.ndarray,
    actual: np.ndarray,
    predicted: np.ndarray,
    mask: np.ndarray,
) -> None:
    """Attach out-of-fold quality, plus skill against the baselines that matter.

    A daily light model posts a high R² for knowing the time of year, so the
    number worth reading is what it removes from a baseline that already knows
    that: ``climatology`` (this month's mean) and ``persistence`` (yesterday).

    Everything is scored on one row set — those with an out-of-fold prediction
    *and* a previous day to carry forward. A skill score computed over
    different rows than the model's own error is not a comparison.

    ``climatology_table`` keys on (month, hour); these rows are daily, so the
    hour is constant and the table is a month-of-year mean, which is what a
    daily climatology should be. When every row has been held out at some point
    the table is necessarily built over all of them, so the baseline is mildly
    optimistic — which makes the reported skill against it conservative.
    """
    previous = _previous_day(days, actual)
    scored = mask & np.isfinite(previous)
    if not scored.any():
        return

    times = pd.Series(pd.to_datetime(list(days[scored]), utc=True))
    rest = ~scored
    table = (
        climatology_table(pd.Series(pd.to_datetime(list(days[rest]), utc=True)), actual[rest])
        if rest.any()
        else climatology_table(times, actual[scored])
    )
    score_holdout(
        stats,
        actual[scored],
        predicted[scored],
        {
            "persistence": persistence_baseline(previous[scored]),
            "climatology": climatology_baseline(
                table, times, float(np.mean(actual[scored]))
            ),
        },
    )


@dataclass
class ModelStats:
    """Statistics from two-stage model training."""

    stage1: StageStats  # OpenMeteo → s1000 lux (daily)
    stage2: StageStats  # s1000 lux → indoor PAR (daily)
    training_date: datetime
    date_range: tuple[date, date]
    outdoor_sensor: str = WEATHER_STATION_SENSOR
    indoor_sensor: str = NATURAL_LIGHT_SENSOR
    aggregation: str = "daily"
    model_version: int = MODEL_VERSION
    attenuation_factor: float = 1.0
    attenuation_samples: int = 0
    # Weather in, indoor PAR out, measured rather than inferred. ``None`` when
    # the two stages share too few days to score end to end.
    chain: StageStats | None = None

    @property
    def r2_score(self) -> float:
        """Out-of-fold R² of the whole chain.

        Previously the *product* of the two stages' in-sample R², which assumed
        an error propagation nobody had measured and reported a number neither
        stage could produce. Stage 2 is fitted on measured lux but served the
        lux stage 1 predicts, so the only honest combined figure is the one
        obtained by running it that way — see :meth:`_score_chain`.
        """
        if self.chain is not None and self.chain.holdout_r2 is not None:
            return self.chain.holdout_r2
        return round(self.stage1.r2_score * self.stage2.r2_score, 4)

    @property
    def n_samples(self) -> int:
        """Minimum samples across stages."""
        return min(self.stage1.n_samples, self.stage2.n_samples)


class TwoStageLightModel:
    """Two-stage model for predicting daily indoor light.

    Stage 1: Daily OpenMeteo weather → daily s1000 lux
        Input: direct_radiation_sum, diffuse_radiation_sum, cloud_cover_avg,
               day_of_year_sin, day_of_year_cos
        Output: daily sum of lux (calibrated to local weather station)

    Stage 2: Daily s1000 lux → daily indoor PAR
        Input: lux_hours, day_of_year_sin, day_of_year_cos
        Output: daily sum of indoor PAR (μmol/m²/day, convert to DLI by /1e6*3600)

    Uses Ridge regression to handle correlated features.
    Uses daily aggregation for better correlation (~0.9 vs ~0.7 hourly).
    """

    def __init__(self):
        self.stage1_model = None  # OpenMeteo → daily lux
        self.stage2_model = None  # daily lux → daily indoor PAR
        self.stats: ModelStats | None = None
        # Overwritten by `train` or `load`; the declared sets are the default so
        # an untrained instance cannot describe a shape nothing was fitted to.
        self.stage1_features = list(STAGE1_FEATURES)
        self.stage2_features = list(STAGE2_FEATURES)
        # Feature transformers
        self.stage1_poly = None
        self.stage2_poly = None
        self.stage1_scaler = None
        self.stage2_scaler = None
        # Attenuation: above-lamp → plant-level conversion factor
        self.attenuation_factor: float = 1.0

    def is_trained(self) -> bool:
        """Check if both stages are trained."""
        return self.stage1_model is not None and self.stage2_model is not None

    def _add_day_of_year_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add cyclical day-of-year features (sin/cos encoding)."""
        return add_day_of_year_features(df, date_col="date")

    def train(
        self,
        weather_df: pd.DataFrame,
        outdoor_df: pd.DataFrame,
        indoor_df: pd.DataFrame,
        outdoor_sensor: str = WEATHER_STATION_SENSOR,
        indoor_sensor: str = NATURAL_LIGHT_SENSOR,
        plant_level_df: pd.DataFrame | None = None,
        above_lamp_df: pd.DataFrame | None = None,
    ) -> ModelStats:
        """Train both stages on daily aggregated data.

        Args:
            weather_df: OpenMeteo data with columns: datetime, solar_radiation, cloud_cover
                       Optionally: diffuse_radiation for better accuracy
            outdoor_df: s1000 weather station with columns: time, lux
            indoor_df: PAR sensor with columns: time, value (or par)
                       (now s2100-01-par, the above-lamp sensor)
            plant_level_df: Optional s2100-02-par readings for attenuation computation
            above_lamp_df: Optional s2100-01-par readings for attenuation computation

        Returns:
            ModelStats with both stage statistics
        """
        # Reset feature lists to full extended set (may have been overwritten by load())
        candidate_s1_features = list(STAGE1_FEATURES)
        candidate_s2_features = list(STAGE2_FEATURES)

        # Aggregate to daily and align (Stage 1)
        stage1_data = self._align_weather_to_outdoor_daily(weather_df, outdoor_df)
        if len(stage1_data) < 10:
            raise ValueError(
                f"Insufficient Stage 1 data: {len(stage1_data)} days "
                "(need OpenMeteo + s1000 overlap)"
            )

        # Aggregate to daily and align (Stage 2)
        stage2_data = self._align_outdoor_to_indoor_daily(outdoor_df, indoor_df)
        if len(stage2_data) < 10:
            raise ValueError(
                f"Insufficient Stage 2 data: {len(stage2_data)} days "
                "(need s1000 + indoor PAR overlap)"
            )

        # Add day-of-year features
        stage1_data = self._add_day_of_year_features(stage1_data)
        stage2_data = self._add_day_of_year_features(stage2_data)

        # Determine available features for Stage 1
        available_s1_features = [f for f in candidate_s1_features if f in stage1_data.columns]
        if not available_s1_features:
            raise ValueError("No valid Stage 1 features found in data")

        # Train Stage 1: daily OpenMeteo → daily lux.
        #
        # Day-blocked folds, not sklearn's random K-fold: consecutive days share
        # a weather system, so a random split trains on the test set's
        # neighbours and every score comes back flattering.
        X1 = stage1_data[available_s1_features].to_numpy(dtype=float)
        y1 = stage1_data["lux_hours"].to_numpy(dtype=float)
        days1 = stage1_data["date"].to_numpy()

        self.stage1_poly = None  # No polynomial features (simpler model)
        self.stage1_model, self.stage1_scaler, stage1_stats = fit_ridge(
            X1, y1, available_s1_features, days=days1
        )
        oof1, mask1 = out_of_fold_predictions(X1, y1, available_s1_features, days1)
        _score_stage(stage1_stats, days1, y1, oof1, mask1)

        # Train Stage 2: daily lux → daily indoor PAR
        available_s2_features = [f for f in candidate_s2_features if f in stage2_data.columns]
        X2 = stage2_data[available_s2_features].to_numpy(dtype=float)
        y2 = stage2_data["par_integral"].to_numpy(dtype=float)
        days2 = stage2_data["date"].to_numpy()

        self.stage2_poly = None  # No polynomial features
        self.stage2_model, self.stage2_scaler, stage2_stats = fit_ridge(
            X2, y2, available_s2_features, days=days2
        )
        oof2, mask2 = out_of_fold_predictions(X2, y2, available_s2_features, days2)
        _score_stage(stage2_stats, days2, y2, oof2, mask2)

        chain_stats = self._score_chain(
            stage2_stats, available_s2_features, X2, y2, days2,
            days1, oof1, mask1,
        )

        # Store the actual features used
        self.stage1_features = available_s1_features
        self.stage2_features = available_s2_features

        # Compute attenuation factor (above-lamp → plant-level)
        attenuation_factor = 1.0
        attenuation_samples = 0
        if plant_level_df is not None and above_lamp_df is not None:
            with contextlib.suppress(Exception):
                attenuation_factor, attenuation_samples = self._compute_attenuation(
                    above_lamp_df, plant_level_df
                )
        self.attenuation_factor = attenuation_factor

        # Date range
        all_dates = list(stage1_data["date"]) + list(stage2_data["date"])
        date_range = (min(all_dates), max(all_dates)) if all_dates else (None, None)

        self.stats = ModelStats(
            stage1=stage1_stats,
            stage2=stage2_stats,
            chain=chain_stats,
            training_date=datetime.now(UTC),
            date_range=date_range,
            outdoor_sensor=outdoor_sensor,
            indoor_sensor=indoor_sensor,
            aggregation="daily",
            model_version=MODEL_VERSION,
            attenuation_factor=round(attenuation_factor, 4),
            attenuation_samples=attenuation_samples,
        )

        return self.stats

    def _align_weather_to_outdoor_daily(
        self, weather_df: pd.DataFrame, outdoor_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Align and aggregate OpenMeteo + s1000 data to daily totals.

        Handles both single-radiation (solar_radiation) and multi-radiation
        (direct_radiation, diffuse_radiation) weather data formats.
        """
        return align_weather_to_outdoor_daily(weather_df, outdoor_df)

    def _align_outdoor_to_indoor_daily(
        self, outdoor_df: pd.DataFrame, indoor_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Align and aggregate s1000 + indoor PAR data to daily totals."""
        return align_outdoor_to_indoor_daily(outdoor_df, indoor_df)

    def _score_chain(
        self,
        stage2_stats: StageStats,
        s2_features: list[str],
        X2: np.ndarray,
        y2: np.ndarray,
        days2: np.ndarray,
        days1: np.ndarray,
        oof1: np.ndarray,
        mask1: np.ndarray,
    ) -> StageStats | None:
        """Score the chain the way it is served: on predicted lux, not measured.

        Stage 2 is *fitted* on the lux the station recorded, because that is the
        cleanest signal to learn the greenhouse's transmission from. But no
        future day has a recorded lux — serving has only stage 1's estimate — so
        that is what stage 2 is evaluated on here. Each fold fits on measured
        lux and predicts its held-out days from predicted lux, which is exactly
        what a forecast does.

        This is the number that replaces ``stage1_R² × stage2_R²``. The product
        was never a bound on anything: it assumed the stages' errors compound in
        a way nobody had measured, and it flattered stage 2 by crediting it with
        an input it never receives.

        Returns ``None`` when the two stages share too few days to fold.
        """
        if "lux_hours" not in s2_features:
            return None

        predicted_lux = {
            day: value
            for day, value, ok in zip(days1, oof1, mask1, strict=True)
            if ok
        }
        has_lux = np.array([day in predicted_lux for day in days2])
        if has_lux.sum() < DEFAULT_CV_FOLDS:
            return None

        lux_column = s2_features.index("lux_hours")
        X2_chain = X2.copy()
        X2_chain[has_lux, lux_column] = [predicted_lux[day] for day in days2[has_lux]]

        predictions = np.full(len(y2), np.nan, dtype=float)
        for train_idx, test_idx in time_blocked_splits(days2, DEFAULT_CV_FOLDS):
            model, scaler, _ = fit_ridge(
                X2[train_idx], y2[train_idx], s2_features, days=days2[train_idx],
            )
            predictions[test_idx] = model.predict(scaler.transform(X2_chain[test_idx]))

        mask = has_lux & ~np.isnan(predictions)
        if not mask.any():
            return None

        # The same fitted shape with its own out-of-sample verdict. `skill` has
        # to be a new dict: `replace` would otherwise share stage 2's.
        stats = replace(
            stage2_stats,
            holdout_r2=None, holdout_rmse=None, holdout_mae=None,
            n_holdout=0, skill={},
        )
        _score_stage(stats, days2, y2, predictions, mask)
        return stats

    def _compute_attenuation(
        self, above_lamp_df: pd.DataFrame, plant_level_df: pd.DataFrame
    ) -> tuple[float, int]:
        """Attenuation factor; see :func:`wp6_data.red.lamp.compute_attenuation`.

        Kept as a method for the existing callers and tests; the arithmetic
        moved to ``lamp.py`` so the climate model can use the same number
        instead of computing its own.
        """
        from wp6_data.red.lamp import compute_attenuation

        return compute_attenuation(above_lamp_df, plant_level_df)

    def predict_daily(
        self,
        direct_radiation_sum: float | None = None,
        diffuse_radiation_sum: float | None = None,
        cloud_cover_avg: float | None = None,
        day_of_year: int | None = None,
        *,
        shortwave_sum: float | None = None,
        at_plant_level: bool = True,
    ) -> float:
        """Predict daily indoor PAR sum from OpenMeteo daily forecast.

        Stage 2 is fitted on ``NATURAL_LIGHT_SENSOR``, which hangs *above* the
        lamps, so the above-lamp PAR sum is what it natively predicts.
        ``at_plant_level`` multiplies by the attenuation factor to reach the
        under-lamp position instead.

        The two are different physical quantities — they differ by the whole
        attenuation factor, around a third — so the caller says which it wants
        rather than inferring it from the magnitudes. Scoring a plant-level
        prediction against the above-lamp sensor reads as a model that
        underpredicts by 38%, when nothing is wrong with the model at all.

        Args:
            direct_radiation_sum: Daily sum of direct_radiation (only needed by
                models fitted before v9)
            diffuse_radiation_sum: Daily sum of diffuse_radiation (optional)
            cloud_cover_avg: Daily average cloud cover % (optional)
            day_of_year: Day of year 1-365 (optional, defaults to today)
            shortwave_sum: Daily sum of global horizontal irradiance, which is
                what stage 1 is fitted on from v9 onward
            at_plant_level: Convert the above-lamp prediction to the plant-level
                position. Default, because that is the light a grower asks about
                and what the lamp contribution is added to. Pass ``False`` to
                compare against ``NATURAL_LIGHT_SENSOR`` itself, which sits
                above the lamps and is therefore not attenuated.

        Returns:
            Predicted daily indoor PAR sum (μmol/m²/day sum over readings)
        """
        if not self.is_trained():
            raise RuntimeError("Model not trained. Call train() or load() first.")

        # Default day_of_year to today. Only right for a prediction *about* today:
        # a caller predicting any other date must say which, or the seasonal term
        # is silently frozen (see predict_natural_dli_from_weather).
        if day_of_year is None:
            day_of_year = datetime.now().timetuple().tm_yday

        # Calculate cyclical day-of-year features
        day_sin, day_cos = encode_day_of_year(day_of_year)

        # Build Stage 1 feature vector based on what was used during training
        # A feature the model was *fitted* on has no sensible default: standing in
        # 0.0 diffuse or 50% cloud applies coefficients to a number the weather
        # never produced, and the result reads like a working prediction. Refuse
        # instead, so a caller that forgets one finds out.
        feature_values = {
            "shortwave_sum": shortwave_sum,
            "direct_radiation_sum": direct_radiation_sum,
            "diffuse_radiation_sum": diffuse_radiation_sum,
            "cloud_cover_avg": cloud_cover_avg,
            "day_of_year_sin": day_sin,
            "day_of_year_cos": day_cos,
        }
        missing = [f for f in self.stage1_features if feature_values.get(f) is None]
        if missing:
            raise ValueError(
                f"Stage 1 was trained on {missing} but they were not supplied. "
                "Pass them from the forecast rather than letting a default stand in."
            )

        X1 = np.array([[feature_values[f] for f in self.stage1_features]])

        # Apply polynomial transform and scaling if available
        if self.stage1_poly is not None:
            X1 = self.stage1_poly.transform(X1)
        if self.stage1_scaler is not None:
            X1 = self.stage1_scaler.transform(X1)

        predicted_lux_sum = self.stage1_model.predict(X1)[0]
        predicted_lux_sum = max(0, predicted_lux_sum)

        # Build Stage 2 feature vector
        s2_feature_values = {
            "lux_hours": predicted_lux_sum,
            "day_of_year_sin": day_sin,
            "day_of_year_cos": day_cos,
        }
        X2 = np.array([[s2_feature_values[f] for f in self.stage2_features]])

        if self.stage2_poly is not None:
            X2 = self.stage2_poly.transform(X2)
        if self.stage2_scaler is not None:
            X2 = self.stage2_scaler.transform(X2)

        predicted_par_sum = self.stage2_model.predict(X2)[0]

        # Attenuation is the above-lamp -> plant-level conversion, so it applies
        # only when the caller asked for plant level. Applying it unconditionally
        # is what made /dli/performance score an attenuated prediction against
        # the un-attenuated above-lamp sensor.
        if at_plant_level:
            predicted_par_sum *= self.attenuation_factor

        return max(0.0, round(predicted_par_sum, 1))

    def predict_dli(
        self,
        direct_radiation_sum: float | None = None,
        diffuse_radiation_sum: float | None = None,
        cloud_cover_avg: float | None = None,
        day_of_year: int | None = None,
        readings_per_day: int = 144,  # unused from v10; kept for callers
        *,
        shortwave_sum: float | None = None,
        at_plant_level: bool = True,
    ) -> float:
        """Predict DLI (mol/m²/day) from OpenMeteo daily forecast.

        Args:
            direct_radiation_sum: Daily sum of direct_radiation
            diffuse_radiation_sum: Daily sum of diffuse_radiation (optional)
            cloud_cover_avg: Daily average cloud cover % (optional)
            day_of_year: Day of year 1-365 (optional, defaults to today)
            readings_per_day: Ignored from v10 — stage 2 predicts a time
                integral, so no cadence is assumed
            at_plant_level: Which sensor position to predict for; see
                :meth:`predict_daily`.

        Returns:
            Predicted DLI in mol/m²/day
        """
        par_integral = self.predict_daily(
            direct_radiation_sum,
            diffuse_radiation_sum=diffuse_radiation_sum,
            cloud_cover_avg=cloud_cover_avg,
            day_of_year=day_of_year,
            shortwave_sum=shortwave_sum,
            at_plant_level=at_plant_level,
        )

        # Stage 2 predicts an integral in μmol/m², so DLI is a plain unit
        # conversion. From v10 there is no reading-cadence assumption left in
        # this path: `readings_per_day` only ever stood in for one.
        return round(par_integral / UMOL_TO_MOL, 2)

    def save(self, path: Path | None = None) -> Path:
        """Save model to disk."""
        if not self.is_trained():
            raise RuntimeError("No model to save. Train first.")

        path = path or MODEL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "stage1_model": self.stage1_model,
            "stage2_model": self.stage2_model,
            "stage1_poly": self.stage1_poly,
            "stage2_poly": self.stage2_poly,
            "stage1_scaler": self.stage1_scaler,
            "stage2_scaler": self.stage2_scaler,
            "stage1_features": self.stage1_features,
            "stage2_features": self.stage2_features,
            "stats": self.stats,
            "attenuation_factor": self.attenuation_factor,
            "version": MODEL_VERSION,
            # What produced this fit. Checked on load, because the model now
            # outlives the pod that trained it — see ADR 0007.
            "fingerprint": fit_fingerprint(),
        }

        with open(path, "wb") as f:
            pickle.dump(data, f)

        return path

    def load(self, path: Path | None = None) -> ModelStats | None:
        """Load the saved model, or return ``None`` when there isn't a usable one.

        **Equality on the version, not a floor.** Earlier revisions accepted v4,
        v5 and v6 artifacts and filled the gaps with defaults — a guessed feature
        list of ``["direct_radiation_sum"]``, an attenuation of ``1.0``. That was
        survivable while models died with the pod that wrote them, because an old
        artifact could not outlive its deploy. Now that they persist, a migrated
        model can be served indefinitely, and a *guessed* feature list is
        indistinguishable downstream from a fitted one. Refusing costs one refit;
        the alternative costs wrong numbers with no signal.

        Never raises. Anything a pickle from another era can throw — a moved
        class, a removed attribute, a truncated write — means the same thing to a
        caller that can simply retrain, and this one is called during startup.
        """
        path = path or MODEL_PATH

        if not path.exists():
            return None

        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
        except Exception:
            return None

        if not isinstance(data, dict) or data.get("version") != MODEL_VERSION:
            return None
        if data.get("fingerprint") != fit_fingerprint():
            # Same layout, different inputs: the training window moved, or a
            # sensor was swapped. Refit rather than answer an older question.
            return None

        try:
            self.stage1_model = data["stage1_model"]
            self.stage2_model = data["stage2_model"]
            self.stats = data["stats"]
            self.stage1_scaler = data["stage1_scaler"]
            self.stage2_scaler = data["stage2_scaler"]
            self.stage1_features = data["stage1_features"]
            self.stage2_features = data["stage2_features"]
            self.stage1_poly = data["stage1_poly"]
            self.stage2_poly = data["stage2_poly"]
            self.attenuation_factor = data["attenuation_factor"]
        except KeyError:
            # A key the current version promises is absent: not a model we can
            # use, and not one to patch up with a default.
            return None

        # Simulation override, deliberately applied after the artifact is read.
        override = os.getenv("WP6_RED_DLI_ATTENUATION_OVERRIDE")
        if override:
            self.attenuation_factor = float(override)

        return self.stats


# Backwards compatible alias
LightCorrelationModel = TwoStageLightModel


# Global model instance
_model: TwoStageLightModel | None = None


def get_model() -> TwoStageLightModel:
    """Get or create the global model instance, loading from disk if available."""
    global _model

    if _model is None:
        _model = TwoStageLightModel()
        _model.load()

    return _model
