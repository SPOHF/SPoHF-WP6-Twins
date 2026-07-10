"""Tests for wp6_data.api.models — pure Pydantic, no mocks."""

from datetime import UTC, datetime

from wp6_data.api.models import ApiResponse, SensorReading

from .conftest import make_api_response, make_reading

# --- Value coercion via field_validator ---


class TestValueCoercion:
    def test_float_coerced_to_string(self):
        r = make_reading(value=42.5)
        assert r.value == "42.5"

    def test_int_coerced_to_string(self):
        r = make_reading(value=7)
        assert r.value == "7"

    def test_none_coerced_to_empty_string(self):
        r = make_reading(value=None)
        assert r.value == ""

    def test_string_stays_string(self):
        r = make_reading(value="hello")
        assert r.value == "hello"


# --- value_float property ---


class TestValueFloat:
    def test_valid_numeric(self):
        r = make_reading(value="21.5")
        assert r.value_float == 21.5

    def test_non_numeric_returns_none(self):
        r = make_reading(value="not-a-number")
        assert r.value_float is None

    def test_empty_string_returns_none(self):
        r = make_reading(value="")
        assert r.value_float is None

    def test_integer_string(self):
        r = make_reading(value="42")
        assert r.value_float == 42.0


# --- Optional field defaults ---


class TestOptionalDefaults:
    def test_device_name_defaults_to_unknown(self):
        r2 = SensorReading(
            sensor_id="x",
            sensor_tag="t",
            value="1",
            datetime_measure=datetime(2024, 1, 1, tzinfo=UTC),
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert r2.device_name == "unknown"

    def test_unmodelled_keys_are_dropped(self):
        # `project` is not a field; Pydantic must ignore it, not raise.
        r = make_reading(project="my-project")
        assert not hasattr(r, "project")

    def test_metadata_defaults_to_none(self):
        r = make_reading()
        assert r.metadata is None

    def test_metadata_preserved(self):
        r = make_reading(metadata={"key": "val"})
        assert r.metadata == {"key": "val"}


# --- ApiResponse ---


class TestApiResponse:
    def test_empty_response(self):
        resp = make_api_response([])
        assert resp.results == []
        assert resp.count == 0

    def test_response_with_readings(self):
        readings = [make_reading(sensor_tag="a"), make_reading(sensor_tag="b")]
        resp = make_api_response(readings)
        assert len(resp.results) == 2
        assert resp.count == 2

    def test_count_from_json(self):
        resp = ApiResponse.model_validate(
            {
                "results": [
                    {
                        "sensor_id": "x",
                        "sensor_tag": "t",
                        "value": "1",
                        "datetime_measure": "2024-01-01T00:00:00+00:00",
                        "timestamp": "2024-01-01T00:00:00+00:00",
                    }
                ],
                "count": 1,
            }
        )
        assert resp.count == 1
        assert resp.results[0].sensor_id == "x"
