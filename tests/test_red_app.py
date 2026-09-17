"""Smoke tests for the red dashboard app composed without infrastructure.

Builds the red app from its real TwinConfig with the lifespan hooks stripped,
so no MySQL connect, TSDB pool init or model training happens: ``deps.db``
stays ``None`` and each covered route must compose — either via its
"Database not connected" branch or (for the shared home) with the provider's
backends mocked per tests/test_red_provider.py.

dev-auth env is set before the app imports (see tests/test_series_endpoint.py).
"""

import os

os.environ.setdefault("WP6_OIDC_DEV_AUTH", "true")
os.environ.setdefault("WP6_OIDC_CLIENT_SECRET", "dev")
os.environ.setdefault("WP6_OIDC_SESSION_SECRET", "dev-session-secret-dev-session-secret")
os.environ.setdefault(
    "WP6_RED_TSDB_URL", "postgresql://wp6_red:wp6dev@localhost:5433/wp6_red",
)

import dataclasses
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    # Importing red.dashboard runs create_app -> configure_dashboard, which
    # mutates module globals in shared.templates.config (dashboard identity).
    # Snapshot them first and restore on teardown so this module can't pollute
    # others (e.g. test_templates asserts the configured identity).
    from wp6_data.shared.templates import config as tmpl_config

    saved = (
        tmpl_config._dashboard_id,
        tmpl_config._dashboard_title,
        tmpl_config._twin_theme_css,
        tmpl_config._data_sources,
    )
    from wp6_data.red.dashboard import config
    from wp6_data.shared.app_factory import create_app

    # Strip the lifespan hooks: no MySQL connect / TSDB pool / model training.
    test_config = dataclasses.replace(
        config, lifespan_startup=None, lifespan_shutdown=None,
    )
    app = create_app(test_config)
    try:
        with TestClient(app) as c:
            # Dev-auth login seeds the session cookie the routes require.
            resp = c.get("/auth/login", follow_redirects=False)
            assert resp.status_code == 302
            yield c
    finally:
        (
            tmpl_config._dashboard_id,
            tmpl_config._dashboard_title,
            tmpl_config._twin_theme_css,
            tmpl_config._data_sources,
        ) = saved


def test_multi_height_landing_renders_without_db(client):
    resp = client.get("/multi_height")
    assert resp.status_code == 200
    assert "Multi Height" in resp.text


def test_dli_home_renders_not_connected_page(client):
    from wp6_data.red.routes.dli.home import PAGE_TITLE

    resp = client.get("/dli")
    assert resp.status_code == 200
    assert "Database not connected" in resp.text
    assert PAGE_TITLE in resp.text


def test_dli_history_renders_not_connected_page(client):
    from wp6_data.red.routes.dli.history import PAGE_TITLE

    resp = client.get("/dli/history")
    assert resp.status_code == 200
    assert "Database not connected" in resp.text
    assert PAGE_TITLE in resp.text


def test_climate_forecast_survives_a_pickle_naming_a_dead_module(
    client, tmp_path, monkeypatch
):
    """A pickle naming a module that no longer exists must degrade to "retrain".

    Regression: the lamp model moved to red/lamp.py, and every saved climate
    artifact recorded its class by the old module path. Unpickling raised
    ModuleNotFoundError before the version check could reject the artifact,
    taking the page down with it.
    """
    from wp6_data.red.climate import model as climate_model

    # A GLOBAL opcode pointing at the module the lamp model used to live in —
    # byte-for-byte the failure a real saved artifact hits.
    stale = tmp_path / "climate_model.pkl"
    stale.write_bytes(b"\x80\x04cwp6_data.red.climate.lamp\nLampModel\n.")

    with pytest.raises(ModuleNotFoundError):
        import pickle

        pickle.loads(stale.read_bytes())

    assert climate_model.read_artifact(stale) is None

    monkeypatch.setattr(climate_model, "MODEL_PATH", stale)
    resp = client.get("/climate/forecast")
    assert resp.status_code == 200


