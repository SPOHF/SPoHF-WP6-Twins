"""
SPoHF Soil Condition Forecaster
================================
Standalone module — copy this file plus exports/models/*.pkl to the dashboard repo.

Training (notebook):
    from soil_forecaster import train_all_forecasters, build_exog_moisture
    exog = build_exog_moisture(daily_precip_series, daily_temp_series)
    forecasters = train_all_forecasters(treatment_sensors, exog_moisture=exog, freq='H')

Inference (dashboard):
    from soil_forecaster import SoilForecaster, build_exog_moisture
    fc = SoilForecaster.load('models/soilMoisture_K1.pkl')
    preds = fc.predict(recent_hourly)          # {1: 18.1, 2: 18.4, ..., 7: 19.0}
    preds = fc.predict(recent_hourly, exog)    # moisture: pass recent precip exog

Dependencies: numpy, pandas (standard). No sklearn needed.
"""

import pickle
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ── constants ─────────────────────────────────────────────────────────────────

_LAG_DAYS       = [1, 3, 7, 14]
_LAG_HOURS      = [24, 72, 168, 336]   # 1d, 3d, 7d, 14d in hours
_HORIZONS       = [1, 2, 3, 4, 5, 6, 7]           # one day-ahead model per day
_HORIZONS_HOURS = [24, 48, 72, 96, 120, 144, 168]
_ALPHA_GRID     = [0.1, 1.0, 10.0, 100.0]
_GROWING_MONTHS = [3, 4, 5, 6, 7, 8, 9, 10]

# Known-bad sensor/treatment pairs — skipped during training
_EXCLUDED = {
    'soilMoisture':    {'Ca'},   # electrical failure confirmed May–Oct 2025
}


# ── exogenous feature builders ────────────────────────────────────────────────

def build_exog_precip(daily_precip: pd.Series) -> pd.DataFrame:
    """
    Build precipitation-based exogenous features for soil moisture prediction.

    Parameters
    ----------
    daily_precip : pd.Series (DatetimeIndex, daily)
        Daily total precipitation in mm. Missing days treated as 0.

    Returns
    -------
    pd.DataFrame  columns: precip_3d, precip_7d
    """
    idx = pd.date_range(daily_precip.index.min(),
                        daily_precip.index.max(), freq='D')
    p = daily_precip.reindex(idx).fillna(0.0)
    return pd.DataFrame({
        'precip_3d': p.rolling(3, min_periods=1).sum(),
        'precip_7d': p.rolling(7, min_periods=1).sum(),
    }, index=idx)


def build_exog_moisture(daily_precip: pd.Series,
                        daily_temp: pd.Series | None = None) -> pd.DataFrame:
    """
    Build exogenous features for soil moisture prediction.
    Precipitation only, or precipitation + soil temperature as an ET proxy.
    Daily resolution — automatically upsampled to hourly by _build_features
    when the model runs at freq='H'.

    Parameters
    ----------
    daily_precip : pd.Series (DatetimeIndex, daily)
        Daily total precipitation in mm. Missing days treated as 0.
    daily_temp : pd.Series (DatetimeIndex, daily), optional
        Daily median soil temperature (°C). Gaps ≤7 days are interpolated.

    Returns
    -------
    pd.DataFrame  columns: precip_3d, precip_7d [, temp_now, temp_3d, temp_7d]
    """
    idx = pd.date_range(daily_precip.index.min(),
                        daily_precip.index.max(), freq='D')
    p = daily_precip.reindex(idx).fillna(0.0)
    df = pd.DataFrame({
        'precip_3d': p.rolling(3, min_periods=1).sum(),
        'precip_7d': p.rolling(7, min_periods=1).sum(),
    }, index=idx)

    if daily_temp is not None:
        t = daily_temp.reindex(idx).interpolate(limit=7)
        df['temp_now'] = t
        df['temp_3d']  = t.rolling(3, min_periods=1).mean()
        df['temp_7d']  = t.rolling(7, min_periods=1).mean()

    return df


# ── internal feature builder ──────────────────────────────────────────────────

