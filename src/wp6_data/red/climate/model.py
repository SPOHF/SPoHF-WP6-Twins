"""Links 1-2 of red's climate model: weather → outdoor station → greenhouse level.

**Link 1** calibrates OpenMeteo's modelled weather to what red's own outdoor
station actually records. **Link 2** predicts the greenhouse-level reference at
``t + horizon`` from the greenhouse's recent state, link 1's output, and the
time of day and year.

Two choices here are load-bearing:

*Link 2 trains on link 1's predictions, not on measured ``s1000``.* At serving
time there is no measured outdoor reading for a future hour — only a forecast
run through link 1 — so training on the measured value would tune link 2 to an
input it will never see and report an accuracy it cannot reproduce. This is why
the chain is fitted in order rather than stage-by-stage in isolation, and why
there is no "combined R² = product of stages" anywhere in this module.

*Every reported score is out-of-fold.* Day-blocked folds are held out in turn
(``fitting.out_of_fold_predictions``), so each row is predicted by a fit that
never saw its block, while the score still spans every season in the data. A
single trailing holdout would have tested one season and said nothing about the
rest.

A model of a slowly-moving indoor quantity scores well by doing nothing, so the
skill against persistence and climatology — not R² — is what the status page
leads with.
"""

from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from wp6_data.red.climate.config import ClimateModelConfig
from wp6_data.red.climate.features import (
    build_supervised,
    feature_row,
    hourly_frame,
)
from wp6_data.red.fitting import (
    StageStats,
    climatology_baseline,
    climatology_table,
    fit_ridge,
    out_of_fold_predictions,
    persistence_baseline,
    rmse,
    score_holdout,
)

# Bumped whenever the pickle layout or the feature contract changes. `load`
# refuses anything older rather than silently mixing eras, so a stale model on
# ephemeral disk degrades to "retrain" instead of to wrong numbers.
#
# v2: the lamp model moved from `climate/lamp.py` to `red/lamp.py`. A pickle
# records a class by module path, so every v1 artifact names a module that no
# longer exists and cannot be unpickled at all — see `read_artifact`.
MODEL_VERSION = 2

# Hourly OpenMeteo variables link 1 calibrates from. Radiation is split into
# direct and diffuse because they transmit through glass differently — the same
# reasoning as the DLI model's MODEL_PAPER §4.3.
WEATHER_VARIABLES: tuple[str, ...] = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "cloud_cover",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "wind_speed_10m",
    "precipitation",
    "surface_pressure",
)

# A stage with fewer rows than this is not reported at all, rather than reported
# with a score nobody should read. Link 1 sees ~8000 hourly rows across the
# span; link 2 loses rows to lags, horizons and gaps.
MIN_LINK1_ROWS = 200
MIN_LINK2_ROWS = 200


WEATHER_PREFIX = "wx_"
OUTDOOR_PREFIX = "out_"
PREDICTED_OUTDOOR_PREFIX = "outhat_"


def read_artifact(path: Path) -> dict | None:
    """The pickled artifact at ``path``, or ``None`` when it cannot be used.

    A version check only protects against artifacts we can still *read*. Pickle
    stores classes by module path, so moving or renaming one makes every older
    artifact unreadable — the load fails before the version inside it can be
    consulted. Treating that as "no model" is what keeps the promise the version
    check makes on its own: a stale artifact on ephemeral disk degrades to
    "retrain", never to a crash and never to wrong numbers.

    Deliberately broad: anything a pickle from another era can raise
    (a moved class, a removed attribute, a different library version, a
    truncated write) means the same thing to a caller that can simply retrain.
    """
    if not path.exists():
        return None
    try:
        with open(path, "rb") as handle:
            data = pickle.load(handle)
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("version", 0) != MODEL_VERSION:
        return None
    return data


def _default_model_dir() -> Path:
    return Path.home() / ".wp6" / "models"


