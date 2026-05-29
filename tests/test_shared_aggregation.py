"""Tests for wp6_data.shared.aggregation.bucket_and_aggregate.

This is the pandas fallback the legacy MySQL + synthetic grey backends use;
it must mirror the TSDB time_bucket SQL push-down (same shape, same
tz-aware bucket boundaries, a ``count`` for count-weighted client merge).
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from wp6_data.shared.aggregation import (
    BUCKETED_COLUMNS,
    CHART_AGG_FUNCS,
    bucket_and_aggregate,
)

AMS = ZoneInfo("Europe/Amsterdam")
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def _df(rows: list[tuple[str, str, str, float | None]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["device", "sensor", "time", "value"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


class TestShapeAndContract:
    def test_empty_in_empty_out_with_full_columns(self):
        out = bucket_and_aggregate(_df([]), HOUR, "avg", AMS)
        assert list(out.columns) == BUCKETED_COLUMNS
        assert out.empty

    def test_unknown_agg_raises(self):
        with pytest.raises(ValueError, match="Unknown aggregation"):
            bucket_and_aggregate(_df([("d", "s", "2026-01-01T00:00Z", 1.0)]),
                                 HOUR, "median", AMS)

    def test_output_columns_exact(self):
        out = bucket_and_aggregate(
            _df([("d", "s", "2026-01-01T00:10Z", 1.0)]), HOUR, "avg", AMS)
        assert list(out.columns) == BUCKETED_COLUMNS


class TestAggregationFunctions:
    def _two_in_one_hour(self):
        return _df([
            ("d", "s", "2026-06-01T10:05:00Z", 10.0),
            ("d", "s", "2026-06-01T10:55:00Z", 20.0),
        ])

    @pytest.mark.parametrize(
        ("agg", "expected"),
        [("avg", 15.0), ("min", 10.0), ("max", 20.0), ("sum", 30.0)],
    )
    def test_each_function(self, agg, expected):
        out = bucket_and_aggregate(self._two_in_one_hour(), HOUR, agg, AMS)
        assert len(out) == 1
        assert out.iloc[0]["value"] == pytest.approx(expected)
        assert out.iloc[0]["count"] == 2

    @pytest.mark.parametrize("agg", list(CHART_AGG_FUNCS))
    def test_range_band_extremes_are_raw_minmax(self, agg):
        # value_min/value_max are always the raw bucket extremes, regardless of
        # which aggregate the line uses — that's what the chart's range band
        # shades. Fixture holds 10 and 20 in a single hour.
        out = bucket_and_aggregate(self._two_in_one_hour(), HOUR, agg, AMS)
        assert out.iloc[0]["value_min"] == pytest.approx(10.0)
        assert out.iloc[0]["value_max"] == pytest.approx(20.0)

    def test_all_whitelisted_funcs_run(self):
        for agg in CHART_AGG_FUNCS:
            out = bucket_and_aggregate(self._two_in_one_hour(), HOUR, agg, AMS)
            assert out.iloc[0]["count"] == 2


class TestCountAndNulls:
    def test_count_excludes_nulls_and_avg_ignores_them(self):
        df = _df([
            ("d", "s", "2026-06-01T10:05:00Z", 10.0),
            ("d", "s", "2026-06-01T10:25:00Z", None),
            ("d", "s", "2026-06-01T10:45:00Z", 20.0),
        ])
        out = bucket_and_aggregate(df, HOUR, "avg", AMS)
        assert out.iloc[0]["count"] == 2
        assert out.iloc[0]["value"] == pytest.approx(15.0)

    def test_count_weighting_decomposition_holds(self):
        # Two series, unequal counts in the same hour. The helper returns
        # per-series mean + count; the count-weighted recombination must
        # equal the mean over the pooled raw values (avg-of-avgs would not).
        df = _df([
            ("d1", "s", "2026-06-01T10:05:00Z", 10.0),
            ("d1", "s", "2026-06-01T10:15:00Z", 10.0),
            ("d1", "s", "2026-06-01T10:25:00Z", 10.0),  # s1: 3x10  -> mean 10
            ("d2", "s", "2026-06-01T10:35:00Z", 40.0),  # s2: 1x40  -> mean 40
        ])
        out = bucket_and_aggregate(df, HOUR, "avg", AMS).set_index("device")
        num = sum(out.loc[d, "value"] * out.loc[d, "count"] for d in ("d1", "d2"))
        den = sum(out.loc[d, "count"] for d in ("d1", "d2"))
        pooled_mean = (10 + 10 + 10 + 40) / 4
        assert num / den == pytest.approx(pooled_mean)
        assert pooled_mean != pytest.approx((10 + 40) / 2)  # avg-of-avgs is wrong


class TestTimezoneBoundaries:
    def test_day_bucket_is_local_midnight_not_utc(self):
        # 22:30 and 23:30 UTC on 2026-06-01 are both 2026-06-02 (00:30 / 01:30)
        # in Amsterdam summer time (UTC+2) — same *local* day, so one bucket.
        df = _df([
            ("d", "s", "2026-06-01T22:30:00Z", 1.0),
            ("d", "s", "2026-06-01T23:30:00Z", 3.0),
        ])
        out = bucket_and_aggregate(df, DAY, "avg", AMS)
        assert len(out) == 1
        # Bucket start = local midnight of 2026-06-02 = 2026-06-01T22:00Z.
        assert out.iloc[0]["time"] == pd.Timestamp("2026-06-01T22:00:00Z")
        assert out.iloc[0]["value"] == pytest.approx(2.0)

    def test_separate_local_days_split(self):
        df = _df([
            ("d", "s", "2026-06-01T21:00:00Z", 1.0),  # 23:00 local 06-01
            ("d", "s", "2026-06-01T22:30:00Z", 3.0),  # 00:30 local 06-02
        ])
        out = bucket_and_aggregate(df, DAY, "avg", AMS)
        assert len(out) == 2


class TestPerSeriesGrouping:
    def test_devices_and_sensors_stay_separate(self):
        df = _df([
            ("d1", "temp", "2026-06-01T10:05:00Z", 10.0),
            ("d2", "temp", "2026-06-01T10:05:00Z", 20.0),
            ("d1", "hum", "2026-06-01T10:05:00Z", 50.0),
        ])
        out = bucket_and_aggregate(df, HOUR, "avg", AMS)
        assert len(out) == 3
        assert set(zip(out["device"], out["sensor"], strict=True)) == {
            ("d1", "temp"), ("d2", "temp"), ("d1", "hum"),
        }
