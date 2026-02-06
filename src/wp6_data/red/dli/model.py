"""Two-stage ML model for predicting daily indoor light from weather data.

Stage 1: OpenMeteo daily weather → s1000 daily lux (calibrates API to local)
Stage 2: s1000 daily lux → daily indoor PAR sum (greenhouse transmission)

Features:
- Stage 1: direct_radiation_sum, diffuse_radiation_sum, cloud_cover_avg, day_of_year
- Stage 2: lux_sum, day_of_year

Trained on daily aggregates for better correlation (0.9+) vs hourly (0.7).
Uses Ridge regression to handle correlated features.
"""

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
    outdoor_sensor: str = "s1000"
    indoor_sensor: str = "s2100-01-par"
    aggregation: str = "daily"
    model_version: int = 5

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
        outdoor_sensor: str = "s1000",
        indoor_sensor: str = "s2100-01-par",
    ) -> ModelStats:
        """Train both stages on daily aggregated data.

        Args:
            weather_df: OpenMeteo data with columns: datetime, solar_radiation, cloud_cover
                       Optionally: diffuse_radiation for better accuracy
            outdoor_df: s1000 weather station with columns: time, lux
            indoor_df: PAR sensor with columns: time, value (or par)

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
            model_version=5,
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

        # Default day_of_year to today
        if day_of_year is None:
            day_of_year = datetime.now().timetuple().tm_yday

        # Calculate cyclical day-of-year features
        day_sin, day_cos = encode_day_of_year(day_of_year)

        # Build Stage 1 feature vector based on what was used during training
        feature_values = {
            "direct_radiation_sum": direct_radiation_sum,
            "diffuse_radiation_sum": diffuse_radiation_sum or 0.0,
            "cloud_cover_avg": cloud_cover_avg or 50.0,  # Default to 50% if not provided
            "day_of_year_sin": day_sin,
            "day_of_year_cos": day_cos,
        }

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
            "version": 6,  # Polynomial features + RidgeCV version
        }

        with open(path, "wb") as f:
            pickle.dump(data, f)

        return path

    def load(self, path: Path | None = None) -> ModelStats | None:
        """Load model from disk."""
        path = path or MODEL_PATH

        if not path.exists():
            return None

        with open(path, "rb") as f:
            data = pickle.load(f)

        version = data.get("version", 1)
        if version < 4:
            # Old model format - incompatible
            return None

        self.stage1_model = data["stage1_model"]
        self.stage2_model = data["stage2_model"]
        self.stats = data["stats"]

        # Load transformers and features (v5+)
        if version >= 5:
            self.stage1_scaler = data.get("stage1_scaler")
            self.stage2_scaler = data.get("stage2_scaler")
            self.stage1_features = data.get("stage1_features", ["direct_radiation_sum"])
            self.stage2_features = data.get("stage2_features", ["lux_sum"])
        else:
            # v4 compatibility - single feature, no scaling
            self.stage1_scaler = None
            self.stage2_scaler = None
            self.stage1_features = ["direct_radiation_sum"]
            self.stage2_features = ["lux_sum"]

        # Load polynomial transformers (v6+)
        if version >= 6:
            self.stage1_poly = data.get("stage1_poly")
            self.stage2_poly = data.get("stage2_poly")
        else:
            self.stage1_poly = None
            self.stage2_poly = None

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


