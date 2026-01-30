"""Tests for wp6_data.shared.templates."""

from datetime import date, timedelta
from unittest.mock import patch

from wp6_data.shared.templates import (
    default_date_range,
    render_compare_form,
    render_date_filter,
    render_page,
)


class TestDefaultDateRange:
    @patch("wp6_data.shared.templates.date")
    def test_returns_7_day_window(self, mock_date):
        mock_date.today.return_value = date(2025, 3, 15)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        start, end = default_date_range()
        assert end == date(2025, 3, 15)
        assert start == date(2025, 3, 8)

    def test_start_before_end(self):
        start, end = default_date_range()
        assert start < end
        assert (end - start).days == 7


class TestRenderDateFilter:
    def test_contains_form_element(self):
        html = render_date_filter(date(2025, 1, 1), date(2025, 1, 8))
        assert '<form id="dateFilter"' in html
        assert 'method="get"' in html

    def test_contains_all_preset_buttons(self):
        html = render_date_filter(date(2025, 1, 1), date(2025, 1, 8))
        for label in ("1d", "7d", "30d", "90d", "1y", "All"):
            assert f">{label}</button>" in html

    def test_date_inputs_have_correct_values(self):
        start = date(2025, 2, 1)
        end = date(2025, 2, 10)
        html = render_date_filter(start, end)
        assert 'value="2025-02-01"' in html
        assert 'value="2025-02-10"' in html

    @patch("wp6_data.shared.templates.date")
    def test_active_preset_7d(self, mock_date):
        today = date(2025, 3, 15)
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        start = today - timedelta(days=7)
        html = render_date_filter(start, today)
        # 7d button should have active style (blue background)
        assert 'background: #0066cc; color: white;" onclick="setRange(7)">7d</button>' in html

    @patch("wp6_data.shared.templates.date")
    def test_active_preset_all(self, mock_date):
        today = date(2025, 3, 15)
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        html = render_date_filter(date(2024, 1, 1), today)
        assert 'background: #0066cc; color: white;" onclick="setRange(null)">All</button>' in html

    @patch("wp6_data.shared.templates.date")
    def test_no_active_preset_for_custom_range(self, mock_date):
        today = date(2025, 3, 15)
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        html = render_date_filter(date(2025, 2, 1), date(2025, 2, 15))
        # No button should have the active style
        assert html.count("background: #0066cc") == 0

    def test_extra_params_rendered_as_hidden_fields(self):
        html = render_date_filter(
            date(2025, 1, 1), date(2025, 1, 8), extra_params={"sensor": "temp", "device": "d1"}
        )
        assert '<input type="hidden" name="sensor" value="temp">' in html
        assert '<input type="hidden" name="device" value="d1">' in html

    def test_no_hidden_fields_without_extra_params(self):
        html = render_date_filter(date(2025, 1, 1), date(2025, 1, 8))
        assert 'type="hidden"' not in html

    def test_setrange_script_present(self):
        html = render_date_filter(date(2025, 1, 1), date(2025, 1, 8))
        assert "function setRange(days)" in html


class TestRenderPage:
    def test_minimal_page_structure(self):
        html = render_page("Test", "<p>Hello</p>", show_logo=False, show_footer=False)
        assert "<!DOCTYPE html>" in html
        assert "<title>Test</title>" in html
        assert "<p>Hello</p>" in html

    def test_logo_shown_by_default(self):
        html = render_page("T", "content")
        assert "interreg.png" in html
        assert '<div class="logo">' in html

    def test_logo_hidden(self):
        html = render_page("T", "content", show_logo=False)
        assert '<div class="logo">' not in html

    def test_footer_shown_by_default(self):
        html = render_page("T", "content")
        assert "<footer>" in html

    def test_footer_hidden(self):
        html = render_page("T", "content", show_footer=False)
        assert "<footer>" not in html

    def test_back_link_hidden_by_default(self):
        html = render_page("T", "content")
        assert "Back to Dashboard" not in html

    def test_back_link_shown(self):
        html = render_page("T", "content", show_back_link=True)
        assert "Back to Dashboard" in html
        assert 'href="/"' in html

    def test_custom_back_url(self):
        html = render_page("T", "content", show_back_link=True, back_url="/home")
        assert 'href="/home"' in html

    def test_extra_css_included(self):
        html = render_page("T", "content", extra_css=".custom { color: red; }")
        assert ".custom { color: red; }" in html

    def test_base_css_always_included(self):
        html = render_page("T", "content")
        assert "font-family:" in html


SAMPLE_DEVICE_DATA = {
    "sensor-A": ["temp", "humidity"],
    "sensor-B": ["co2"],
}


class TestRenderCompareForm:
    def test_contains_form_with_action(self):
        html = render_compare_form(SAMPLE_DEVICE_DATA, action_url="/my/compare")
        assert 'action="/my/compare"' in html
        assert "<form" in html

    def test_default_action_url(self):
        html = render_compare_form(SAMPLE_DEVICE_DATA)
        assert 'action="/compare/chart"' in html

    def test_left_and_right_fieldsets(self):
        html = render_compare_form(SAMPLE_DEVICE_DATA)
        assert "Left Y-axis" in html
        assert "Right Y-axis" in html

    def test_device_options_sorted(self):
        html = render_compare_form(SAMPLE_DEVICE_DATA)
        assert 'value="sensor-A"' in html
        assert 'value="sensor-B"' in html
        # sensor-A should appear before sensor-B
        assert html.index("sensor-A") < html.index("sensor-B")

    def test_contains_update_script(self):
        html = render_compare_form(SAMPLE_DEVICE_DATA)
        assert "function updateMeasurements(prefix)" in html
        assert "updateMeasurements('left')" in html
        assert "updateMeasurements('right')" in html

    def test_device_data_json_embedded(self):
        html = render_compare_form(SAMPLE_DEVICE_DATA)
        assert '"sensor-A"' in html
        assert '"temp"' in html
        assert '"humidity"' in html
        assert '"co2"' in html

    def test_submit_button(self):
        html = render_compare_form(SAMPLE_DEVICE_DATA)
        assert "Generate Chart" in html

    def test_select_names(self):
        html = render_compare_form(SAMPLE_DEVICE_DATA)
        assert 'name="left_device"' in html
        assert 'name="left_measurement"' in html
        assert 'name="right_device"' in html
        assert 'name="right_measurement"' in html

    def test_empty_device_data(self):
        html = render_compare_form({})
        assert "<form" in html
        assert "Generate Chart" in html
