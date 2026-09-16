"""Tests for red's shared fitting and scoring helpers.

The point of these is the scoring, not the fitting: a leaking split or a
flattering baseline is exactly the failure that looks like success.
"""

import numpy as np
import pandas as pd
import pytest

from wp6_data.red.fitting import (
    DEFAULT_CV_FOLDS,
    climatology_baseline,
    climatology_table,
    fit_ridge,
    gradient_error,
    mae,
    persistence_baseline,
    reference_baseline,
    rmse,
    score_holdout,
    skill_score,
    time_blocked_splits,
)


class TestTimeBlockedSplits:
    """The leak guard. Hourly rows an hour apart are near-duplicates."""

    def test_no_day_appears_on_both_sides_of_a_fold(self):
        days = np.repeat(pd.date_range("2026-01-01", periods=20, freq="D").date, 24)

        folds = list(time_blocked_splits(days, DEFAULT_CV_FOLDS))

        assert folds, "expected folds for 20 days"
        for train_idx, test_idx in folds:
            train_days = set(days[train_idx])
            test_days = set(days[test_idx])
            assert not (train_days & test_days)

    def test_held_out_days_are_contiguous(self):
        days = np.repeat(pd.date_range("2026-01-01", periods=20, freq="D").date, 4)

        for _, test_idx in time_blocked_splits(days, DEFAULT_CV_FOLDS):
            held = sorted({d.toordinal() for d in days[test_idx]})
            assert held == list(range(held[0], held[-1] + 1))

    def test_every_row_is_held_out_exactly_once(self):
        days = np.repeat(pd.date_range("2026-01-01", periods=12, freq="D").date, 2)

        held = [i for _, test_idx in time_blocked_splits(days, 4) for i in test_idx]

        assert sorted(held) == list(range(len(days)))

    def test_too_few_days_yields_nothing_rather_than_a_degenerate_fold(self):
        days = np.array([pd.Timestamp("2026-01-01").date()] * 50)

        assert list(time_blocked_splits(days, DEFAULT_CV_FOLDS)) == []


class TestSkillScore:
    def test_zero_when_model_matches_baseline(self):
        assert skill_score(2.0, 2.0) == 0.0

    def test_negative_when_worse_than_baseline(self):
        """A real, reportable outcome — not something to clamp away."""
        assert skill_score(4.0, 2.0) == pytest.approx(-1.0)

    def test_one_when_model_is_perfect(self):
        assert skill_score(0.0, 2.0) == pytest.approx(1.0)

    def test_perfect_baseline_leaves_nothing_to_improve(self):
        assert skill_score(1.0, 0.0) == 0.0


class TestBaselines:
    def test_persistence_carries_the_current_value_forward(self):
        now = [20.0, 21.0, 22.5]

        assert persistence_baseline(now).tolist() == now

    def test_reference_baseline_ignores_the_gradient(self):
        reference = [19.0, 19.5]

        assert reference_baseline(reference).tolist() == reference

    def test_climatology_averages_per_month_and_hour(self):
        times = pd.to_datetime(
            ["2026-01-01T06:00Z", "2026-01-02T06:00Z", "2026-01-01T18:00Z"]
        ).to_series()

        table = climatology_table(times, [10.0, 20.0, 5.0])

        assert table[(1, 6)] == pytest.approx(15.0)
        assert table[(1, 18)] == pytest.approx(5.0)

    def test_unseen_month_hour_falls_back_rather_than_reading_zero(self):
        """A summer-trained model asked about winter must not silently get 0.0."""
        table = climatology_table(
            pd.to_datetime(["2026-07-01T12:00Z"]).to_series(), [25.0]
        )

        applied = climatology_baseline(
            table, pd.to_datetime(["2026-01-15T03:00Z"]).to_series(), fallback=18.0
        )

        assert applied.tolist() == [18.0]


