"""Boot-time soil-forecast model bootstrap (mirrors red's DLI retrain-on-boot).

Models live on ephemeral storage, so `bootstrap_models_if_missing` retrains on
startup only when needed and must never crash the app. These tests pin that
decision logic (skip/train/no-data/locked/error) without doing a real fit.
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pandas as pd

from wp6_data.blue.routes.monitor import soil_forecast


class _FakeProvider:
    """Minimal SensorDataProvider stub that records fetch_data calls."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df
        self.calls = 0

    async def fetch_data(self, sensor_tags=None, **kwargs) -> pd.DataFrame:  # noqa: ANN001, ANN003
        self.calls += 1
        return self._df


def _readings() -> pd.DataFrame:
    """One row shaped like a provider fetch (columns bootstrap forwards on)."""
    return pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-06-01"]),
            "device": ["d1"],
            "sensor": [soil_forecast._FORECAST_SENSORS[0]],
            "value": [12.3],
        },
    )


async def test_bootstrap_skips_when_models_present(monkeypatch) -> None:
    monkeypatch.setattr(soil_forecast, "_scan_models", lambda: [Path("m.pkl")])
    train = AsyncMock()
    monkeypatch.setattr(soil_forecast, "_train_from_readings", train)
    provider = _FakeProvider(_readings())

    await soil_forecast.bootstrap_models_if_missing(provider)

    assert provider.calls == 0  # never touches the DB when models already exist
    train.assert_not_awaited()


async def test_bootstrap_trains_when_absent(monkeypatch) -> None:
    monkeypatch.setattr(soil_forecast, "_scan_models", lambda: [])
    train = AsyncMock(return_value={("soilMoisture", "Std"): object()})
    monkeypatch.setattr(soil_forecast, "_train_from_readings", train)
    provider = _FakeProvider(_readings())

    await soil_forecast.bootstrap_models_if_missing(provider)

    assert provider.calls == 1
    train.assert_awaited_once()


async def test_bootstrap_skips_when_no_data(monkeypatch) -> None:
    monkeypatch.setattr(soil_forecast, "_scan_models", lambda: [])
    train = AsyncMock()
    monkeypatch.setattr(soil_forecast, "_train_from_readings", train)
    provider = _FakeProvider(pd.DataFrame())  # empty fetch

    await soil_forecast.bootstrap_models_if_missing(provider)

    assert provider.calls == 1
    train.assert_not_awaited()  # no data → nothing to fit


async def test_bootstrap_noop_when_lock_held(monkeypatch) -> None:
    monkeypatch.setattr(soil_forecast, "_scan_models", lambda: [])
    train = AsyncMock()
    monkeypatch.setattr(soil_forecast, "_train_from_readings", train)
    provider = _FakeProvider(_readings())

    await soil_forecast._training_lock.acquire()
    try:
        await soil_forecast.bootstrap_models_if_missing(provider)
    finally:
        soil_forecast._training_lock.release()

    assert provider.calls == 0  # a manual retrain is already running
    train.assert_not_awaited()


async def test_bootstrap_swallows_training_error(monkeypatch) -> None:
    monkeypatch.setattr(soil_forecast, "_scan_models", lambda: [])
    train = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(soil_forecast, "_train_from_readings", train)
    provider = _FakeProvider(_readings())

    # Must not raise — a boot-training failure must never crash startup.
    await soil_forecast.bootstrap_models_if_missing(provider)

    train.assert_awaited_once()
    assert not soil_forecast._training_lock.locked()  # lock released on error
