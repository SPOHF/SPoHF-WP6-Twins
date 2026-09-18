"""The DLI model reports what it can reproduce out of sample.

Until this landed, every number on /dli/model was in-sample, and the headline
was `stage1_R² × stage2_R²` — a product that assumed an error propagation
nobody had measured, and credited stage 2 with an input it never receives.
Stage 2 is fitted on the lux the station recorded; serving has only stage 1's
estimate of it.
"""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from wp6_data.red.dli.model import ModelStats, _previous_day, _score_stage
from wp6_data.red.fitting import StageStats

DAY = date(2026, 3, 1)


def _stage(**overrides) -> StageStats:
    base = {
        "r2_score": 0.9, "rmse": 1.0, "mae": 1.0, "n_samples": 10,
        "coefficients": {}, "intercept": 0.0,
    }
    return StageStats(**{**base, **overrides})


class TestPreviousDay:
    def test_it_is_yesterday_not_the_previous_row(self):
        """Quality gates drop days, so the previous row is often not yesterday."""
        days = np.array([DAY, DAY + timedelta(days=1), DAY + timedelta(days=3)])
        values = np.array([10.0, 20.0, 30.0])

        previous = _previous_day(days, values)

        assert np.isnan(previous[0]), "the first day has no predecessor"
        assert previous[1] == 10.0
        assert np.isnan(previous[2]), "day 3's predecessor (day 2) was dropped"


class TestScoreStage:
    def _run(self, predicted):
        days = np.array([DAY + timedelta(days=i) for i in range(6)])
        actual = np.array([10.0, 14.0, 9.0, 16.0, 11.0, 15.0])
        stats = _stage()
        _score_stage(stats, days, actual, np.asarray(predicted), np.ones(6, dtype=bool))
        return stats, actual

    def test_a_perfect_model_takes_all_the_baselines_error(self):
        stats, actual = self._run([10.0, 14.0, 9.0, 16.0, 11.0, 15.0])

        assert stats.holdout_r2 == pytest.approx(1.0)
        assert stats.skill["persistence"] == pytest.approx(1.0)
        assert stats.skill["climatology"] == pytest.approx(1.0)

    def test_days_without_a_predecessor_are_not_scored(self):
        """Model and baseline must be judged on identical rows to compare."""
        stats, actual = self._run([10.0, 14.0, 9.0, 16.0, 11.0, 15.0])

        assert stats.n_holdout == len(actual) - 1

    def test_both_baselines_are_reported(self):
        stats, _ = self._run([11.0, 13.0, 10.0, 15.0, 12.0, 14.0])

        assert set(stats.skill) == {"persistence", "climatology"}

    def test_a_stage_worse_than_its_baseline_says_so(self):
        """Negative skill is a real outcome, not a bug — stage 1 posts one."""
        stats, _ = self._run([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

        assert stats.skill["persistence"] < 0


class TestHeadlineNumber:
    def _stats(self, chain):
        return ModelStats(
            stage1=_stage(r2_score=0.5846),
            stage2=_stage(r2_score=0.9825),
            training_date=datetime.now(UTC),
            date_range=(DAY, DAY + timedelta(days=30)),
            chain=chain,
        )

    def test_it_is_the_measured_chain_not_the_product(self):
        stats = self._stats(_stage(holdout_r2=0.6549))

        assert stats.r2_score == 0.6549
        assert stats.r2_score != pytest.approx(0.5846 * 0.9825, abs=1e-4)

    def test_it_falls_back_to_the_product_when_the_chain_is_unscored(self):
        """An older artifact still renders rather than crashing the page."""
        stats = self._stats(None)

        assert stats.r2_score == pytest.approx(0.5846 * 0.9825, abs=1e-4)
