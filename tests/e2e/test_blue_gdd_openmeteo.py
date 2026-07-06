"""E2E: the GDD page renders from OpenMeteo weather and drops the source toggle.

GDD no longer reads sensor data (issue 023) — it's modeled weather only — so the
data-source toggle must not appear on this page, and the weather provenance must.
The weather fetch is mocked so the test makes no network call.
"""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport

import wp6_data.blue.routes.gdd as gdd_route

pytestmark = pytest.mark.e2e

TSDB_DSN = "postgresql://wp6:wp6dev@localhost:5433/wp6_blue"


def _fake_actual_df():
    """~2 months of hourly-ish temps in the current year for calculate_daily_gdd."""
    import pandas as pd

    start = date(date.today().year, 1, 1)
    rows = []
    for i in range(60):
        d = start + timedelta(days=i)
        for hour, temp in ((6, 4.0), (14, 16.0)):
            rows.append({
                "time": datetime(d.year, d.month, d.day, hour, tzinfo=UTC),
                "value": temp,
            })
    return pd.DataFrame(rows, columns=["time", "value"])


@pytest.mark.e2e
async def test_gdd_page_uses_openmeteo_and_hides_source_toggle(monkeypatch):
    async def _fake_weather(latitude, longitude, today):
        return _fake_actual_df(), []  # actuals only, no forecast days

    monkeypatch.setattr(gdd_route, "get_weather_hours", _fake_weather)

    import os
    os.environ["WP6_TSDB_URL"] = TSDB_DSN
    from wp6_data.blue.dashboard import app

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=True,
    ) as client:
        resp = await client.get("/gdd")

    assert resp.status_code == 200
    body = resp.text
    # Weather provenance shown, GDD content rendered.
    assert "OpenMeteo" in body
    assert "GDD Tracker" in body
    # Source toggle suppressed on this source-independent page.
    assert 'id="source-toggle"' not in body
