"""Tests for device/sensor metadata registry."""

from pathlib import Path

from wp6_data.shared.metadata import (
    DeviceMetadata,
    MetadataRegistry,
    SensorMetadata,
)

BLUE_YAML = Path(__file__).parent.parent / "src" / "wp6_data" / "blue" / "metadata.yaml"
RED_YAML = Path(__file__).parent.parent / "src" / "wp6_data" / "red" / "metadata.yaml"


def test_blue_metadata_loads() -> None:
    registry = MetadataRegistry(BLUE_YAML)
    meta = registry.sensor_default("par")
    assert meta.unit == "μmol/m²/s"
    assert meta.alias == "PAR"


def test_red_metadata_loads() -> None:
    registry = MetadataRegistry(RED_YAML)
    meta = registry.sensor_default("temp")
    assert meta.unit == "°C"
    assert meta.alias == "Temp"


def test_unknown_device_returns_empty() -> None:
    registry = MetadataRegistry(BLUE_YAML)
    meta = registry.device("nonexistent-device")
    assert meta == DeviceMetadata()


def test_unknown_sensor_returns_empty() -> None:
    registry = MetadataRegistry(RED_YAML)
    meta = registry.sensor("nonexistent-sensor")
    assert meta == SensorMetadata()


def test_missing_yaml_file() -> None:
    registry = MetadataRegistry(Path("/tmp/does-not-exist.yaml"))
    assert registry.device("x") == DeviceMetadata()
    assert registry.sensor("x") == SensorMetadata()


def test_sensor_merges_device_override_with_defaults() -> None:
    """Device-level sensor fields override sensor_defaults."""
    registry = MetadataRegistry(RED_YAML)
    # par on s2100-01-par has a device-specific intention
    meta = registry.sensor("par", "s2100-01-par")
    assert meta.unit == "μmol/m²/s"  # from defaults
    assert meta.intention == "Measures PAR above grow lamp"  # from device

    # par without a device just gets defaults
    default_meta = registry.sensor("par")
    assert default_meta.unit == "μmol/m²/s"
    assert default_meta.intention == ""


def test_sensor_types() -> None:
    """sensor_types() groups sensor keys by their type field."""
    registry = MetadataRegistry(RED_YAML)
    types = registry.sensor_types()
    assert "dendrometer" in types
    assert "adc_ch1" in types["dendrometer"]
    assert "adc_ch2" in types["dendrometer"]
    assert "adc_ch3" in types["dendrometer"]


def test_enrich_sensor_list() -> None:
    registry = MetadataRegistry(BLUE_YAML)
    flat = [
        {"device": "weatherstation", "sensor": "precipitation"},
        {"device": "weatherstation", "sensor": "windSpeed"},
        {"device": "3672 | PAR", "sensor": "par"},
    ]
    enriched = registry.enrich_sensor_list(flat)

    # Should group by device
    assert len(enriched) == 2

    # First device: weatherstation with 2 sensors
    ws = enriched[0]
    assert ws["device"] == "weatherstation"
    assert "meta" in ws
    assert len(ws["sensors"]) == 2
    assert ws["sensors"][0]["sensor"] == "precipitation"
    assert ws["sensors"][0]["meta"]["unit"] == "mm"

    # Second device: PAR sensor
    par_dev = enriched[1]
    assert par_dev["device"] == "3672 | PAR"
    assert len(par_dev["sensors"]) == 1
    assert par_dev["sensors"][0]["meta"]["unit"] == "μmol/m²/s"
    # Should include merged intention from device-level sensor
    assert par_dev["sensors"][0]["meta"]["intention"] == "Photosynthetically active radiation"


def test_enrich_omits_empty_meta() -> None:
    """Devices/sensors without metadata should not have a 'meta' key."""
    registry = MetadataRegistry(BLUE_YAML)
    flat = [{"device": "unknown-device", "sensor": "unknown-sensor"}]
    enriched = registry.enrich_sensor_list(flat)

    assert len(enriched) == 1
    assert "meta" not in enriched[0]
    assert "meta" not in enriched[0]["sensors"][0]