def _build_features(series: pd.Series,
                    exog: pd.DataFrame | None,
                    lag_periods: list,
                    seasonal: bool,
                    freq: str = 'D') -> pd.DataFrame:
    """
    Gap-aware feature matrix from a sensor time series.

    Reindexes to a full DatetimeIndex at the given frequency so that
    winter/off-season gaps become NaN. Lag features that cross a gap
    become NaN and are removed by dropna() — no leakage across breaks.
    Daily exog is forward-filled when freq='H' (cheap daily→hourly upsample).
    """
    s = series.copy().astype(float)
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()

    full_idx = pd.date_range(s.index.min(), s.index.max(), freq=freq)
    s = s.reindex(full_idx)

    cols: dict = {'value': s.values}
    for lag in lag_periods:
        cols[f'lag_{lag}'] = s.shift(lag).values

    if seasonal:
        doy = full_idx.dayofyear
        cols['sin_doy'] = np.sin(2 * np.pi * doy / 365)
        cols['cos_doy'] = np.cos(2 * np.pi * doy / 365)
        if freq == 'H':
            hour = full_idx.hour
            cols['sin_hour'] = np.sin(2 * np.pi * hour / 24)
            cols['cos_hour'] = np.cos(2 * np.pi * hour / 24)

    feat_df = pd.DataFrame(cols, index=full_idx)

    if exog is not None:
        feat_df = pd.concat([feat_df, exog.reindex(full_idx, method='ffill')], axis=1)

    return feat_df.dropna()


# ── ridge regression (pure numpy, no sklearn) ─────────────────────────────────

def _ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    n, p = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    A  = Xb.T @ Xb + alpha * np.eye(p + 1)
    A[0, 0] -= alpha   # intercept not penalised
    return np.linalg.solve(A, Xb.T @ y)


def _ridge_predict(X: np.ndarray, beta: np.ndarray) -> np.ndarray:
    return np.hstack([np.ones((len(X), 1)), X]) @ beta


def _mae(y, yhat):
    return float(np.mean(np.abs(y - yhat)))

def _r2(y, yhat):
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else float('nan')


# ── forecaster class ──────────────────────────────────────────────────────────