_env_dir = os.getenv("WP6_RED_CLIMATE_MODEL_PATH", "")
MODEL_PATH = (
    Path(_env_dir) if _env_dir else _default_model_dir() / "climate_model.pkl"
)


@dataclass
class HorizonFit:
    """One (target, horizon) model's out-of-fold verdict."""

    target: str
    horizon_hours: int
    stats: StageStats
    # Held-out RMSE per hour of day. Kept with the fit because it is the only
    # diagnostic that distinguishes a model which learnt the day's *shape* from
    # one that merely tracks its mean — both score the same overall.
    error_by_hour: list[tuple[int, float]] = field(default_factory=list)
    # Held-out RMSE per calendar month. Absolute error tracks the magnitude of
    # the signal, and for PAR that magnitude swings with the season — measured
    # at a 3.5x range across the year against 1.4x for temperature. A single
    # RMSE averages that away and reads as a property of the model when it is
    # partly a property of the month.
    error_by_month: list[tuple[int, float]] = field(default_factory=list)

    @property
    def beats_persistence(self) -> bool:
        """Whether this fit removes any of persistence's error at all."""
        return self.stats.skill.get("persistence", 0.0) > 0.0


@dataclass
class ClimateModelStats:
    """Everything the status page needs to judge a training run."""

    trained_at: datetime
    span: tuple[date | None, date | None]
    reference_key: str
    link1: dict[str, StageStats] = field(default_factory=dict)
    link2: list[HorizonFit] = field(default_factory=list)
    rows: dict[str, int] = field(default_factory=dict)
    excluded_days: int = 0
    model_version: int = MODEL_VERSION

    @property
    def targets(self) -> list[str]:
        return sorted({fit.target for fit in self.link2})

    @property
    def horizons(self) -> list[int]:
        return sorted({fit.horizon_hours for fit in self.link2})

    def fit_for(self, target: str, horizon: int) -> HorizonFit | None:
        for fit in self.link2:
            if fit.target == target and fit.horizon_hours == horizon:
                return fit
        return None

    @property
    def horizons_beating_persistence(self) -> list[tuple[str, int]]:
        """The (target, horizon) pairs that actually earned their place."""
        return [(f.target, f.horizon_hours) for f in self.link2 if f.beats_persistence]


