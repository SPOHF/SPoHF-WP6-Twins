"""Red's DLI model migrated old artifacts forward; now it refuses them.

While models died with the pod that wrote them, accepting a v4 pickle and
filling its gaps with defaults was survivable — the artifact could not outlive
its deploy. Persisting them (ADR 0007) makes a migrated model able to live
indefinitely, and a *guessed* feature list is indistinguishable downstream from
a fitted one.
"""

import pickle

import pytest

from wp6_data.red.dli.model import MODEL_VERSION, TwoStageLightModel, fit_fingerprint


def _artifact(**overrides) -> dict:
    """A well-formed artifact of the current era."""
    data = {
        "stage1_model": "m1", "stage2_model": "m2",
        "stage1_poly": None, "stage2_poly": None,
        "stage1_scaler": None, "stage2_scaler": None,
        "stage1_features": ["direct_radiation_sum"],
        "stage2_features": ["lux_sum"],
        "stats": "stats", "attenuation_factor": 0.62,
        "version": MODEL_VERSION, "fingerprint": fit_fingerprint(),
    }
    data.update(overrides)
    return data


def _write(tmp_path, data) -> object:
    path = tmp_path / "light_model.pkl"
    path.write_bytes(pickle.dumps(data))
    return path


class TestLoad:
    def test_a_current_artifact_loads(self, tmp_path):
        path = _write(tmp_path, _artifact())

        assert TwoStageLightModel().load(path) == "stats"

    def test_an_older_version_is_refused_not_migrated(self, tmp_path):
        """v4/v5/v6 used to load with defaults filled in for whatever was
        missing. Refusing costs one refit; migrating costs wrong numbers."""
        for version in (4, 5, 6):
            path = _write(tmp_path, _artifact(version=version))

            assert TwoStageLightModel().load(path) is None, version

    def test_a_newer_version_is_refused_too(self, tmp_path):
        """Equality, not a floor — a rollback must not read forward."""
        path = _write(tmp_path, _artifact(version=MODEL_VERSION + 1))

        assert TwoStageLightModel().load(path) is None

    def test_a_different_fit_configuration_is_refused(self, tmp_path):
        """Move the training start or swap a sensor and the old fit answers a
        question nobody asked any more."""
        path = _write(tmp_path, _artifact(fingerprint="somethingelse"))

        assert TwoStageLightModel().load(path) is None

    def test_an_unstamped_artifact_is_refused(self, tmp_path):
        data = _artifact()
        del data["fingerprint"]
        path = _write(tmp_path, data)

        assert TwoStageLightModel().load(path) is None

    def test_a_missing_key_is_refused_rather_than_defaulted(self, tmp_path):
        """The old code filled `stage1_features` with a guess. A guessed feature
        list is indistinguishable from a fitted one once it is in memory."""
        data = _artifact()
        del data["stage1_features"]
        path = _write(tmp_path, data)

        assert TwoStageLightModel().load(path) is None

    def test_a_corrupt_pickle_returns_none_rather_than_raising(self, tmp_path):
        """`load` runs during startup, where an exception is a failed boot."""
        path = tmp_path / "light_model.pkl"
        path.write_bytes(b"this is not a pickle")

        assert TwoStageLightModel().load(path) is None

    def test_a_missing_file_returns_none(self, tmp_path):
        assert TwoStageLightModel().load(tmp_path / "nope.pkl") is None

    def test_the_attenuation_override_still_applies(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WP6_RED_DLI_ATTENUATION_OVERRIDE", "0.8")
        path = _write(tmp_path, _artifact())

        model = TwoStageLightModel()
        model.load(path)

        assert model.attenuation_factor == pytest.approx(0.8)


class TestFingerprint:
    def test_it_moves_with_the_training_window(self, monkeypatch):
        """The window is the input most likely to be widened, and the one a
        version constant would never notice."""
        from datetime import date

        from wp6_data.red.dli import model as dli_model

        before = fit_fingerprint()
        monkeypatch.setattr(dli_model, "DEFAULT_TRAINING_START", date(2025, 1, 1))

        assert dli_model.fit_fingerprint() != before

    def test_it_moves_with_the_sensor(self, monkeypatch):
        from wp6_data.red.dli import model as dli_model

        before = fit_fingerprint()
        monkeypatch.setattr(dli_model, "NATURAL_LIGHT_SENSOR", "s9999-01-par")

        assert dli_model.fit_fingerprint() != before

    def test_saving_stamps_the_current_version_and_fingerprint(self):
        """The version and fingerprint must come from the constants, not from
        literals that drift — this file's own `_artifact` relies on it."""
        import inspect

        source = inspect.getsource(TwoStageLightModel.save)

        assert '"version": MODEL_VERSION' in source
        assert '"fingerprint": fit_fingerprint()' in source
