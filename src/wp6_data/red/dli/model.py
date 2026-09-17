"""Two-stage ML model for predicting daily indoor light from weather data.

Stage 1: OpenMeteo daily weather → s1000 daily lux (calibrates API to local)
Stage 2: s1000 daily lux → daily indoor PAR sum (greenhouse transmission)

Features:
- Stage 1: direct_radiation_sum, diffuse_radiation_sum, cloud_cover_avg, day_of_year
- Stage 2: lux_sum, day_of_year

Trained on daily aggregates for better correlation (0.9+) vs hourly (0.7).
Uses Ridge regression to handle correlated features.
"""

import contextlib
import os
import pickle
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
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
    WEATHER_STATION_SENSOR,
)
from wp6_data.shared.artifacts import fingerprint

# Bumped for a deliberate break: a change in the pickle layout, or in what the
# stored numbers mean when their shape is unchanged. Unlike earlier revisions
# this is an *equality* check, not a floor — see `load`.
MODEL_VERSION = 7


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
            ["direct_radiation", "diffuse_radiation"],
        ]
    )


def _default_model_path() -> Path:
    """Get default model path in user's home directory."""
    return Path.home() / ".wp6" / "models" / "light_model.pkl"


_env_path = os.getenv("WP6_RED_DLI_MODEL_PATH", "")
MODEL_PATH = Path(_env_path) if _env_path else _default_model_path()


