"""Two-stage ML model for predicting daily indoor light from weather data.

Stage 1: OpenMeteo daily direct_radiation → s1000 daily lux (calibrates API to local)
Stage 2: s1000 daily lux → daily indoor PAR sum (greenhouse transmission)

Trained on daily aggregates for better correlation (0.9+) vs hourly (0.7).
"""

import os
import pickle
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd


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

    Stage 1: Daily OpenMeteo direct_radiation → daily s1000 lux
        Input: daily sum of direct_radiation, avg cloud_cover, day_of_year
        Output: daily sum of lux (calibrated to local weather station)

    Stage 2: Daily s1000 lux → daily indoor PAR
        Input: daily sum of lux, day_of_year
        Output: daily sum of indoor PAR (μmol/m²/day, convert to DLI by /1e6*3600)

    Uses daily aggregation for better correlation (~0.9 vs ~0.7 hourly).
    """

    def __init__(self):
        self.stage1_model = None  # OpenMeteo → daily lux
        self.stage2_model = None  # daily lux → daily indoor PAR
        self.stats: ModelStats | None = None
        self.stage1_features = ["direct_radiation_sum"]
        self.stage2_features = ["lux_sum"]

    def is_trained(self) -> bool:
        """Check if both stages are trained."""
        return self.stage1_model is not None and self.stage2_model is not None

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
            outdoor_df: s1000 weather station with columns: time, lux
            indoor_df: PAR sensor with columns: time, value (or par)

        Returns:
            ModelStats with both stage statistics
        """
        from sklearn.linear_model import LinearRegression
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

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

        # Train Stage 1: daily OpenMeteo → daily lux
        X1 = stage1_data[self.stage1_features].values
        y1 = stage1_data["lux_sum"].values

        self.stage1_model = LinearRegression()
        self.stage1_model.fit(X1, y1)

        y1_pred = self.stage1_model.predict(X1)
        stage1_stats = StageStats(
            r2_score=round(r2_score(y1, y1_pred), 4),
            rmse=round(np.sqrt(mean_squared_error(y1, y1_pred)), 2),
            mae=round(mean_absolute_error(y1, y1_pred), 2),
            n_samples=len(stage1_data),
            coefficients=dict(zip(
                self.stage1_features, self.stage1_model.coef_, strict=True
            )),
            intercept=round(self.stage1_model.intercept_, 4),
        )

        # Train Stage 2: daily lux → daily indoor PAR
        X2 = stage2_data[self.stage2_features].values
        y2 = stage2_data["par_sum"].values

        self.stage2_model = LinearRegression()
        self.stage2_model.fit(X2, y2)

        y2_pred = self.stage2_model.predict(X2)
        stage2_stats = StageStats(
            r2_score=round(r2_score(y2, y2_pred), 4),
            rmse=round(np.sqrt(mean_squared_error(y2, y2_pred)), 2),
            mae=round(mean_absolute_error(y2, y2_pred), 2),
            n_samples=len(stage2_data),
            coefficients=dict(zip(
                self.stage2_features, self.stage2_model.coef_, strict=True
            )),
            intercept=round(self.stage2_model.intercept_, 4),
        )

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
        )

        return self.stats

    def _align_weather_to_outdoor_daily(
        self, weather_df: pd.DataFrame, outdoor_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Align and aggregate OpenMeteo + s1000 data to daily totals."""
        weather = weather_df.copy()
        outdoor = outdoor_df.copy()

        weather["datetime"] = pd.to_datetime(weather["datetime"], utc=True)
        outdoor["time"] = pd.to_datetime(outdoor["time"], utc=True)

        # Extract date
        weather["date"] = weather["datetime"].dt.date
        outdoor["date"] = outdoor["time"].dt.date

        # Aggregate weather to daily
        weather_daily = weather.groupby("date").agg({
            "solar_radiation": "sum",  # direct_radiation from OpenMeteo
        }).reset_index()
        weather_daily.columns = ["date", "direct_radiation_sum"]

        # Aggregate outdoor lux to daily
        outdoor_daily = outdoor.groupby("date").agg({
            "lux": "sum",
        }).reset_index()
        outdoor_daily.columns = ["date", "lux_sum"]

        # Merge
        merged = weather_daily.merge(outdoor_daily, on="date", how="inner")

        if merged.empty:
            return merged

        # Filter valid days (some light recorded)
        merged = merged[merged["lux_sum"] > 1000]  # At least some daylight
        merged = merged[merged["direct_radiation_sum"] > 0]

        return merged

    def _align_outdoor_to_indoor_daily(
        self, outdoor_df: pd.DataFrame, indoor_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Align and aggregate s1000 + indoor PAR data to daily totals."""
        outdoor = outdoor_df.copy()
        indoor = indoor_df.copy()

        outdoor["time"] = pd.to_datetime(outdoor["time"], utc=True)

        # Handle different column names
        if "time" in indoor.columns:
            indoor["datetime"] = pd.to_datetime(indoor["time"], utc=True)
        else:
            indoor["datetime"] = pd.to_datetime(indoor["datetime"], utc=True)

        if "value" in indoor.columns:
            indoor["par"] = indoor["value"]

        # Extract date
        outdoor["date"] = outdoor["time"].dt.date
        indoor["date"] = indoor["datetime"].dt.date

        # Aggregate to daily
        outdoor_daily = outdoor.groupby("date").agg({
            "lux": "sum",
        }).reset_index()
        outdoor_daily.columns = ["date", "lux_sum"]

        indoor_daily = indoor.groupby("date").agg({
            "par": "sum",
        }).reset_index()
        indoor_daily.columns = ["date", "par_sum"]

        # Merge
        merged = outdoor_daily.merge(indoor_daily, on="date", how="inner")

        if merged.empty:
            return merged

        # Filter valid days
        merged = merged[merged["lux_sum"] > 1000]
        merged = merged[merged["par_sum"] > 100]

        return merged

    def predict_daily(
        self,
        direct_radiation_sum: float,
    ) -> float:
        """Predict daily indoor PAR sum from OpenMeteo daily forecast.

        Args:
            direct_radiation_sum: Daily sum of direct_radiation (W/m² summed over hours)

        Returns:
            Predicted daily indoor PAR sum (μmol/m²/day sum over readings)
        """
        if not self.is_trained():
            raise RuntimeError("Model not trained. Call train() or load() first.")

        # Stage 1: OpenMeteo → daily lux
        X1 = np.array([[direct_radiation_sum]])
        predicted_lux_sum = self.stage1_model.predict(X1)[0]
        predicted_lux_sum = max(0, predicted_lux_sum)

        # Stage 2: daily lux → daily indoor PAR
        X2 = np.array([[predicted_lux_sum]])
        predicted_par_sum = self.stage2_model.predict(X2)[0]

        return max(0.0, round(predicted_par_sum, 1))

    def predict_dli(
        self,
        direct_radiation_sum: float,
        readings_per_day: int = 144,  # Assuming 10-min intervals
    ) -> float:
        """Predict DLI (mol/m²/day) from OpenMeteo daily forecast.

        Args:
            direct_radiation_sum: Daily sum of direct_radiation
            readings_per_day: Expected number of PAR readings per day

        Returns:
            Predicted DLI in mol/m²/day
        """
        par_sum = self.predict_daily(direct_radiation_sum)

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
            "stats": self.stats,
            "version": 4,  # Simplified single-feature version
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
            # Old model format - incompatible with simplified features
            return None

        self.stage1_model = data["stage1_model"]
        self.stage2_model = data["stage2_model"]
        self.stats = data["stats"]

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


def predict_indoor_par(
    solar_radiation: float,
    cloud_cover: float,
    hour: int,
    day_of_year: int,
) -> float | None:
    """Deprecated: The two-stage model is designed for daily predictions only.

    For hourly PAR estimation, use the model's daily prediction and distribute
    proportionally based on the hourly radiation profile. See optimizer.py for
    the correct approach.

    Always returns None to force fallback to physics-based estimation.
    Use model.predict_dli() with daily radiation sum for accurate predictions.
    """
    # The two-stage model predicts daily indoor PAR from daily radiation sums.
    # It cannot accurately predict hourly values from single-hour inputs.
    # Return None to force physics fallback for any legacy callers.
    return None
