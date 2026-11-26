"""The /greenhouse microclimate mode's data: the wires laid out as one cross-section.

What is pinned: the layout follows the configured row (not the sorted wire ids),
steps line up with the page's timeline, a missing reading stays missing, VPD is
formed per reading before averaging, and the colour range never exaggerates a
spread the twin does not count as notable.
"""

import os

os.environ.setdefault("WP6_OIDC_DEV_AUTH", "true")
os.environ.setdefault("WP6_OIDC_CLIENT_SECRET", "dev")
os.environ.setdefault("WP6_OIDC_SESSION_SECRET", "dev-session-secret-dev-session-secret")
os.environ.setdefault("WP6_RED_TSDB_URL", "postgresql://wp6_red:wp6dev@localhost:5433/wp6_red")

import dataclasses
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from wp6_data.red import deps
from wp6_data.red.db import WIRE_SENSOR_HEIGHTS, wire_device_id, wire_readings_frame
from wp6_data.red.greenhouse import state as S
from wp6_data.red.greenhouse.config import Microclimate, load_greenhouse
from wp6_data.red.greenhouse.microclimate import build_microclimate_day
from wp6_data.red.multi_height.config import load_uniformity_config
from wp6_data.red.risk.metrics import vpd_series
from wp6_data.red.wires import invalidate_wire_cache
from wp6_data.shared import i18n

RED = Path(__file__).parents[1] / "src/wp6_data/red"
MC = load_greenhouse(RED / "metadata.yaml").microclimate
SPANS = load_uniformity_config(RED / "metadata.yaml").notable_spread
TZ = "Europe/Amsterdam"
DAY = date(2026, 8, 12)
ROW = [w.id for w in MC.wires]
INSTALLED = sorted(ROW)
STEPS_PER_DAY = int(pd.Timedelta(days=1) / pd.Timedelta(S.STEP))
STEP = pd.Timedelta(S.STEP)


@pytest.fixture(autouse=True)
def _catalogues():
    i18n.load(i18n.SHARED_DIR, RED / "i18n")
    yield


def _at(hh: int, mm: int = 0) -> pd.Timestamp:
    return pd.Timestamp(DAY, tz=TZ) + pd.Timedelta(hours=hh, minutes=mm)


def _frame(rows) -> pd.DataFrame:
    """Tidy wire readings from ``(wire, height, measurement, local time, value)``."""
    return wire_readings_frame([
        {
            "device": wire_device_id(wire, h),
            "height": h,
            "measurement": m,
            "time": when.tz_convert("UTC"),
            "value": v,
        }
        for wire, h, m, when, v in rows
    ])


def _build(df, installed=INSTALLED, mc=MC):
    return build_microclimate_day(df, mc, installed, DAY, TZ, SPANS)


def _step(t: str, day: dict) -> int:
    return day["steps"].index(t)


def test_columns_follow_the_configured_row_not_the_sorted_ids():
    rows = [
        (w, h, "temp", _at(12), 20.0 + i) for i, w in enumerate(ROW) for h in WIRE_SENSOR_HEIGHTS
    ]
    day = _build(_frame(rows))
    assert [w["id"] for w in day["wires"]] == ROW
    noon = day["metrics"]["temp"]["values"][_step("12:00", day)]
    assert [col[0] for col in noon] == [20.0 + i for i in range(len(ROW))]
    assert [h["h"] for h in day["heights"]] == sorted(WIRE_SENSOR_HEIGHTS)
    assert [w["at_m"] for w in day["wires"]] == [w.at_m for w in MC.wires]


def test_steps_are_the_pages_timeline_and_hold_their_mean():
    w, h = ROW[0], WIRE_SENSOR_HEIGHTS[0]
    inside = STEP / 3
    rows = [(w, h, "temp", _at(12), 20.0), (w, h, "temp", _at(12) + inside, 22.0)]
    day = _build(_frame(rows))
    assert len(day["steps"]) == STEPS_PER_DAY
    assert day["steps"][0] == "00:00"
    values = day["metrics"]["temp"]["values"]
    assert values[_step("12:00", day)][0][0] == 21.0
    assert values[_step("12:00", day) + 1][0][0] is None


def test_a_missing_reading_stays_missing():
    w = ROW[0]
    present = WIRE_SENSOR_HEIGHTS[:-1]
    rows = [(w, h, "temp", _at(12), 20.0) for h in present]
    day = _build(_frame(rows))
    noon = day["metrics"]["temp"]["values"][_step("12:00", day)]
    assert noon[0][-1] is None
    assert all(v is None for col in noon[1:] for v in col)


def test_vpd_is_formed_per_reading_before_averaging():
    w, h = ROW[0], WIRE_SENSOR_HEIGHTS[0]
    pairs = [(_at(12), 18.0, 95.0), (_at(12) + STEP / 3, 30.0, 50.0)]
    rows = [r for when, temp, hum in pairs
            for r in ((w, h, "temp", when, temp), (w, h, "hum", when, hum))]
    df = _frame(rows)
    day = _build(df)
    expected = vpd_series(df)["value"].mean()
    assert day["metrics"]["vpd"]["values"][_step("12:00", day)][0][0] == round(expected, 2)