class IndoorClimateModel:
    """The weather → outdoor → greenhouse-level chain, for one reference sensor.

    One instance per candidate greenhouse-level reference; which reference gives
    the better chain is measured, not assumed, so both are trained and compared.
    """

    def __init__(self, config: ClimateModelConfig, reference_key: str):
        self.config = config
        self.reference_key = reference_key
        self.link1_models: dict[str, tuple[Any, Any, list[str]]] = {}
        self.link2_models: dict[tuple[str, int], tuple[Any, Any, list[str]]] = {}
        self.stats: ClimateModelStats | None = None
        # The exact column order link 2 was fitted with. Reconstructing it at
        # prediction time is how a train/serve mismatch gets in: sorting the
        # targets rather than keeping their fitted order silently reorders every
        # lag feature.
        self.link2_autoregressive: list[str] = []
        self.link2_exogenous: list[str] = []
        # Which (device, sensor) each link-2 column came from. Serving must
        # fetch the same set: a column training had and serving lacks silently
        # drops every lag built from it.
        self.link2_sources: dict[str, tuple[str, str]] = {}
        # Climatology tables kept from training so a prediction can be compared
        # against the same baseline the score was computed against.
        self.climatology: dict[str, dict[tuple[int, int], float]] = {}

    def is_trained(self) -> bool:
        return bool(self.link2_models)

    # ── training ────────────────────────────────────────────────────────────

    def train(
        self,
        weather: pd.DataFrame,
        outdoor: dict[str, pd.DataFrame],
        indoor: dict[str, pd.DataFrame],
    ) -> ClimateModelStats:
        """Fit both links and report out-of-fold quality.

        ``weather`` is the hourly OpenMeteo frame (a ``datetime`` column plus one
        column per variable). ``outdoor`` and ``indoor`` map a name to a
        ``time, value`` frame, as ``data.sensor_frames`` returns them.
        """
        weather_hourly = self._weather_frame(weather)
        outdoor_hourly = hourly_frame(
            {f"{OUTDOOR_PREFIX}{name}": df for name, df in outdoor.items()}
        )
        indoor_hourly = hourly_frame(indoor)

        link1_stats, predicted_outdoor = self._train_link1(
            weather_hourly, outdoor_hourly
        )
        link2_fits = self._train_link2(indoor_hourly, predicted_outdoor, list(indoor))

        observed = indoor_hourly.dropna(how="all")
        span = (
            (observed.index.min().date(), observed.index.max().date())
            if not observed.empty
            else (None, None)
        )
        self.stats = ClimateModelStats(
            trained_at=datetime.now(UTC),
            span=span,
            reference_key=self.reference_key,
            link1=link1_stats,
            link2=link2_fits,
            rows={name: int(df.shape[0]) for name, df in indoor.items()},
            excluded_days=self._excluded_days(span),
        )
        return self.stats

    def _weather_frame(self, weather: pd.DataFrame) -> pd.DataFrame:
        """OpenMeteo's hourly frame on the shared hourly index, prefixed."""
        if weather.empty:
            return pd.DataFrame()
        series = {
            f"{WEATHER_PREFIX}{column}": weather[["datetime", column]].rename(
                columns={"datetime": "time", column: "value"}
            )
            for column in weather.columns
            if column != "datetime"
        }
        return hourly_frame(series)

    def _train_link1(
        self, weather: pd.DataFrame, outdoor: pd.DataFrame
    ) -> tuple[dict[str, StageStats], pd.DataFrame]:
        """Calibrate the weather API to the local outdoor station.

        Returns the per-target stats and a frame of **predicted** outdoor values
        spanning the whole weather index — including hours the station itself
        never reported, which is what lets link 2 train on an input it will also
        have at serving time.
        """
        stats: dict[str, StageStats] = {}
        predicted = pd.DataFrame(index=weather.index)
        if weather.empty or outdoor.empty:
            return stats, predicted

        joined = weather.join(outdoor, how="left")
        weather_columns = [c for c in weather.columns]

        for column in outdoor.columns:
            usable = joined[[*weather_columns, column]].dropna()
            if len(usable) < MIN_LINK1_ROWS:
                continue
            X = usable[weather_columns].to_numpy(dtype=float)
            y = usable[column].to_numpy(dtype=float)
            days = np.array([ts.date() for ts in usable.index])

            model, scaler, stage = fit_ridge(X, y, weather_columns, days=days)
            oof, mask = out_of_fold_predictions(X, y, weather_columns, days)
            if mask.any():
                score_holdout(stage, y[mask], oof[mask])
            stats[column] = stage

            # A stage that cannot beat its own mean out-of-fold is noise, and
            # noise handed to link 2 is a feature that can only cost it. Local
            # wind is the real case: OpenMeteo's 10 m wind does not describe
            # what the station in the yard records. Kept in `stats` so the page
            # still reports the attempt and its verdict.
            if stage.holdout_r2 is None or stage.holdout_r2 <= 0:
                continue
            self.link1_models[column] = (model, scaler, weather_columns)

            name = column.replace(OUTDOOR_PREFIX, PREDICTED_OUTDOOR_PREFIX, 1)
            complete = weather[weather_columns].dropna()
            if not complete.empty:
                predicted.loc[complete.index, name] = model.predict(
                    scaler.transform(complete.to_numpy(dtype=float))
                )
        return stats, predicted

    def _train_link2(
        self,
        indoor: pd.DataFrame,
        predicted_outdoor: pd.DataFrame,
        targets: list[str],
    ) -> list[HorizonFit]:
        """Predict each indoor target at each horizon, scored out-of-fold."""
        fits: list[HorizonFit] = []
        if indoor.empty:
            return fits

        frame = indoor.join(predicted_outdoor, how="left")
        exogenous = list(predicted_outdoor.columns)
        self.link2_autoregressive = list(targets)
        self.link2_exogenous = exogenous

        for target in targets:
            if target not in frame:
                continue
            for horizon in self.config.horizons_hours:
                supervised = build_supervised(
                    frame, target,
                    horizon_hours=horizon,
                    lag_hours=self.config.lag_hours,
                    autoregressive=targets,
                    exogenous=exogenous,
                    with_day_of_year=True,
                )
                if len(supervised) < MIN_LINK2_ROWS:
                    continue

                model, scaler, stage = fit_ridge(
                    supervised.X, supervised.y, supervised.feature_names,
                    days=supervised.days,
                )
                self.link2_models[(target, horizon)] = (
                    model, scaler, supervised.feature_names,
                )

                oof, mask = out_of_fold_predictions(
                    supervised.X, supervised.y, supervised.feature_names,
                    supervised.days,
                )
                hourly: list[tuple[int, float]] = []
                monthly: list[tuple[int, float]] = []
                if mask.any():
                    self._score_with_baselines(stage, supervised, oof, mask, target)
                    times = supervised.time_target[mask.nonzero()[0]]
                    hourly = [
                        (int(row.hour), float(row.rmse))
                        for row in error_by_hour(
                            supervised.y[mask], oof[mask], times
                        ).itertuples(index=False)
                    ]
                    monthly = [
                        (int(row.month), float(row.rmse))
                        for row in error_by_month(
                            supervised.y[mask], oof[mask], times
                        ).itertuples(index=False)
                    ]
                fits.append(
                    HorizonFit(
                        target, horizon, stage,
                        error_by_hour=hourly, error_by_month=monthly,
                    )
                )
        return fits

    def _score_with_baselines(
        self, stage: StageStats, supervised: Any, oof: np.ndarray,
        mask: np.ndarray, target: str,
    ) -> None:
        """Attach out-of-fold quality plus skill against the real baselines.

        The climatology table is built from the rows *not* being scored, so the
        baseline cannot see the period it is being judged on — the same
        discipline the model itself is held to.
        """
        actual = supervised.y[mask]
        times = supervised.time_target[mask.nonzero()[0]]

        table = climatology_table(
            supervised.time_target[(~mask).nonzero()[0]], supervised.y[~mask]
        ) if (~mask).any() else climatology_table(supervised.time_target, supervised.y)
        self.climatology[target] = table

        baselines = {
            "persistence": persistence_baseline(supervised.y_now[mask]),
            "climatology": climatology_baseline(table, times, float(np.mean(actual))),
        }
        score_holdout(stage, actual, oof[mask], baselines)

    def _excluded_days(self, span: tuple[date | None, date | None]) -> int:
        start, end = span
        if start is None or end is None:
            return 0
        days = pd.date_range(start, end, freq="D").date
        return int(sum(1 for day in days if self.config.is_excluded(day)))

    # ── prediction ──────────────────────────────────────────────────────────

    def predict_outdoor(self, weather: pd.DataFrame) -> pd.DataFrame:
        """Link 1 applied across a weather frame, past or future alike.

        The forecast path feeds this the OpenMeteo *forecast* rather than the
        archive; nothing else changes, which is the point of calibrating the API
        instead of the sensor.
        """
        hourly = self._weather_frame(weather)
        predicted = pd.DataFrame(index=hourly.index)
        if hourly.empty:
            return predicted

        for column, (model, scaler, feature_names) in self.link1_models.items():
            usable = hourly[feature_names].dropna()
            if usable.empty:
                continue
            name = column.replace(OUTDOOR_PREFIX, PREDICTED_OUTDOOR_PREFIX, 1)
            predicted.loc[usable.index, name] = model.predict(
                scaler.transform(usable.to_numpy(dtype=float))
            )
        return predicted

    def predict_target(
        self,
        frame: pd.DataFrame,
        target: str,
        horizon: int,
        *,
        at: pd.Timestamp,
    ) -> float | None:
        """Predict ``target`` at ``at + horizon`` hours, or ``None``.

        ``frame`` must carry the indoor columns up to ``at`` and the predicted
        outdoor columns *through* ``at + horizon``. ``None`` means some input was
        missing: a prediction built on a defaulted lag would be indistinguishable
        downstream from one built on real readings.
        """
        entry = self.link2_models.get((target, horizon))
        if entry is None:
            return None
        model, scaler, feature_names = entry

        built = feature_row(
            frame,
            at=at,
            horizon_hours=horizon,
            lag_hours=self.config.lag_hours,
            autoregressive=self.link2_autoregressive,
            exogenous=self.link2_exogenous,
            with_day_of_year=True,
        )
        if built is None:
            return None
        X, names = built
        if names != feature_names:
            # The frame no longer produces the columns this model was fitted on
            # — refusing is right; silently reordering would serve nonsense.
            return None
        return float(model.predict(scaler.transform(X))[0])

    @property
    def link2_targets(self) -> list[str]:
        """Targets the chain was fitted for, in the order it was fitted."""
        return list(self.link2_autoregressive)

    # ── persistence ─────────────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> Path:
        """Pickle the trained chain. Training is cheap; a stale model is not."""
        if not self.is_trained():
            raise RuntimeError("No model to save. Train first.")
        path = path or MODEL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as handle:
            pickle.dump(
                {
                    "version": MODEL_VERSION,
                    "reference_key": self.reference_key,
                    "link1_models": self.link1_models,
                    "link2_models": self.link2_models,
                    "climatology": self.climatology,
                    "link2_autoregressive": self.link2_autoregressive,
                    "link2_exogenous": self.link2_exogenous,
                    "link2_sources": self.link2_sources,
                    "stats": self.stats,
                },
                handle,
            )
        return path

    def load(self, path: Path | None = None) -> ClimateModelStats | None:
        """Restore a pickled chain, or ``None`` if absent or from an older era."""
        data = read_artifact(path or MODEL_PATH)
        if data is None:
            return None
        self.reference_key = data["reference_key"]
        self.link1_models = data["link1_models"]
        self.link2_models = data["link2_models"]
        self.climatology = data.get("climatology", {})
        self.link2_autoregressive = data.get("link2_autoregressive", [])
        self.link2_exogenous = data.get("link2_exogenous", [])
        self.link2_sources = data.get("link2_sources", {})
        self.stats = data.get("stats")
        return self.stats


