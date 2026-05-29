"""Tests for weekly coverage builder and status grid renderer."""

from datetime import date, timedelta

from wp6_data.shared.charts import build_weekly_coverage, render_coverage_grid


def _days(device: str, sensor: str, start: date, count: int) -> list[dict]:
    """Helper: generate contiguous daily records."""
    return [
        {"device": device, "sensor": sensor, "day": start + timedelta(days=i)}
        for i in range(count)
    ]


class TestBuildWeeklyCoverage:
    def test_full_week_is_good(self):
        # 7 consecutive days in one week
        records = _days("d1", "temp", date(2024, 4, 1), 7)
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 4, 7))
        assert len(df) == 1
        assert df.iloc[0]["status"] == "good"
        assert df.iloc[0]["days_with_data"] == 7

    def test_six_days_is_partial(self):
        records = _days("d1", "temp", date(2024, 4, 1), 6)
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 4, 7))
        assert df.iloc[0]["status"] == "partial"

    def test_three_days_is_partial(self):
        records = _days("d1", "temp", date(2024, 4, 1), 3)
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 4, 7))
        assert df.iloc[0]["status"] == "partial"

    def test_two_days_is_none(self):
        records = _days("d1", "temp", date(2024, 4, 1), 2)
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 4, 7))
        assert df.iloc[0]["status"] == "none"
        assert df.iloc[0]["days_with_data"] == 2

    def test_no_data_week_is_none(self):
        # Data in week 1, nothing in week 2
        records = _days("d1", "temp", date(2024, 4, 1), 7)
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 4, 14))
        week2 = df[df["week_start"] == date(2024, 4, 8)]
        assert len(week2) == 1
        assert week2.iloc[0]["status"] == "none"
        assert week2.iloc[0]["days_with_data"] == 0

    def test_empty_records(self):
        df = build_weekly_coverage([])
        assert df.empty
        assert "status" in df.columns

    def test_multiple_devices_separate_rows(self):
        records = (
            _days("d1", "temp", date(2024, 4, 1), 7)
            + _days("d2", "temp", date(2024, 4, 1), 3)
        )
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 4, 7))
        assert len(df) == 2
        d1 = df[df["device"] == "d1"].iloc[0]
        d2 = df[df["device"] == "d2"].iloc[0]
        assert d1["status"] == "good"
        assert d2["status"] == "partial"

    def test_multiple_sensors(self):
        records = [
            {"device": "d1", "sensor": "temp", "day": date(2024, 4, 1)},
            {"device": "d1", "sensor": "humidity", "day": date(2024, 4, 1)},
        ]
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 4, 7))
        assert set(df["sensor"]) == {"temp", "humidity"}

    def test_spans_full_project_range(self):
        records = [{"device": "d1", "sensor": "temp", "day": date(2024, 4, 1)}]
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 5, 5))
        # 5 weeks: Apr 1, Apr 8, Apr 15, Apr 22, Apr 29
        assert df["week_start"].nunique() == 5

    def test_default_project_start(self):
        records = [{"device": "d1", "sensor": "temp", "day": date(2024, 3, 5)}]
        df = build_weekly_coverage(records, project_end=date(2024, 3, 7))
        # Start derived from earliest record (2024-03-05 Tue), snapped to Monday 2024-03-04
        assert df.iloc[0]["week_start"] == date(2024, 3, 4)


class TestPresenceMode:
    """Manual data uses a binary presence scale: any measurement that week is
    green, none is grey — no yellow/red 'fault' states."""

    def test_one_day_is_good(self):
        records = _days("d1", "shoot_length", date(2024, 4, 1), 1)
        df = build_weekly_coverage(
            records, date(2024, 4, 1), date(2024, 4, 7), mode="presence"
        )
        assert df.iloc[0]["status"] == "good"
        assert df.iloc[0]["days_with_data"] == 1

    def test_empty_week_is_none(self):
        records = _days("d1", "shoot_length", date(2024, 4, 1), 1)
        df = build_weekly_coverage(
            records, date(2024, 4, 1), date(2024, 4, 14), mode="presence"
        )
        week2 = df[df["week_start"] == date(2024, 4, 8)]
        assert week2.iloc[0]["status"] == "none"

    def test_never_partial(self):
        # 3 days would be "partial" in daily mode; presence mode only knows good/none.
        records = _days("d1", "shoot_length", date(2024, 4, 1), 3)
        df = build_weekly_coverage(
            records, date(2024, 4, 1), date(2024, 4, 7), mode="presence"
        )
        assert set(df["status"]) <= {"good", "none"}
        assert df.iloc[0]["status"] == "good"

    def test_grid_uses_grey_not_red(self):
        records = _days("d1", "shoot_length", date(2024, 4, 1), 1)
        df = build_weekly_coverage(
            records, date(2024, 4, 1), date(2024, 4, 14), mode="presence"
        )
        html = render_coverage_grid(df, mode="presence")
        assert "#9ca3af" in html  # grey for an unmeasured week
        assert "#ef4444" not in html  # no red faults for manual data


class TestRenderCoverageGrid:
    def test_returns_html_string(self):
        records = _days("d1", "temp", date(2024, 4, 1), 14)
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 4, 14))
        html = render_coverage_grid(df)
        assert isinstance(html, str)
        assert "uptime-grid" in html

    def test_contains_blocks(self):
        records = _days("d1", "temp", date(2024, 4, 1), 7)
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 4, 7))
        html = render_coverage_grid(df)
        assert "uptime-block" in html
        assert "#22c55e" in html  # green for good

    def test_shows_label(self):
        records = _days("d1", "temp", date(2024, 4, 1), 7)
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 4, 7))
        html = render_coverage_grid(df)
        assert "d1" in html
        assert "temp" in html

    def test_empty_df(self):
        import pandas as pd

        df = pd.DataFrame(
            columns=["device", "sensor", "week_start", "days_with_data", "status"]
        )
        html = render_coverage_grid(df)
        assert "No coverage data" in html

    def test_red_for_no_data(self):
        # One week with data, one without
        records = _days("d1", "temp", date(2024, 4, 1), 7)
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 4, 14))
        html = render_coverage_grid(df)
        assert "#ef4444" in html  # red for no-data week

    def test_yellow_for_partial(self):
        records = _days("d1", "temp", date(2024, 4, 1), 3)
        df = build_weekly_coverage(records, date(2024, 4, 1), date(2024, 4, 7))
        html = render_coverage_grid(df)
        assert "#eab308" in html  # yellow for partial