def test_read_artifact_rejects_an_older_era(tmp_path):
    import pickle

    from wp6_data.red.climate.model import MODEL_VERSION, read_artifact

    old = tmp_path / "old.pkl"
    old.write_bytes(pickle.dumps({"version": MODEL_VERSION - 1, "chain": None}))
    assert read_artifact(old) is None

    current = tmp_path / "current.pkl"
    current.write_bytes(pickle.dumps({"version": MODEL_VERSION, "chain": "x"}))
    assert read_artifact(current) == {"version": MODEL_VERSION, "chain": "x"}


def test_read_artifact_rejects_a_model_fitted_under_a_different_config(tmp_path):
    """The rail that persistence makes necessary.

    A config edit — a widened training window, an added horizon, a new
    exclusion — does not change the pickle's layout, so the version gate waves
    it through. While models died with the pod that was harmless: the next boot
    refitted anyway. Now that they outlive a deploy, a model fitted to answer a
    different question would keep being served.
    """
    import pickle

    from wp6_data.red.climate.model import MODEL_VERSION, read_artifact

    path = tmp_path / "model.pkl"
    path.write_bytes(
        pickle.dumps({"version": MODEL_VERSION, "fingerprint": "abc", "chain": "x"})
    )

    assert read_artifact(path, expect_fingerprint="abc") is not None
    assert read_artifact(path, expect_fingerprint="def") is None
    # No expectation stated: the layout check still applies, the config one does not.
    assert read_artifact(path) is not None


def test_an_unstamped_artifact_is_refused_when_a_config_is_expected(tmp_path):
    """Artifacts written before fingerprinting existed cannot be vouched for."""
    import pickle

    from wp6_data.red.climate.model import MODEL_VERSION, read_artifact

    path = tmp_path / "model.pkl"
    path.write_bytes(pickle.dumps({"version": MODEL_VERSION, "chain": "x"}))

    assert read_artifact(path, expect_fingerprint="abc") is None


def test_the_config_fingerprint_moves_with_the_config():
    """Every field shapes the fit, so every field is in the fingerprint."""
    from wp6_data.red import deps
    from wp6_data.red.climate.config import load_climate_model

    config = load_climate_model(deps._METADATA_PATH)
    before = config.fit_fingerprint()

    widened = config.model_copy(
        update={"horizons_hours": [*config.horizons_hours, 72]}
    )

    assert widened.fit_fingerprint() != before
    # ...and is stable when nothing changed.
    assert load_climate_model(deps._METADATA_PATH).fit_fingerprint() == before


def test_every_writer_of_the_artifact_stamps_it():
    """There are two places that write the pickle, and both must stamp it.

    `IndoorClimateModel.save` is the one you find first; `training._save` is the
    one training actually calls. Stamping only the first left the fingerprint
    permanently absent, so every load was refused and the model refitted on
    every boot — the exact failure persistence was meant to remove, and silent
    because "refused" looks the same as "no model yet".
    """
    import inspect

    from wp6_data.red.climate import model as climate_model
    from wp6_data.red.climate import training

    for writer in (climate_model.IndoorClimateModel.save, training._save):
        source = inspect.getsource(writer)
        assert '"version": MODEL_VERSION' in source, writer.__qualname__
        assert '"fingerprint"' in source, writer.__qualname__


def test_read_artifact_returns_none_for_a_missing_file(tmp_path):
    from wp6_data.red.climate.model import read_artifact

    assert read_artifact(tmp_path / "nope.pkl") is None


def test_dli_lamps_renders_not_connected_page(client):
    from wp6_data.red.routes.dli.lamps import PAGE_TITLE

    resp = client.get("/dli/lamps")
    assert resp.status_code == 200
    assert "Database not connected" in resp.text
    assert PAGE_TITLE in resp.text


def test_shared_home_composes_with_mocked_data_layer(client, monkeypatch):
    """GET / drives RedSensorProvider; back it with empty mocked backends."""
    from wp6_data.red import deps as red_deps
    from wp6_data.red import tsdb
    from wp6_data.red.dashboard import config
    from wp6_data.red.provider import _coverage_cache
    from wp6_data.shared import sensor_summary

    db = AsyncMock()
    db.get_all_devices.return_value = {}
    db.get_wire_device_summary.return_value = {}
    monkeypatch.setattr(red_deps, "db", db)
    monkeypatch.setattr(tsdb, "fetch_sensors_from_cagg", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        tsdb,
        "fetch_manual_summary_tsdb",
        AsyncMock(return_value={"uploads": {}, "measurements": {}}),
    )
    sensor_summary.invalidate()
    _coverage_cache.clear()
    try:
        resp = client.get("/")
        assert resp.status_code == 200
        assert config.title in resp.text
    finally:
        # Drop anything cached from the mocked backends.
        sensor_summary.invalidate()
        _coverage_cache.clear()