def _error_by(
    actual: np.ndarray, predicted: np.ndarray, times: pd.Series, part: str
) -> pd.DataFrame:
    """Held-out RMSE grouped by a component of the timestamp."""
    stamps = pd.to_datetime(times, utc=True)
    frame = pd.DataFrame(
        {"key": getattr(stamps.dt, part), "actual": actual, "predicted": predicted}
    )
    return (
        frame.groupby("key")
        .apply(lambda g: rmse(g["actual"].to_numpy(), g["predicted"].to_numpy()),
               include_groups=False)
        .rename("rmse")
        .reset_index()
    )


def error_by_month(actual: np.ndarray, predicted: np.ndarray, times: pd.Series) -> pd.DataFrame:
    """RMSE per calendar month — whether the model generalises across seasons.

    The companion to :func:`error_by_hour`. Together they separate two quite
    different ways a single RMSE can mislead: error concentrated in part of the
    day, and error concentrated in part of the year.
    """
    return _error_by(actual, predicted, times, "month").rename(columns={"key": "month"})


def error_by_hour(actual: np.ndarray, predicted: np.ndarray, times: pd.Series) -> pd.DataFrame:
    """RMSE per hour-of-day — the direct test of whether diurnal shape is learnt.

    A model that merely tracks the daily mean scores evenly here; one that has
    actually learnt the day's shape is better at the hours that matter.
    """
    return _error_by(actual, predicted, times, "hour").rename(columns={"key": "hour"})