class SoilForecaster:
    """
    Ridge regression forecaster for one (sensor_type, treatment) pair.
    Trains a separate direct-forecast model for each day-ahead horizon,
    1 through 7 days out.

    Parameters
    ----------
    sensor_type : str   'soilMoisture' or 'soilTemperature'
    treatment   : str   treatment code, e.g. 'K', 'Org1'
    lag_days    : list  lag windows in days (auto-converted to hours when freq='H')
    seasonal    : bool  include sin/cos day-of-year (+ hour-of-day when freq='H')
    freq        : str   'D' daily resolution (default), 'H' hourly resolution
    """

    def __init__(self,
                 sensor_type: str,
                 treatment: str,
                 lag_days: list = _LAG_DAYS,
                 seasonal: bool = True,
                 freq: str = 'D'):
        self.sensor_type   = sensor_type
        self.treatment     = treatment
        self.lag_days      = lag_days
        self.seasonal      = seasonal
        self.freq          = freq
        self.trained_at: datetime | None = None
        self._models: dict       = {}
        self._feature_cols: list = []
        self.fitted: bool        = False

    # ── training ──────────────────────────────────────────────────────────────

    def fit(self,
            series: pd.Series,
            exog: pd.DataFrame | None = None,
            alpha_grid: list = _ALPHA_GRID,
            val_frac: float = 0.2) -> SoilForecaster:
        """
        Train one ridge model per forecast horizon (day+1 .. day+7).
        Alpha selected by lowest validation MAE (time-based 80/20 split).

        Parameters
        ----------
        series : pd.Series (DatetimeIndex)
            Sensor values at native frequency (daily medians or hourly means).
        exog : pd.DataFrame (optional)
            Exogenous features. For moisture: build_exog_moisture().
            Daily exog is auto-upsampled when freq='H'.
        """
        lag_periods = [lag * 24 for lag in self.lag_days] if self.freq == 'H' else self.lag_days
        horizons    = _HORIZONS_HOURS if self.freq == 'H' else _HORIZONS

        feat_df = _build_features(series, exog, lag_periods, self.seasonal, self.freq)

        feature_cols = [c for c in feat_df.columns if c != 'value']
        self._feature_cols = feature_cols

        s_full = series.reindex(
            pd.date_range(series.index.min(), series.index.max(), freq=self.freq)
        ).astype(float)

        for horizon in horizons:
            target = s_full.shift(-horizon).reindex(feat_df.index)
            mask   = target.notna()
            if mask.sum() < 40:
                print(f'    [{self.sensor_type}/{self.treatment}] h={horizon}: '
                      f'only {mask.sum()} labeled samples — skipped')
                continue

            X = feat_df.loc[mask, feature_cols].values
            y = target[mask].values
            dates = feat_df.index[mask]

            split = max(20, int(len(X) * (1 - val_frac)))
            X_tr, X_va = X[:split], X[split:]
            y_tr, y_va = y[:split], y[split:]
            d_va       = dates[split:]

            best = {'mae': np.inf}
            for alpha in alpha_grid:
                beta   = _ridge_fit(X_tr, y_tr, alpha)
                va_mae = _mae(y_va, _ridge_predict(X_va, beta))
                if va_mae < best['mae']:
                    best = {'mae': va_mae, 'alpha': alpha, 'beta': beta}

            beta    = best['beta']
            yhat_tr = _ridge_predict(X_tr, beta)
            yhat_va = _ridge_predict(X_va, beta)

            # Store key as days regardless of internal freq, for consistent API
            horizon_days = horizon // 24 if self.freq == 'H' else horizon
            self._models[horizon_days] = {
                'beta':       beta,
                'alpha':      best['alpha'],
                'train_mae':  round(_mae(y_tr,  yhat_tr), 4),
                'val_mae':    round(_mae(y_va,  yhat_va), 4),
                'val_r2':     round(_r2(y_va,   yhat_va), 4),
                'n_train':    len(X_tr),
                'n_val':      len(X_va),
                # stored for backtest plots in the notebook only
                '_val_dates':  d_va,
                '_val_actual': y_va,
                '_val_pred':   yhat_va,
            }

        self.fitted = True
        self.trained_at = datetime.now(UTC)
        return self

    # ── inference ─────────────────────────────────────────────────────────────

    def predict(self,
                recent_series: pd.Series,
                exog: pd.DataFrame | None = None) -> dict:
        """
        Predict soil conditions at each forecast horizon.

        Parameters
        ----------
        recent_series : pd.Series (DatetimeIndex)
            Recent sensor values at the model's native frequency.
            Daily models: daily medians. Hourly models: hourly means.
            Needs at least max(lag_days) days of recent data.
        exog : pd.DataFrame (optional)
            Recent exogenous features (required if model was trained with exog).
            For moisture: build with build_exog_moisture(recent_precip).

        Returns
        -------
        dict  e.g. {1: 33.8, 2: 34.0, ..., 7: 34.1}  — keys are always in days
        """
        if not self.fitted:
            raise RuntimeError('Forecaster not fitted. Call fit() first.')

        lag_periods = [lag * 24 for lag in self.lag_days] if self.freq == 'H' else self.lag_days
        feat_df = _build_features(recent_series, exog, lag_periods, self.seasonal, self.freq)

        missing = [c for c in self._feature_cols if c not in feat_df.columns]
        if missing:
            raise ValueError(f'Missing feature columns: {missing}. Pass exog?')

        row = feat_df[self._feature_cols].dropna().tail(1)
        if len(row) == 0:
            raise ValueError(
                f'Not enough recent data. Need at least {max(self.lag_days)} days.'
            )

        return {
            h: round(float(_ridge_predict(row.values, info['beta'])[0]), 4)
            for h, info in self._models.items()
        }

    # ── reporting ─────────────────────────────────────────────────────────────

    def summary(self) -> pd.DataFrame:
        return pd.DataFrame([
            {
                'sensor_type':  self.sensor_type,
                'treatment':    self.treatment,
                'horizon_days': h,
                'alpha':        info['alpha'],
                'train_mae':    info['train_mae'],
                'val_mae':      info['val_mae'],
                'val_r2':       info['val_r2'],
                'n_train':      info['n_train'],
                'n_val':        info['n_val'],
            }
            for h, info in self._models.items()
        ])

    # ── persistence ───────────────────────────────────────────────────────────

    def save(self, path) -> None:
        with open(path, 'wb') as fh:
            pickle.dump(self, fh)

    @classmethod
    def load(cls, path) -> SoilForecaster:
        with open(path, 'rb') as fh:
            return pickle.load(fh)


