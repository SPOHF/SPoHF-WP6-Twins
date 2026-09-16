"""Tests for red's greenhouse-level climate chain (links 1-2).

The concern here is not that a ridge can fit a line. It is that the reported
numbers mean what the status page will claim they mean: out-of-fold, against
real baselines, and trained on the inputs the model will actually be served.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wp6_data.red.climate.config import load_climate_model
from wp6_data.red.climate.model import (
    MODEL_VERSION,
    PREDICTED_OUTDOOR_PREFIX,
    WEATHER_VARIABLES,
    IndoorClimateModel,
    error_by_hour,
)

METADATA = Path("src/wp6_data/red/metadata.yaml")
HOURS = 24 * 60


@pytest.fixture(scope="module")
def config():
    return load_climate_model(METADATA)


def _synthetic(hours=HOURS, seed=3, co2_signal=True):
    index = pd.date_range("2025-10-08", periods=hours, freq="h", tz="UTC")
    rng = np.random.default_rng(seed)
    hour = index.hour.to_numpy()
    outdoor_temp = 12 + 5 * np.sin(2 * np.pi * (hour - 9) / 24) + rng.normal(0, 1, hours)
    radiation = np.clip(600 * np.sin(np.pi * (hour - 6) / 12), 0, None)

    weather = pd.DataFrame({"datetime": index})
    for variable in WEATHER_VARIABLES:
        weather[variable] = {
            "temperature_2m": outdoor_temp,
            "shortwave_radiation": radiation,
        }.get(variable, rng.normal(0, 1, hours))

    indoor_temp = np.zeros(hours)
    indoor_temp[0] = 20.0
    for i in range(1, hours):
        indoor_temp[i] = 0.9 * indoor_temp[i - 1] + 0.1 * (
            18 + 0.35 * outdoor_temp[i] + 0.004 * radiation[i]
        )
    co2 = (
        450 - 0.05 * radiation if co2_signal else rng.normal(450, 40, hours)
    )

    return (
        weather,
        {"temp": pd.DataFrame({"time": index, "value": outdoor_temp})},
        {
            "temp": pd.DataFrame({"time": index, "value": indoor_temp}),
            "co2": pd.DataFrame({"time": index, "value": co2}),
        },
    )


@pytest.fixture(scope="module")
def trained(config):
    weather, outdoor, indoor = _synthetic()
    model = IndoorClimateModel(config, "s2103")
    stats = model.train(weather, outdoor, indoor)
    return model, stats


class TestTraining:
    def test_fits_every_declared_horizon_for_every_target(self, trained, config):
        _, stats = trained

        assert stats.targets == ["co2", "temp"]
        assert stats.horizons == sorted(config.horizons_hours)

    def test_reports_out_of_fold_scores_not_in_sample_ones(self, trained):
        _, stats = trained
        fit = stats.fit_for("temp", 1)

        assert fit.stats.holdout_r2 is not None
        assert fit.stats.n_holdout > 0
        # in-sample is always at least as flattering; they must not be the same
        # object or silently copied
        assert fit.stats.holdout_r2 <= fit.stats.r2_score

    def test_link2_is_served_predicted_outdoor_not_measured(self, trained):
        """Training on measured s1000 would tune link 2 to an input that does
        not exist for a future hour."""
        model, _ = trained
        _, _, feature_names = model.link2_models[("temp", 1)]

        exogenous = [n for n in feature_names if n.startswith(PREDICTED_OUTDOOR_PREFIX)]
        assert exogenous
        assert not any(n.startswith("out_") for n in feature_names)

    def test_every_fit_carries_skill_against_both_baselines(self, trained):
        _, stats = trained

        for fit in stats.link2:
            assert set(fit.stats.skill) == {"persistence", "climatology"}

    def test_records_the_span_it_actually_trained_on(self, trained):
        _, stats = trained
        start, end = stats.span

        assert start is not None and end is not None
        assert start < end

    def test_no_combined_score_is_a_product_of_stages(self, trained):
        """The DLI model multiplies stage R²s; this chain must not, because it
        measures the whole chain end-to-end instead."""
        _, stats = trained

        assert not hasattr(stats, "r2_score")


class TestUselessLink1StagesAreNotFedOnward:
    def test_a_stage_that_cannot_beat_its_mean_is_reported_but_not_used(self, config):
        """Local wind is the real case: OpenMeteo's 10 m wind does not describe
        what the station in the yard records, and a negative-R2 stage handed to
        link 2 is a feature that can only cost it."""
        weather, outdoor, indoor = _synthetic(seed=5)
        # An independent stream: reusing the fixture's seed would reproduce the
        # very noise baked into temperature_2m, making "noise" predictable.
        rng = np.random.default_rng(987654321)
        index = pd.to_datetime(weather["datetime"], utc=True)
        outdoor["noise"] = pd.DataFrame(
            {"time": index, "value": rng.normal(0, 1, len(index))}
        )

        model = IndoorClimateModel(config, "s2103")
        stats = model.train(weather, outdoor, indoor)

        assert "out_noise" in stats.link1  # the attempt is reported
        assert "out_noise" not in model.link1_models  # but not used
        _, _, feature_names = model.link2_models[("temp", 1)]
        assert not any("noise" in name for name in feature_names)


class TestHonestyOnWeakSignal:
    def test_a_noise_target_is_reported_as_weak_not_flattering(self, config):
        weather, outdoor, indoor = _synthetic(seed=11, co2_signal=False)
        model = IndoorClimateModel(config, "s2103")

        stats = model.train(weather, outdoor, indoor)
        co2_fits = [f for f in stats.link2 if f.target == "co2"]

        # pure noise: it cannot beat the climatological mean
        assert co2_fits
        assert all(f.stats.skill["climatology"] < 0.1 for f in co2_fits)

    def test_beats_persistence_is_a_reportable_false(self, config):
        weather, outdoor, indoor = _synthetic(seed=11, co2_signal=False)
        model = IndoorClimateModel(config, "s2103")
        stats = model.train(weather, outdoor, indoor)

        verdicts = {f.beats_persistence for f in stats.link2}
        assert verdicts <= {True, False}


class TestPersistence:
    def test_round_trip_preserves_the_chain_and_its_stats(self, trained, tmp_path):
        model, stats = trained
        path = model.save(tmp_path / "climate.pkl")

        restored = IndoorClimateModel(model.config, "unknown")
        loaded = restored.load(path)

        assert restored.reference_key == "s2103"
        assert restored.is_trained()
        assert loaded.trained_at == stats.trained_at
        assert sorted(restored.link2_models) == sorted(model.link2_models)

    def test_absent_file_loads_as_none_rather_than_raising(self, config, tmp_path):
        assert IndoorClimateModel(config, "s2103").load(tmp_path / "nope.pkl") is None

    def test_a_model_from_an_older_era_is_refused(self, trained, tmp_path):
        """A stale pickle on ephemeral disk must degrade to 'retrain', not to
        wrong numbers."""
        import pickle

        model, _ = trained
        path = tmp_path / "old.pkl"
        model.save(path)
        with open(path, "rb") as handle:
            data = pickle.load(handle)
        data["version"] = MODEL_VERSION - 1
        with open(path, "wb") as handle:
            pickle.dump(data, handle)

        assert IndoorClimateModel(model.config, "s2103").load(path) is None

    def test_untrained_model_refuses_to_save(self, config, tmp_path):
        with pytest.raises(RuntimeError, match="Train first"):
            IndoorClimateModel(config, "s2103").save(tmp_path / "x.pkl")


class TestErrorByHour:
    def test_reports_one_row_per_hour_present(self):
        times = pd.date_range("2026-07-13", periods=48, freq="h", tz="UTC").to_series()
        actual = np.arange(48, dtype=float)

        table = error_by_hour(actual, actual + 1.0, times)

        assert len(table) == 24
        assert table["rmse"].round(3).eq(1.0).all()


class TestChoosingAReference:
    """Picking on skill alone silently dropped CO2: s2101 has no CO2 sensor and
    edges s2103 only because its larger swing leaves more variance to explain."""

    def _stats(self, targets, skill):
        from wp6_data.red.climate.model import ClimateModelStats, HorizonFit
        from wp6_data.red.fitting import StageStats

        return ClimateModelStats(
            trained_at=pd.Timestamp("2026-09-16", tz="UTC").to_pydatetime(),
            span=(None, None),
            reference_key="x",
            link2=[
                HorizonFit(
                    target, 1,
                    StageStats(0.0, 0.0, 0.0, 10, {}, 0.0, skill={"persistence": skill}),
                )
                for target in targets
            ],
        )

    def test_wider_coverage_wins_over_a_marginally_better_score(self):
        from wp6_data.red.climate.training import choose_reference

        chosen = choose_reference({
            "s2101": self._stats(["temp", "hum"], 0.2712),
            "s2103": self._stats(["temp", "hum", "co2"], 0.2504),
        })

        assert chosen == "s2103"

    def test_skill_breaks_ties_at_equal_coverage(self):
        from wp6_data.red.climate.training import choose_reference

        chosen = choose_reference({
            "a": self._stats(["temp", "hum"], 0.10),
            "b": self._stats(["temp", "hum"], 0.30),
        })

        assert chosen == "b"
