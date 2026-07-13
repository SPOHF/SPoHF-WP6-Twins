"""Unit tests for the /status sync-health classifier and rendering helpers."""

from datetime import UTC, datetime, timedelta

from wp6_data.shared.routes.status import (
    _build_sync_endpoint,
    _classify,
    _lag_phrase,
    _sparkline,
)

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def _row(**over):
    base = {
        "endpoint": "yookr-data",
        "source_type": "synced",
        "last_run_at": NOW - timedelta(minutes=3),
        "last_run_success": True,
        "last_data_timestamp": NOW - timedelta(minutes=8),
        "freshness_budget": (2.0, 6.0),
        "records": 9809,
        "runs_7d": 671,
        "ok_7d": 669,
        "recent_records": [9000, 9100, 8800],
        "recent_success": [True, True, False],
        "total_runs": 105000,
        "total_failures": 1179,
    }
    base.update(over)
    return base


class TestClassify:
    def test_healthy_when_fresh(self):
        assert _classify(_row(), NOW)[0] == "healthy"

    def test_stale_between_budgets(self):
        row = _row(last_data_timestamp=NOW - timedelta(hours=3))
        assert _classify(row, NOW) == ("stale", "Data stale", "warning")

    def test_outage_past_budget(self):
        row = _row(last_data_timestamp=NOW - timedelta(hours=10))
        assert _classify(row, NOW) == ("outage", "Likely outage", "danger")

    def test_failing_beats_freshness(self):
        # A failed run is 'failing' regardless of data lag.
        row = _row(last_run_success=False, last_data_timestamp=NOW - timedelta(hours=10))
        assert _classify(row, NOW)[0] == "failing"

    def test_never_run(self):
        assert _classify(_row(last_run_at=None), NOW)[0] == "never"

    def test_manual_never_goes_stale(self):
        # Event-driven: an old manual upload is still 'ok', not stale/outage.
        row = _row(
            source_type="manual", freshness_budget=None,
            last_data_timestamp=NOW - timedelta(days=180),
            last_run_at=NOW - timedelta(days=180),
        )
        assert _classify(row, NOW) == ("ok", "Up to date", "success")

    def test_synced_without_budget_is_healthy_not_stale(self):
        # A scheduled job (no freshness budget) never reports stale/outage.
        row = _row(freshness_budget=None, last_data_timestamp=NOW - timedelta(days=2))
        assert _classify(row, NOW)[0] == "healthy"


class TestLagPhrase:
    def test_hours(self):
        assert _lag_phrase(10 * 3600) == "10 h behind"

    def test_minutes(self):
        assert _lag_phrase(35 * 60) == "35 min behind"

    def test_days(self):
        assert _lag_phrase(2 * 86400) == "2 d behind"


class TestSparkline:
    def test_empty(self):
        assert _sparkline([]) == ""
        assert _sparkline(None) == ""

    def test_reverses_to_chronological(self):
        # Stored newest-first; the max maps to the top tick, shown last.
        html = _sparkline([100, 50, 0])
        assert "▁" in html and "█" in html
        assert html.index("▁") < html.index("█")  # oldest(0)→newest(100)


class TestRenderEndpoint:
    def test_synced_outage_card(self):
        row = _row(last_data_timestamp=NOW - timedelta(hours=10))
        html = _build_sync_endpoint(row, NOW)
        assert "🔄 Synced" in html
        assert "Likely outage" in html
        assert "10 h behind" in html
        assert "SLA (7d)" in html
        assert "no new data" in html  # upstream reason banner

    def test_manual_card_has_no_sla(self):
        row = _row(
            endpoint="long_data", source_type="manual", freshness_budget=None,
            last_run_at=NOW - timedelta(days=180), records=3251,
        )
        html = _build_sync_endpoint(row, NOW)
        assert "✋ Manual" in html
        assert "last upload" in html
        assert "3,251" in html and "rows" in html
        assert "SLA" not in html  # manual sources omit the run-SLA

    def test_failing_card_shows_error(self):
        row = _row(
            last_run_success=False, error="boom", api_status=500,
            consecutive_failures=4, failing_since=NOW - timedelta(hours=3),
        )
        html = _build_sync_endpoint(row, NOW)
        assert "Failing" in html
        assert "Failing since" in html
        assert "boom" in html
