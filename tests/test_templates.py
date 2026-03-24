"""Tests for wp6_data.shared.templates."""

from datetime import date, timedelta
from unittest.mock import patch

from wp6_data.shared.templates import (
    default_date_range,
    render_date_filter,
    render_page,
    render_unified_chart_page,
    resolve_date_range,
)


class TestResolveDateRange:
    def test_applies_defaults_when_none(self):
        start, end, start_dt, end_dt = resolve_date_range(None, None)
        assert start == end - timedelta(days=7)
        assert start_dt.hour == 0 and start_dt.minute == 0
        assert end_dt.hour == 23 and end_dt.minute == 59 and end_dt.second == 59

    def test_uses_provided_dates(self):
        s, e = date(2026, 6, 1), date(2026, 6, 10)
        start, end, start_dt, end_dt = resolve_date_range(s, e)
        assert start == s
        assert end == e
        assert start_dt.year == 2026 and start_dt.month == 6 and start_dt.day == 1
        assert end_dt.day == 10

    def test_partial_override_start_only(self):
        s = date(2026, 1, 1)
        start, end, _, _ = resolve_date_range(s, None)
        assert start == s
        assert end == date.today()

    def test_partial_override_end_only(self):
        e = date(2026, 12, 31)
        start, end, _, _ = resolve_date_range(None, e)
        assert end == e
        assert start == date.today() - timedelta(days=7)

    def test_datetimes_are_utc(self):
        from datetime import UTC

        _, _, start_dt, end_dt = resolve_date_range(date(2026, 3, 1), date(2026, 3, 2))
        assert start_dt.tzinfo is UTC
        assert end_dt.tzinfo is UTC


class TestDefaultDateRange:
    @patch("wp6_data.shared.templates.date")
    def test_returns_7_day_window(self, mock_date):
        mock_date.today.return_value = date(2026, 3, 15)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        start, end = default_date_range()
        assert end == date(2026, 3, 15)
        assert start == date(2026, 3, 8)

    def test_start_before_end(self):
        start, end = default_date_range()
        assert start < end
        assert (end - start).days == 7


class TestRenderDateFilter:
    def test_contains_form_element(self):
        html = render_date_filter(date(2026, 1, 1), date(2026, 1, 8))
        assert '<form id="dateFilter"' in html
        assert 'method="get"' in html

    def test_contains_all_preset_buttons(self):
        html = render_date_filter(date(2026, 1, 1), date(2026, 1, 8))
        for label in ("1d", "7d", "30d", "90d", "1y", "All"):
            assert f">{label}</button>" in html

    def test_date_inputs_have_correct_values(self):
        start = date(2026, 2, 1)
        end = date(2026, 2, 10)
        html = render_date_filter(start, end)
        assert 'value="2026-02-01"' in html
        assert 'value="2026-02-10"' in html

    @patch("wp6_data.shared.templates.date")
    def test_active_preset_7d(self, mock_date):
        today = date(2026, 3, 15)
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        start = today - timedelta(days=7)
        html = render_date_filter(start, today)
        # 7d button should have active style (contrast class)
        assert 'class="contrast" onclick="setRange(7)">7d</button>' in html

    @patch("wp6_data.shared.templates.date")
    def test_active_preset_all(self, mock_date):
        today = date(2026, 3, 15)
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        html = render_date_filter(date(2024, 1, 1), today)
        assert 'class="contrast" onclick="setRange(null)">All</button>' in html

    @patch("wp6_data.shared.templates.date")
    def test_no_active_preset_for_custom_range(self, mock_date):
        today = date(2026, 3, 15)
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        html = render_date_filter(date(2026, 2, 1), date(2026, 2, 15))
        # No button should have the active (contrast) class
        assert 'class="contrast"' not in html

    def test_extra_params_rendered_as_hidden_fields(self):
        html = render_date_filter(
            date(2026, 1, 1), date(2026, 1, 8), extra_params={"sensor": "temp", "device": "d1"}
        )
        assert '<input type="hidden" name="sensor" value="temp">' in html
        assert '<input type="hidden" name="device" value="d1">' in html

    def test_setrange_script_present(self):
        html = render_date_filter(date(2026, 1, 1), date(2026, 1, 8))
        assert "function setRange(days)" in html


class TestRenderPage:
    def test_minimal_page_structure(self):
        html = render_page("Test", "<p>Hello</p>", show_logo=False, show_footer=False)
        assert "<!DOCTYPE html>" in html
        assert "<title>Test</title>" in html
        assert "<p>Hello</p>" in html

    def test_nav_bar_rendered(self):
        html = render_page("T", "content")
        assert "dashboard-nav" in html
        assert "theme-toggle" in html

    def test_dashboard_identity_default(self):
        html = render_page("T", "content")
        assert 'data-dashboard="blue"' in html

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

    def test_pico_css_always_included(self):
        html = render_page("T", "content")
        assert "pico.classless.min.css" in html


class TestRenderUnifiedChartPage:
    def test_contains_chart_layout(self):
        html = render_unified_chart_page("Test", date(2026, 1, 1), date(2026, 1, 8))
        assert "chart-layout" in html
        assert "sensor-panel" in html
        assert "chart-area" in html

    def test_contains_date_filter(self):
        html = render_unified_chart_page("Test", date(2026, 1, 1), date(2026, 1, 8))
        assert "dateFilter" in html
        assert 'value="2026-01-01"' in html

    def test_contains_plotly_script(self):
        html = render_unified_chart_page("Test", date(2026, 1, 1), date(2026, 1, 8))
        assert "plotly" in html.lower()

    def test_contains_grouping_toggle(self):
        html = render_unified_chart_page("Test", date(2026, 1, 1), date(2026, 1, 8))
        assert "By metric" in html
        assert "By device" in html

    def test_contains_clear_button(self):
        html = render_unified_chart_page("Test", date(2026, 1, 1), date(2026, 1, 8))
        assert "clear-all" in html

    def test_contains_panel_toggle(self):
        html = render_unified_chart_page("Test", date(2026, 1, 1), date(2026, 1, 8))
        assert "panel-toggle" in html
        assert "Hide controls" in html
