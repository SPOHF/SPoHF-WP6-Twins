"""Contract test for GET /api/fertigation-events CSV fallback behavior."""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("WP6_OIDC_DEV_AUTH", "true")
    os.environ.setdefault("WP6_OIDC_CLIENT_SECRET", "dev")
    os.environ.setdefault(
        "WP6_OIDC_SESSION_SECRET",
        "dev-session-secret-dev-session-secret",
    )

    # Keep shared dashboard identity globals isolated from other test modules.
    import wp6_data.shared.templates as tmpl

    saved = (
        tmpl._dashboard_id,
        tmpl._dashboard_title,
        tmpl._twin_theme_css,
        tmpl._data_sources,
    )
    from wp6_data.grey.dashboard import app

    try:
        with TestClient(app) as c:
            yield c
    finally:
        (
            tmpl._dashboard_id,
            tmpl._dashboard_title,
            tmpl._twin_theme_css,
            tmpl._data_sources,
        ) = saved


def test_fertigation_events_csv_fallback_contract(client, monkeypatch, tmp_path):
    csv_path = tmp_path / "fertigation_events.csv"
    csv_path.write_text(
        "date,volume_ml_per_plant\n"
        "2026-06-01,10\n"
        "2026-06-02,0\n"
        "invalid-date,4\n"
        "2026-06-03,2\n",
        encoding="utf-8",
    )

    import wp6_data.shared.routes.api as api_routes

    def _raise_pool_error():
        raise RuntimeError("pool not initialized")

    monkeypatch.setattr(api_routes, "get_pool", _raise_pool_error)
    monkeypatch.setattr(api_routes, "_fertigation_csv_path", lambda: csv_path)

    resp = client.get("/api/fertigation-events?start=2026-06-02&end=2026-06-03")

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "csv:fertigation_events"
    assert body["total_events"] == 2
    assert body["in_view_events"] == 1
    assert body["first_date"] == "2026-06-01"
    assert body["last_date"] == "2026-06-03"
    assert [e["date"] for e in body["events"]] == ["2026-06-03"]