# ── batch training ────────────────────────────────────────────────────────────

def train_all_forecasters(
    treatment_sensors_df: pd.DataFrame,
    exog_moisture: pd.DataFrame | dict | None = None,
    output_dir: str = 'exports/models',
    min_days: int = 60,
    freq: str = 'D',
) -> dict:
    """
    Train one SoilForecaster per (sensor_type, treatment) on all growing-season
    (Mar-Oct) data available, across every year present in the input.
    Skips known-bad sensor/treatment pairs automatically.

    Off-season (Nov-Feb) gaps between years are left out rather than zero-filled
    or interpolated: `_build_features` reindexes to a full daily index and drops
    rows whose lag features cross a gap, so multi-year data trains correctly
    without leaking across the gap. This also means a partial first season
    (e.g. training mid-summer, before Nov) already has usable data — there is
    no need to wait for a season to "complete" before training.

    Parameters
    ----------
    treatment_sensors_df : pd.DataFrame
        Columns required: timestamp, sensor_type, treatment, value.
    exog_moisture : pd.DataFrame | dict | None
        Global precipitation exog from build_exog_moisture(), OR a dict
        {treatment: DataFrame} for per-treatment exog.
    output_dir : str
        Where to save .pkl files and manifest.csv.
    min_days : int
        Minimum days of data required per treatment to train.
    freq : str
        'D' daily (default), 'H' hourly — resolution for model training.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    df = treatment_sensors_df.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['month'] = df['timestamp'].dt.month
    df['date']  = df['timestamp'].dt.normalize()

    df = df[
        (df['sensor_type'].isin(['soilMoisture', 'soilTemperature'])) &
        (df['month'].isin(_GROWING_MONTHS))
    ]

    min_samples = min_days * 24 if freq == 'H' else min_days

    forecasters:   dict = {}
    manifest_rows: list = []

    for sensor_type in ['soilMoisture', 'soilTemperature']:
        excluded = _EXCLUDED.get(sensor_type, set())
        sub = df[df['sensor_type'] == sensor_type]

        for treatment in sorted(sub['treatment'].unique()):
            if treatment in excluded:
                print(f'  skip  {sensor_type}/{treatment:<6}  known sensor issue')
                continue

            if freq == 'H':
                series = (
                    sub[sub['treatment'] == treatment]
                    .set_index('timestamp')['value']
                    .resample('h')
                    .mean()
                    .dropna()
                )
            else:
                series = (
                    sub[sub['treatment'] == treatment]
                    .groupby('date')['value']
                    .median()
                    .pipe(lambda s: s.set_axis(pd.to_datetime(s.index)))
                )

            if len(series) < min_samples:
                unit = 'hours' if freq == 'H' else 'days'
                print(f'  skip  {sensor_type}/{treatment:<6}  '
                      f'only {len(series)} {unit} (need {min_samples})')
                continue

            if isinstance(exog_moisture, dict):
                exog = exog_moisture.get(treatment) if sensor_type == 'soilMoisture' else None
            else:
                exog = exog_moisture if sensor_type == 'soilMoisture' else None

            print(f'  train {sensor_type}/{treatment}')
            fc = SoilForecaster(sensor_type, treatment, freq=freq)
            fc.fit(series, exog=exog)

            fname = f'{sensor_type}_{treatment}.pkl'
            fc.save(Path(output_dir) / fname)
            forecasters[(sensor_type, treatment)] = fc

            for _, row in fc.summary().iterrows():
                print(f'        h={int(row.horizon_days):>2}d  '
                      f'val_MAE={row.val_mae:.3f}  '
                      f'val_R2={row.val_r2:.3f}  '
                      f'alpha={row.alpha}')
                manifest_rows.append({
                    'file':         fname,
                    'sensor_type':  sensor_type,
                    'treatment':    treatment,
                    'horizon_days': int(row.horizon_days),
                    'val_mae':      row.val_mae,
                    'val_r2':       row.val_r2,
                    'alpha':        row.alpha,
                    'freq':         freq,
                })

    pd.DataFrame(manifest_rows).to_csv(
        Path(output_dir) / 'manifest.csv', index=False
    )
    print(f'\n  {len(forecasters)} forecasters saved to {output_dir}/')
    return forecasters
