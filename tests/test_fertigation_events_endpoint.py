"""Contract test for GET /api/fertigation-events CSV fallback behavior."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wp6_data.blue.routes import api as blue_api
from wp6_data.shared.auth import verify_session_user


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(blue_api.router)
    app.dependency_overrides[verify_session_user] = lambda: None
    with TestClient(app) as c:
        yield c


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

    monkeypatch.setattr(blue_api, "_fertigation_csv_path", lambda: csv_path)

    resp = client.get("/api/fertigation-events?start=2026-06-02&end=2026-06-03")

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "csv:fertigation_events"
    assert body["total_events"] == 2
    assert body["in_view_events"] == 1
    assert body["first_date"] == "2026-06-01"
    assert body["last_date"] == "2026-06-03"
    assert [e["date"] for e in body["events"]] == ["2026-06-03"]