def test_climate_model_page_degrades_when_untrained(client, monkeypatch, tmp_path):
    """Models live on ephemeral storage, so 'not trained yet' is a normal state
    the page must render — not a 500."""
    from wp6_data.red.routes.climate_model import status as status_route

    monkeypatch.setattr(status_route, "load_chain", lambda: None)

    resp = client.get("/climate/model/")

    assert resp.status_code == 200
    assert "No climate model yet" in resp.text
    assert "/climate/model/train" in resp.text


def test_climate_model_train_reports_no_database_rather_than_failing(client, monkeypatch):
    from wp6_data.red.climate import data as climate_data

    monkeypatch.setattr(climate_data, "is_connected", lambda: False)

    resp = client.post("/climate/model/train", follow_redirects=False)

    assert resp.status_code == 200
    assert "Database not connected" in resp.text


def test_climate_model_page_reports_skill_not_just_r2(client, monkeypatch):
    """The page must lead with what the model beats. An R2 grid alone reads as
    success everywhere for a slowly-moving indoor quantity."""
    from datetime import UTC, date, datetime

    from wp6_data.red.climate.model import ClimateModelStats, HorizonFit
    from wp6_data.red.climate.training import TrainedChain
    from wp6_data.red.fitting import StageStats
    from wp6_data.red.routes.climate_model import status as status_route

    stats = ClimateModelStats(
        trained_at=datetime(2026, 9, 16, tzinfo=UTC),
        span=(date(2025, 10, 8), date(2026, 9, 16)),
        reference_key="s2103",
        link2=[
            HorizonFit(
                "temp", 1,
                StageStats(
                    0.9, 1.0, 0.8, 100, {}, 0.0,
                    holdout_r2=0.88, holdout_rmse=1.2,
                    skill={"persistence": 0.31, "climatology": -0.12},
                ),
            )
        ],
    )
    monkeypatch.setattr(
        status_route, "load_chain",
        lambda: TrainedChain(
            trained_at=datetime(2026, 9, 16, tzinfo=UTC),
            chosen_reference="s2103",
            comparison={"s2103": stats},
        ),
    )

    resp = client.get("/climate/model/")

    assert resp.status_code == 200
    assert "vs persistence" in resp.text
    assert "+0.31" in resp.text
    # A baseline the model lost to is shown as a loss, not hidden.
    assert "-0.12" in resp.text


def test_climate_model_surfaces_retraining_suggestions(client, monkeypatch):
    """Retraining is how this improves, so config that has become improvable is
    shown on the page rather than left implicit."""
    from datetime import UTC, date, datetime

    from wp6_data.red.climate.model import ClimateModelStats
    from wp6_data.red.climate.training import TrainedChain
    from wp6_data.red.routes.climate_model import status as status_route

    suggestion = "WS_01_03 now reports temp at height(s) H1"
    monkeypatch.setattr(
        status_route, "load_chain",
        lambda: TrainedChain(
            trained_at=datetime(2026, 9, 16, tzinfo=UTC),
            chosen_reference="s2103",
            comparison={
                "s2103": ClimateModelStats(
                    trained_at=datetime(2026, 9, 16, tzinfo=UTC),
                    span=(date(2025, 10, 8), date(2026, 9, 16)),
                    reference_key="s2103",
                )
            },
            suggestions=[suggestion],
        ),
    )

    resp = client.get("/climate/model/")

    assert resp.status_code == 200
    assert "Configuration that has become improvable" in resp.text
    assert suggestion in resp.text


def test_multi_height_hub_offers_the_climate_forecast(client):
    """The forecast is a per-growth-section view, so it belongs in the hub that
    lists the other per-height views rather than only under /climate."""
    resp = client.get("/multi_height")

    assert resp.status_code == 200
    assert "Climate Forecast by Section" in resp.text
    assert "/climate/forecast" in resp.text