def _noon_scale(rows) -> list[float] | None:
    day = _build(_frame(rows))
    return day["metrics"]["temp"]["scales"][_step("12:00", day)]


def test_colour_range_is_never_narrower_than_the_notable_spread():
    small = SPANS["temp"] / 4
    rows = [(ROW[0], 1, "temp", _at(12), 20.0), (ROW[1], 1, "temp", _at(12), 20.0 + small)]
    lo, hi = _noon_scale(rows)
    assert hi - lo == pytest.approx(SPANS["temp"])
    assert lo < 20.0 and hi > 20.0 + small

    wide = SPANS["temp"] * 3
    rows = [(ROW[0], 1, "temp", _at(12), 20.0), (ROW[1], 1, "temp", _at(12), 20.0 + wide)]
    assert _noon_scale(rows) == [20.0, 20.0 + wide]


def test_colour_range_follows_the_step_not_the_day():
    """Night against noon must not use up the colours for the spread along the row."""
    night = SPANS["temp"] * 10
    wide = SPANS["temp"] * 3
    rows = [
        (ROW[0], 1, "temp", _at(2), 20.0 - night),
        (ROW[0], 1, "temp", _at(12), 20.0),
        (ROW[1], 1, "temp", _at(12), 20.0 + wide),
    ]
    assert _noon_scale(rows) == [20.0, 20.0 + wide]


def test_a_day_without_readings_says_so():
    day = _build(_frame([]))
    assert all(s is None for m in day["metrics"].values() for s in m["scales"])
    assert day["notes"] == [i18n.t("greenhouse.note.no_wire_data")]


def test_uninstalled_and_unplaced_wires_are_named():
    rows = [(ROW[0], 1, "temp", _at(12), 20.0)]
    extra = "WS_99_99"
    day = _build(_frame(rows), installed=[*ROW[1:], extra])
    assert day["wires"][0]["installed"] is False
    assert any(ROW[0] in n for n in day["notes"])
    assert any(extra in n for n in day["notes"])


def _raw_microclimate() -> dict:
    raw = yaml.safe_load((RED / "metadata.yaml").read_text(encoding="utf-8"))
    return raw["greenhouse"]["microclimate"]


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r["wires"].reverse(),                            # not along the row
        lambda r: r["heights_m"].pop(WIRE_SENSOR_HEIGHTS[-1]),     # a height unplaced
        lambda r: r["heights_m"].update({1: 0.0}),                 # H1 not on top
        lambda r: r.update(metrics=["dli"]),                       # accumulates: no snapshot
        lambda r: r.update(wires=r["wires"][:1]),                  # one wire is no section
    ],
)
def test_the_configured_section_must_be_a_grid(change):
    raw = _raw_microclimate()
    change(raw)
    with pytest.raises(ValidationError):
        Microclimate(**raw)


# ------------------------------------------------------------------ route


class _StubDb:
    def __init__(self, frame):
        self._frame = frame

    async def get_active_wire_ids(self):
        return list(INSTALLED)

    async def get_wire_sensor_readings(self, start=None, end=None, limit=None):
        return self._frame

    async def get_wire_device_summary(self):
        last = pd.Timestamp(DAY, tz=TZ) + pd.Timedelta(hours=12)
        return {wire_device_id(w, 1): {"readings": 1, "last_seen": last.tz_convert("UTC")}
                for w in INSTALLED}


@pytest.fixture(scope="module")
def app():
    from wp6_data.shared.templates import config as tmpl_config

    saved = (tmpl_config._dashboard_id, tmpl_config._dashboard_title,
             tmpl_config._twin_theme_css, tmpl_config._data_sources)
    from wp6_data.red.dashboard import config
    from wp6_data.shared.app_factory import create_app

    try:
        yield create_app(dataclasses.replace(config, lifespan_startup=None, lifespan_shutdown=None))
    finally:
        (tmpl_config._dashboard_id, tmpl_config._dashboard_title,
         tmpl_config._twin_theme_css, tmpl_config._data_sources) = saved


@pytest.fixture
def client(app, monkeypatch):
    from wp6_data.red.routes import greenhouse

    invalidate_wire_cache()
    greenhouse._micro.clear()
    rows = [(w, h, "temp", _at(12), 20.0) for w in ROW for h in WIRE_SENSOR_HEIGHTS]
    monkeypatch.setattr(deps, "db", _StubDb(_frame(rows)))
    monkeypatch.setattr(deps.base_settings, "display_timezone", TZ)
    with TestClient(app) as c:
        assert c.get("/auth/login", follow_redirects=False).status_code == 302
        yield c
    invalidate_wire_cache()


def test_route_defaults_to_the_newest_wire_day(client):
    body = client.get("/greenhouse/api/microclimate").json()
    assert body["date"] == DAY.isoformat()
    assert body["range"]["latest"] == DAY.isoformat()
    assert set(body["metrics"]) == set(MC.metrics)
    assert body["metrics"]["temp"]["values"][body["steps"].index("12:00")][0][0] == 20.0


def test_route_rejects_a_bad_date(client):
    assert client.get("/greenhouse/api/microclimate?date=12-08").status_code == 400