class TestGradientError:
    """A model can be right about every height's mean and still draw the
    profile upside down. That is the failure this must catch."""

    def _frames(self, predicted_profile):
        times = pd.date_range("2026-07-13", periods=4, freq="h", tz="UTC")
        actual = pd.DataFrame({1: 24.0, 3: 23.0, 5: 22.0}, index=times)
        predicted = pd.DataFrame(predicted_profile, index=times)
        return predicted, actual

    def test_uniform_offset_scores_perfectly(self):
        """Being two degrees warm everywhere leaves the profile shape intact."""
        predicted, actual = self._frames({1: 26.0, 3: 25.0, 5: 24.0})

        score = gradient_error(predicted, actual, base_height=1)

        assert score.rmse == pytest.approx(0.0)
        assert score.sign_agreement == pytest.approx(1.0)

    def test_inverted_profile_scores_badly(self):
        predicted, actual = self._frames({1: 22.0, 3: 23.0, 5: 24.0})

        score = gradient_error(predicted, actual, base_height=1)

        assert score.rmse > 1.0
        assert score.sign_agreement == pytest.approx(0.0)

    def test_correct_means_but_flat_profile_is_penalised(self):
        """The per-height means are right on average; the gradient is gone."""
        predicted, actual = self._frames({1: 23.0, 3: 23.0, 5: 23.0})

        score = gradient_error(predicted, actual, base_height=1)

        assert score.rmse > 0.0

    def test_missing_height_is_dropped_not_read_as_zero_gradient(self):
        predicted, actual = self._frames({1: 24.0, 3: 23.0, 5: 22.0})
        predicted.loc[predicted.index[0], 3] = np.nan

        score = gradient_error(predicted, actual, base_height=1)

        assert score.n == actual.shape[0] * 2 - 1

    def test_absent_base_height_reports_nothing_rather_than_guessing(self):
        predicted, actual = self._frames({1: 24.0, 3: 23.0, 5: 22.0})

        score = gradient_error(predicted.drop(columns=[1]), actual, base_height=1)

        assert score.n == 0
        assert np.isnan(score.rmse)
        assert np.isnan(score.sign_agreement)


class TestFitRidge:
    def test_recovers_a_linear_relationship(self):
        rng = np.random.default_rng(0)
        X = rng.normal(size=(200, 2))
        y = 3.0 * X[:, 0] - 2.0 * X[:, 1] + 10.0

        model, scaler, stats = fit_ridge(X, y, ["a", "b"])

        assert stats.r2_score > 0.99
        assert set(stats.coefficients) == {"a", "b"}
        assert stats.n_samples == len(y)
        assert model.predict(scaler.transform(X)).shape == y.shape

    def test_holdout_measures_are_absent_until_scored(self):
        X = np.arange(40, dtype=float).reshape(-1, 1)

        _, _, stats = fit_ridge(X, X.ravel() * 2, ["x"])

        assert stats.holdout_r2 is None
        assert stats.n_holdout == 0
        assert stats.skill == {}

    def test_day_blocked_folds_are_accepted_for_lagged_data(self):
        rng = np.random.default_rng(1)
        days = np.repeat(pd.date_range("2026-01-01", periods=15, freq="D").date, 8)
        X = rng.normal(size=(len(days), 2))
        y = X[:, 0] * 1.5

        _, _, stats = fit_ridge(X, y, ["a", "b"], days=days)

        assert stats.n_samples == len(days)

    def test_score_holdout_records_skill_against_each_baseline(self):
        X = np.arange(40, dtype=float).reshape(-1, 1)
        _, _, stats = fit_ridge(X, X.ravel() * 2, ["x"])
        actual = np.array([10.0, 12.0, 14.0])
        predicted = np.array([10.5, 12.5, 13.5])

        score_holdout(
            stats, actual, predicted, {"persistence": np.array([8.0, 8.0, 8.0])}
        )

        assert stats.n_holdout == len(actual)
        assert stats.holdout_rmse == pytest.approx(rmse(actual, predicted))
        assert stats.holdout_mae == pytest.approx(mae(actual, predicted))
        assert stats.skill["persistence"] > 0