def test_forecast_page_links_back_to_multi_height_not_home(client, monkeypatch):
    """render_page's back link always reads 'Home' whatever it points at, so
    this page writes its own — the same as crop-climate."""
    resp = client.get("/climate/forecast")

    assert resp.status_code == 200
    assert 'href="/multi_height" class="back-link"' in resp.text


def _stub_chain(*, lamp=None, months=None):
    from datetime import UTC, date, datetime

    from wp6_data.red.climate.model import ClimateModelStats, HorizonFit
    from wp6_data.red.climate.training import TrainedChain
    from wp6_data.red.fitting import StageStats

    def fit(target, horizon, monthly):
        return HorizonFit(
            target, horizon,
            StageStats(0.9, 1.0, 0.8, 100, {}, 0.0, holdout_r2=0.88,
                       holdout_rmse=1.2, skill={"persistence": 0.3, "climatology": 0.1}),
            error_by_month=monthly or [],
        )

    stats = ClimateModelStats(
        trained_at=datetime(2026, 9, 16, tzinfo=UTC),
        span=(date(2025, 10, 8), date(2026, 9, 16)),
        reference_key="s2103",
        link2=[fit("temp", h, months) for h in (1, 6)],
    )
    return TrainedChain(
        trained_at=datetime(2026, 9, 16, tzinfo=UTC),
        chosen_reference="s2103", comparison={"s2103": stats}, lamp=lamp,
    ), stats


def test_model_page_opens_with_an_overview_of_the_chain(client, monkeypatch):
    """A reader needs to know what the three links are before any score below
    means anything."""
    from wp6_data.red.routes.climate_model import status as status_route

    chain, _ = _stub_chain()
    monkeypatch.setattr(status_route, "load_chain", lambda: chain)

    resp = client.get("/climate/model/")

    assert resp.status_code == 200
    assert "How the model works" in resp.text
    for stage in ("Link 1", "Link 2", "Link 3", "Lamps"):
        assert stage in resp.text
    # the overview comes before the scores
    assert resp.text.index("How the model works") < resp.text.index("Link 2 ·")


def test_overview_reports_the_lamp_state_it_was_trained_with(client, monkeypatch):
    from wp6_data.red.lamp import LampModel
    from wp6_data.red.routes.climate_model import status as status_route

    lamp = LampModel(
        attenuation=0.63, attenuation_days=280, power_par=190.7,
        hours_on=frozenset({23, 0, 1, 2}), observed_days=14,
    )
    chain, _ = _stub_chain(lamp=lamp)
    monkeypatch.setattr(status_route, "load_chain", lambda: chain)

    resp = client.get("/climate/model/")

    assert "190.7" in resp.text
    assert "observed, not predicted" in resp.text


def test_seasonal_spread_is_measured_not_quoted(client):
    """An earlier description carried hardcoded ratios that went stale the
    moment the PAR reference changed."""
    from wp6_data.red.routes.climate_model.status import _seasonal_spread_note

    _, stats = _stub_chain(months=[(1, 10.0), (7, 50.0)])

    note = _seasonal_spread_note(stats)

    assert "5.0×" in note


def test_seasonal_spread_is_measured_within_a_horizon(client):
    """Pooling horizons would mix the seasonal range with the horizon range."""
    from wp6_data.red.climate.model import ClimateModelStats, HorizonFit
    from wp6_data.red.fitting import StageStats
    from wp6_data.red.routes.climate_model.status import _seasonal_spread_note

    def fit(horizon, monthly):
        return HorizonFit(
            "temp", horizon, StageStats(0.9, 1.0, 0.8, 10, {}, 0.0),
            error_by_month=monthly,
        )

    stats = ClimateModelStats(
        trained_at=None, span=(None, None), reference_key="s2103",
        link2=[fit(1, [(1, 1.0), (7, 2.0)]), fit(6, [(1, 10.0), (7, 20.0)])],
    )

    # each horizon is 2x; pooling would read as 20x
    assert "2.0×" in _seasonal_spread_note(stats)


def test_no_stored_month_residuals_yields_no_claim(client):
    from wp6_data.red.routes.climate_model.status import _seasonal_spread_note

    _, stats = _stub_chain(months=[])

    assert _seasonal_spread_note(stats) == ""