@dataclass
class StageStats:
    """Statistics for a single model stage."""

    r2_score: float
    rmse: float
    mae: float
    n_samples: int
    coefficients: dict[str, float]
    intercept: float
    feature_names: list[str] = field(default_factory=list)


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

    @property
    def r2_score(self) -> float:
        """Combined R² (product of both stages)."""
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
        Input: lux_sum, day_of_year_sin, day_of_year_cos
        Output: daily sum of indoor PAR (μmol/m²/day, convert to DLI by /1e6*3600)

    Uses Ridge regression to handle correlated features.
    Uses daily aggregation for better correlation (~0.9 vs ~0.7 hourly).
    """

    def __init__(self):
        self.stage1_model = None  # OpenMeteo → daily lux
        self.stage2_model = None  # daily lux → daily indoor PAR
        self.stats: ModelStats | None = None
        # Extended feature set for better predictions
        self.stage1_features = [
            "direct_radiation_sum",
            "diffuse_radiation_sum",
            "cloud_cover_avg",
            "day_of_year_sin",
            "day_of_year_cos",
        ]
        self.stage2_features = ["lux_sum", "day_of_year_sin", "day_of_year_cos"]
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
        from sklearn.linear_model import RidgeCV
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
        from sklearn.preprocessing import StandardScaler

        # Reset feature lists to full extended set (may have been overwritten by load())
        candidate_s1_features = [
            "direct_radiation_sum",
            "diffuse_radiation_sum",
            "cloud_cover_avg",
            "day_of_year_sin",
            "day_of_year_cos",
        ]
        candidate_s2_features = ["lux_sum", "day_of_year_sin", "day_of_year_cos"]

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

        # Train Stage 1: daily OpenMeteo → daily lux with RidgeCV
        X1 = stage1_data[available_s1_features].values
        y1 = stage1_data["lux_sum"].values

        # Scale features, then RidgeCV with cross-validation for alpha
        alphas = [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]
        self.stage1_poly = None  # No polynomial features (simpler model)
        self.stage1_scaler = StandardScaler()

        X1_scaled = self.stage1_scaler.fit_transform(X1)

        self.stage1_model = RidgeCV(alphas=alphas, cv=5)
        self.stage1_model.fit(X1_scaled, y1)

        y1_pred = self.stage1_model.predict(X1_scaled)

        coef_dict = dict(zip(available_s1_features, self.stage1_model.coef_, strict=True))

        stage1_stats = StageStats(
            r2_score=round(r2_score(y1, y1_pred), 4),
            rmse=round(np.sqrt(mean_squared_error(y1, y1_pred)), 2),
            mae=round(mean_absolute_error(y1, y1_pred), 2),
            n_samples=len(stage1_data),
            coefficients=coef_dict,
            intercept=round(float(self.stage1_model.intercept_), 4),
            feature_names=available_s1_features,
        )

        # Train Stage 2: daily lux → daily indoor PAR
        available_s2_features = [f for f in candidate_s2_features if f in stage2_data.columns]
        X2 = stage2_data[available_s2_features].values
        y2 = stage2_data["par_sum"].values

        self.stage2_poly = None  # No polynomial features
        self.stage2_scaler = StandardScaler()

        X2_scaled = self.stage2_scaler.fit_transform(X2)

        self.stage2_model = RidgeCV(alphas=alphas, cv=5)
        self.stage2_model.fit(X2_scaled, y2)

        y2_pred = self.stage2_model.predict(X2_scaled)

        coef_dict2 = dict(zip(available_s2_features, self.stage2_model.coef_, strict=True))

        stage2_stats = StageStats(
            r2_score=round(r2_score(y2, y2_pred), 4),
            rmse=round(np.sqrt(mean_squared_error(y2, y2_pred)), 2),
            mae=round(mean_absolute_error(y2, y2_pred), 2),
            n_samples=len(stage2_data),
            coefficients=coef_dict2,
            intercept=round(float(self.stage2_model.intercept_), 4),
            feature_names=available_s2_features,
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
        direct_radiation_sum: float,
        diffuse_radiation_sum: float | None = None,
        cloud_cover_avg: float | None = None,
        day_of_year: int | None = None,
    ) -> float:
        """Predict daily indoor PAR sum from OpenMeteo daily forecast.

        Args:
            direct_radiation_sum: Daily sum of direct_radiation (W/m² summed over hours)
            diffuse_radiation_sum: Daily sum of diffuse_radiation (optional)
            cloud_cover_avg: Daily average cloud cover % (optional)
            day_of_year: Day of year 1-365 (optional, defaults to today)

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
            "lux_sum": predicted_lux_sum,
            "day_of_year_sin": day_sin,
            "day_of_year_cos": day_cos,
        }
        X2 = np.array([[s2_feature_values[f] for f in self.stage2_features]])

        if self.stage2_poly is not None:
            X2 = self.stage2_poly.transform(X2)
        if self.stage2_scaler is not None:
            X2 = self.stage2_scaler.transform(X2)

        predicted_par_sum = self.stage2_model.predict(X2)[0]

        # Apply attenuation to convert above-lamp prediction to plant-level estimate
        predicted_par_sum *= self.attenuation_factor

        return max(0.0, round(predicted_par_sum, 1))

    def predict_dli(
        self,
        direct_radiation_sum: float,
        diffuse_radiation_sum: float | None = None,
        cloud_cover_avg: float | None = None,
        day_of_year: int | None = None,
        readings_per_day: int = 144,  # Assuming 10-min intervals
    ) -> float:
        """Predict DLI (mol/m²/day) from OpenMeteo daily forecast.

        Args:
            direct_radiation_sum: Daily sum of direct_radiation
            diffuse_radiation_sum: Daily sum of diffuse_radiation (optional)
            cloud_cover_avg: Daily average cloud cover % (optional)
            day_of_year: Day of year 1-365 (optional, defaults to today)
            readings_per_day: Expected number of PAR readings per day

        Returns:
            Predicted DLI in mol/m²/day
        """
        par_sum = self.predict_daily(
            direct_radiation_sum,
            diffuse_radiation_sum=diffuse_radiation_sum,
            cloud_cover_avg=cloud_cover_avg,
            day_of_year=day_of_year,
        )

        # Convert PAR sum to DLI
        # PAR sum is sum of readings, each reading represents ~10 min = 600 seconds
        # DLI = PAR_avg * seconds_per_day / 1,000,000
        # PAR_avg = par_sum / readings_per_day
        # seconds_per_day ≈ readings_per_day * interval_seconds
        interval_seconds = 86400 / readings_per_day  # seconds per reading interval
        dli = (par_sum * interval_seconds) / 1_000_000

        return round(dli, 2)

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
