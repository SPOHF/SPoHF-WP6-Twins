"""Tests for the red "Crop Climate by Height" view (issue 013).

Covers the pure pieces that don't need a live MySQL connection: the red-only
growth-section loader, the inline-SVG sparkline, the per-cell series extraction,
and that the view is registered in the Multi Height hub.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from wp6_data.red.db import WIRE_SENSOR_HEIGHTS, wire_device_id
from wp6_data.red.growth_sections import load_growth_sections
from wp6_data.red.routes.multi_height import (
    MULTI_HEIGHT_VIEWS,
    _admin_build_panel,
    _audit_table,
    _fmt_duration,
    _fungal_cell,
    _height_dli_cell,
    _series_for,
    _sparkline_svg,
    _status_cell,
    _vpd_cell,
    _vpd_sparkline_svg,
)

RED_METADATA = (
    Path(__file__).parent.parent / "src/wp6_data/red/metadata.yaml"
)

_T0 = pd.Timestamp("2026-05-26T12:00:00", tz="UTC")


def _at(minutes):
    return _T0 + pd.Timedelta(minutes=minutes)


class TestLoadGrowthSections:
    def test_loads_ordered_sections(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text(
            "growth_sections:\n"
            "  - height: 1\n    label: Top\n"
            "  - height: 2\n    label: Bottom\n"
        )
        secs = load_growth_sections(p)
        assert [(s.height, s.label) for s in secs] == [(1, "Top"), (2, "Bottom")]

    def test_missing_key_returns_empty(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text("devices: {}\n")
        assert load_growth_sections(p) == []

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_growth_sections(tmp_path / "nope.yaml") == []

    def test_red_config_has_one_section_per_wire_height(self):
        """The shipped red config maps every wire height to a labelled section."""
        secs = load_growth_sections(RED_METADATA)
        assert [s.height for s in secs] == WIRE_SENSOR_HEIGHTS  # ordered H1->H5
        assert all(s.label for s in secs)


class TestSparklineSvg:
    def test_too_few_points_renders_placeholder(self):
        assert "polyline" not in _sparkline_svg([], "#000")
        assert "polyline" not in _sparkline_svg([1.0], "#000")
        assert "—" in _sparkline_svg([1.0], "#000")

    def test_polyline_has_one_point_per_value(self):
        svg = _sparkline_svg([1.0, 2.0, 3.0], "#000")
        points = re.search(r'points="([^"]+)"', svg).group(1)
        assert len(points.split()) == 3

    def test_nan_values_are_dropped(self):
        svg = _sparkline_svg([1.0, float("nan"), 2.0], "#000")
        points = re.search(r'points="([^"]+)"', svg).group(1)
        assert len(points.split()) == 2


class TestSeriesFor:
    @staticmethod
    def _df():
        rows = [
            ("WS_01_01-h1", "par", "12:30", 2.0),
            ("WS_01_01-h1", "par", "12:00", 1.0),  # out of order on purpose
            ("WS_01_01-h1", "temp", "12:00", 9.0),
            ("WS_01_01-h2", "par", "12:00", 5.0),
        ]
        return pd.DataFrame(
            {
                "device": [r[0] for r in rows],
                "height": [1, 1, 1, 2],
                "measurement": [r[1] for r in rows],
                "time": [pd.Timestamp(f"2026-05-26T{r[2]}:00", tz="UTC") for r in rows],
                "value": [r[3] for r in rows],
            }
        )

    def test_returns_time_sorted_values_for_device_and_measurement(self):
        assert _series_for(self._df(), wire_device_id("WS_01_01", 1), "par") == [1.0, 2.0]

    def test_scopes_to_the_right_height(self):
        assert _series_for(self._df(), wire_device_id("WS_01_01", 2), "par") == [5.0]

    def test_empty_frame_returns_empty(self):
        assert _series_for(pd.DataFrame(), "WS_01_01-h1", "par") == []


class TestPlantRail:
    def test_asset_exists_and_height_matches_zones(self):
        import xml.etree.ElementTree as ET

        from wp6_data.red.routes.multi_height import CROP_ROW_HEIGHT, PLANT_SVG_PATH

        viewbox = ET.parse(PLANT_SVG_PATH).getroot().attrib["viewBox"].split()
        assert int(viewbox[3]) == len(WIRE_SENSOR_HEIGHTS) * CROP_ROW_HEIGHT

    def test_zone_cell_crops_to_its_row(self):
        from wp6_data.red.routes.multi_height import CROP_ROW_HEIGHT, _plant_zone_cell

        total = len(WIRE_SENSOR_HEIGHTS)
        html = _plant_zone_cell(2, total, "data:image/svg+xml;base64,XYZ")
        # Full SVG sized to all rows, offset up to show this row's zone.
        assert f'height="{total * CROP_ROW_HEIGHT}"' in html
        assert f"margin-top:-{2 * CROP_ROW_HEIGHT}px" in html
        assert "data:image/svg+xml" in html


class TestMeasurementCell:
    def test_cell_has_relative_background_value_and_is_clickable(self):
        from wp6_data.red.routes.multi_height import _measurement_cell

        html = _measurement_cell([10.0, 20.0], "temp", 0.0, 20.0, 1)
        assert "background:rgba(" in html
        assert "20.0" in html  # latest value rendered
        assert 'data-metric="temp"' in html  # clickable for chart expansion
        assert 'data-height="1"' in html

    def test_empty_series_renders_placeholder(self):
        from wp6_data.red.routes.multi_height import _measurement_cell

        assert "—" in _measurement_cell([], "par", 0.0, 1.0, 1)


class TestDerivedCells:
    def test_height_dli_cell_shows_total_and_sparkline(self):
        # n readings -> n-1 cumulative points; need 3+ for a drawable line.
        df = pd.DataFrame({"time": [_at(0), _at(15), _at(30)], "value": [100.0] * 3})
        out = _height_dli_cell(df, 1)
        assert "mol" in out
        assert "polyline" in out
        assert 'data-metric="dli"' in out  # clickable

    def test_height_dli_cell_empty(self):
        assert "—" in _height_dli_cell(pd.DataFrame(columns=["time", "value"]), 1)

    def test_vpd_cell_renders_value_and_band(self):
        df = pd.DataFrame({
            "time": [_at(0), _at(0), _at(15), _at(15)],
            "measurement": ["temp", "hum", "temp", "hum"],
            "value": [25.0, 60.0, 26.0, 55.0],
        })
        out = _vpd_cell(df, 0.4, 1.2, 1)
        assert "kPa" in out
        assert "<rect" in out  # shaded healthy band

    def test_vpd_cell_empty(self):
        empty = pd.DataFrame(columns=["time", "measurement", "value"])
        assert "—" in _vpd_cell(empty, 0.4, 1.2, 1)

    def test_fungal_cell_shows_hours(self):
        df = pd.DataFrame({"time": [_at(0), _at(15), _at(30)], "value": [90.0, 90.0, 90.0]})
        out = _fungal_cell(df, 85.0, 24.0, 1)
        assert " h" in out
        assert "polyline" in out

    def test_vpd_sparkline_has_band_and_line(self):
        svg = _vpd_sparkline_svg([0.5, 2.0], 0.4, 1.2)
        assert "<rect" in svg
        assert "polyline" in svg

    def test_vpd_sparkline_too_few_points(self):
        assert "polyline" not in _vpd_sparkline_svg([0.5], 0.4, 1.2)


class TestStatusCell:
    def test_no_state_renders_dash(self):
        assert "—" in _status_cell(None)

    def test_badges_reflect_persisted_state(self):
        state = {"height": 1, "canopy_deficit": True, "fungal_active": False,
                 "vpd_in_band": False}
        out = _status_cell(state)
        assert "Light" in out
        assert "VPD" in out
        assert "Fungal" not in out

    def test_ok_when_no_flags(self):
        state = {"height": 1, "canopy_deficit": False, "fungal_active": False,
                 "vpd_in_band": True}
        assert ">OK<" in _status_cell(state)


class TestAdminBuildPanel:
    def test_has_update_and_rebuild_actions(self):
        out = _admin_build_panel("WS_01_01", date(2026, 6, 2))
        assert "crop-climate/update" in out
        assert "crop-climate/rebuild" in out
        assert "WS_01_01" in out


class TestAuditLog:
    def test_empty_range_message(self):
        assert "No risk episodes" in _audit_table([])

    def test_open_episode_shows_ongoing(self):
        ep = {
            "height": 2, "label": "Bloeiende tros", "risk": "fungal",
            "start_time": _T0, "end_time": None, "peak": 3.2,
            "thresholds": {"rh_pct": 85},
        }
        out = _audit_table([ep])
        assert "Fungal risk" in out
        assert "ongoing" in out
        assert "H2" in out
        assert "rh_pct" in out  # threshold-set stamped

    def test_closed_episode_shows_duration(self):
        ep = {
            "height": 1, "label": "Kop", "risk": "vpd",
            "start_time": _T0, "end_time": _at(150), "peak": 1.0, "thresholds": {},
        }
        assert "2h 30m" in _audit_table([ep])

    def test_fmt_duration(self):
        assert _fmt_duration(timedelta(hours=2, minutes=30)) == "2h 30m"
        assert _fmt_duration(timedelta(minutes=45)) == "45m"
        assert _fmt_duration(timedelta(days=1, hours=3)) == "1d 3h"


class TestHubRegistration:
    def test_crop_climate_view_is_listed(self):
        hrefs = {v["href"] for v in MULTI_HEIGHT_VIEWS}
        assert "/multi_height/crop-climate" in hrefs
