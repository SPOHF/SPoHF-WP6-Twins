"""Days the PAR sensor did not report must not score the model.

`calculate_daily_dli` returns a row for a day of flat zeros — red's PAR sensors
read zero for six weeks in 2026 — and the performance page used to treat a zero
actual as a real measurement. Its percentage error was written as ``0.0`` when
the actual was not positive, so an outage entered the average as a *perfect*
day and pulled the reported error down, while the absolute error and bias took
the whole prediction as a miss. Both directions were wrong at once.
"""

import json
import re
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from wp6_data.red.dli.constants import MIN_INDOOR_PAR
from wp6_data.red.dli.model import TwoStageLightModel
from wp6_data.red.routes.dli import performance as perf
from wp6_data.red.routes.dli.performance import _runs
from wp6_data.shared.templates.config import configure_dashboard
from wp6_data.shared.weather import DailyForecast, HourlyWeather

END = date.today() - timedelta(days=1)
START = END - timedelta(days=4)
DAYS = [START + timedelta(days=i) for i in range(5)]
DEAD_DAYS = set(DAYS[1:3])

LIT_PAR = 400.0
DAYLIGHT_HOURS = range(6, 19)


class _Stage:
    """A fitted stage that always predicts the same value."""

    def __init__(self, value: float):
        self.value = value

    def predict(self, _x):
        return [self.value]


def _model() -> TwoStageLightModel:
    model = TwoStageLightModel()
    model.stage1_features = ["shortwave_sum"]
    model.stage2_features = ["lux_hours"]
    model.stage1_model = _Stage(5000.0)
    model.stage2_model = _Stage(100_000.0)
    model.stage1_scaler = model.stage2_scaler = None
    model.stage1_poly = model.stage2_poly = None
    return model


class _Readings:
    """The PAR feed, with `DEAD_DAYS` reading a flat zero all day."""

    def is_connected(self) -> bool:
        return True

    async def get_par_readings(self, device_ids, start, end):
        rows = []
        for device in device_ids:
            for day in DAYS:
                dead = day in DEAD_DAYS and device == perf.NATURAL_LIGHT_SENSOR
                for hour in range(24):
                    lit = hour in DAYLIGHT_HOURS and not dead
                    rows.append({
                        "device": device, "sensor": "par",
                        "time": datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
                        "value": LIT_PAR if lit else 0.0,
                    })
        return pd.DataFrame(rows)


def _forecast(day: date) -> DailyForecast:
    return DailyForecast(date=day, hourly=[
        HourlyWeather(
            datetime=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
            solar_radiation=20.0, cloud_cover=40.0, temperature=12.0,
            direct_radiation=12.0, diffuse_radiation=8.0,
        )
        for hour in range(24)
    ])


@pytest.fixture()
def page(monkeypatch):
    """Render the natural-light comparison over `DAYS`, sensors stubbed."""
    configure_dashboard("red", title="SPoHF Red")

    async def _fetch(_client, _start, _end):
        return [_forecast(day) for day in DAYS]

    monkeypatch.setattr(perf, "dli_data", _Readings())
    monkeypatch.setattr(perf, "get_model", _model)
    monkeypatch.setattr(perf, "fetch_weather_for_range", _fetch)
    monkeypatch.setattr(perf.deps, "get_weather_client", lambda: object())

    async def _render(mode="natural"):
        return await perf.dli_performance(start=START, end=END, mode=mode)

    return _render


def _stat_tiles(html: str) -> dict[str, str]:
    """Map each stat tile's caption to its value."""
    flat = html.replace("\n", "")
    return {
        label: value
        for value, label in re.findall(
            r'stat-value[^"]*">([^<]+)</div><small>([^<]+)</small>', flat
        )
    }


class TestNoDataDaysAreNotScored:
    async def test_the_gate_is_the_training_gate(self):
        """Reusing it is what stops the two drifting apart."""
        from wp6_data.red.dli.calculator import par_sum_to_dli

        assert par_sum_to_dli(MIN_INDOOR_PAR) == perf.NO_DATA_DLI

    async def test_dead_days_are_reported_as_excluded(self, page):
        html = await page()

        assert _stat_tiles(html)["Days Not Scored"] == str(len(DEAD_DAYS))

    async def test_dead_days_are_not_shown_as_a_perfect_day(self, page):
        """The old page printed `+0.0%` for a sensor that was switched off."""
        html = await page()

        assert html.count(">no data<") == len(DEAD_DAYS)

    async def test_the_table_still_lists_every_day(self, page):
        """Excluded from the metrics, not hidden — an outage must stay visible."""
        html = await page()

        assert f"{len(DAYS)} days, {len(DAYS) - len(DEAD_DAYS)} scored" in html

    async def test_the_error_is_averaged_over_scored_days_only(self, page):
        """A zero-actual day entering at 0% error drags the mean down."""
        html = await page()
        mape = float(_stat_tiles(html)["Avg. Error"].rstrip("%"))

        # Every scored day here carries the same error, so the mean over the
        # scored days is that error; averaging the dead days in at 0% would
        # scale it by scored/total.
        diluted = mape * (len(DAYS) - len(DEAD_DAYS)) / len(DAYS)
        assert mape > diluted


def _chart(html: str) -> tuple[list[dict], dict]:
    """The comparison chart's traces and layout, as Plotly received them."""
    blob = re.search(
        r'Plotly\.newPlot\(\s*"[^"]+",\s*(\[.*?\]),\s*(\{.*?\}),\s*\{"responsive"',
        html, re.S,
    )
    return json.loads(blob.group(1)), json.loads(blob.group(2))


class TestOutagesAreDrawnAsAGapNotAZero:
    """Plotting 0.0 claims the sensor measured no light. It measured nothing."""

    async def test_the_actual_line_breaks_over_an_outage(self, page):
        traces, _ = _chart(await page())
        actual = next(t for t in traces if t["name"].startswith("Actual"))

        assert sum(1 for v in actual["y"] if v is None) == len(DEAD_DAYS)

    async def test_no_day_is_drawn_as_zero(self, page):
        traces, _ = _chart(await page())
        actual = next(t for t in traces if t["name"].startswith("Actual"))

        assert not [v for v in actual["y"] if v == 0]

    async def test_the_band_breaks_with_the_line(self, page):
        """`toself` over a gap would span it; `tonexty` stops at the None."""
        traces, _ = _chart(await page())
        actual = next(t for t in traces if t["name"].startswith("Actual"))

        assert actual["fill"] == "tonexty"

    async def test_the_outage_is_shaded_as_one_span(self, page):
        _, layout = _chart(await page())

        assert len(layout.get("shapes", [])) == 1


class TestRuns:
    def test_consecutive_days_collapse_into_one_span(self):
        """An outage is one period, not N separate marks."""
        days = [date(2026, 5, 28) + timedelta(days=i) for i in range(5)]

        assert _runs(days) == [(days[0], days[-1])]

    def test_a_break_starts_a_new_span(self):
        a, b = date(2026, 5, 28), date(2026, 6, 10)

        assert _runs([a, a + timedelta(days=1), b]) == [(a, a + timedelta(days=1)), (b, b)]

    def test_no_days_means_no_spans(self):
        assert _runs([]) == []
