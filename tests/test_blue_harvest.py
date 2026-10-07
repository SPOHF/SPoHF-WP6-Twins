"""Harvest page maths: per-plant totals and pick-date means (no database)."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from wp6_data.blue.routes.monitor.harvest import (
    per_plant_totals,
    pick_means,
    prepare_yield,
)


def _raw(rows: list[tuple[str, date, int, float]]) -> pd.DataFrame:
    """Rows as fetch_data returns them: the plant number is the ordinal second."""
    return pd.DataFrame({
        "device": [t for t, *_ in rows],
        "sensor": "yield_per_plant",
        "time": pd.to_datetime([
            datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(seconds=p)
            for _, d, p, _ in rows
        ], utc=True),
        "value": [v for *_, v in rows],
    })


JUL_9, JUL_23 = date(2026, 7, 9), date(2026, 7, 23)
ROWS = [
    ("K", JUL_9, 1, 100.0), ("K", JUL_23, 1, 50.0),
    ("K", JUL_9, 2, 300.0),  # plant 2 not picked on 23 Jul
    ("Std", JUL_9, 1, 80.0),
]


def test_plant_totals_sum_picks_per_plant() -> None:
    totals = per_plant_totals(prepare_yield(_raw(ROWS)))
    k = totals[totals["treatment"] == "K"].set_index("plant")["total"]
    assert k.to_dict() == {1: 150.0, 2: 300.0}


def test_pick_means_count_unpicked_plants_as_zero() -> None:
    means = pick_means(prepare_yield(_raw(ROWS)))
    k = means[means["treatment"] == "K"].set_index("pick")["mean"]
    assert k[JUL_9] == pytest.approx(200.0)
    assert k[JUL_23] == pytest.approx(25.0)  # 50 g over both plants


def test_pick_means_add_up_to_mean_plant_total() -> None:
    yield_df = prepare_yield(_raw(ROWS))
    totals = per_plant_totals(yield_df).groupby("treatment")["total"].mean()
    stacked = pick_means(yield_df).groupby("treatment")["mean"].sum()
    pd.testing.assert_series_equal(stacked, totals, check_names=False)


def test_unknown_devices_are_dropped() -> None:
    yield_df = prepare_yield(_raw([("not-a-treatment", JUL_9, 1, 5.0)]))
    assert yield_df.empty
