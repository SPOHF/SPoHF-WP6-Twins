"""Tests for device/sensor metadata registry."""

from pathlib import Path

from wp6_data.red.sijia.parser import COLUMN_TO_SENSOR
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


def test_red_chlorophyll_sensor_default_carries_sijia_source() -> None:
    registry = MetadataRegistry(RED_YAML)
    meta = registry.sensor_default("chlorophyll")
    assert meta.source == "sijia"


def test_existing_sensor_without_source_field_defaults_to_empty_string() -> None:
    # Back-compat: yaml entries that pre-date the source field must
    # continue to load cleanly and default source to "" (no routing override).
    registry = MetadataRegistry(RED_YAML)
    par_meta = registry.sensor_default("par")
    assert par_meta.source == ""


def test_red_neurath_devices_are_registered_with_sijia_source() -> None:
    registry = MetadataRegistry(RED_YAML)
    strabelina = registry.device("neurath-B-2034-strabelina")
    shivious = registry.device("neurath-B-2012-shivious")

    assert strabelina.source == "sijia"
    assert strabelina.position == "B"
    assert shivious.source == "sijia"
    assert shivious.position == "B"


def test_every_sijia_parser_sensor_has_a_red_metadata_entry() -> None:
    # SSOT consistency: a parser-emitted sensor that is missing from
    # metadata.yaml would be silently routed back to MySQL by the
    # federated provider. Bind metadata structurally to the parser.
    registry = MetadataRegistry(RED_YAML)
    expected_tags = sorted(set(COLUMN_TO_SENSOR.values()))
    missing = [
        tag for tag in expected_tags if registry.sensor_default(tag).source != "sijia"
    ]
    assert missing == []


# --- Wildcard device matching (data-driven device families) ---------------


def _registry_from_yaml(tmp_path: Path, body: str) -> MetadataRegistry:
    yaml_path = tmp_path / "meta.yaml"
    yaml_path.write_text(body)
    return MetadataRegistry(yaml_path)


def test_wildcard_device_inherits_pattern_position(tmp_path: Path) -> None:
    """A device with no exact entry inherits a matching wildcard pattern."""
    registry = _registry_from_yaml(
        tmp_path,
        'devices:\n  "Org1 / plant *":\n    position: Org1\n',
    )
    assert registry.device("Org1 / plant 12").position == "Org1"
    assert registry.device("Org1 / plant 0").position == "Org1"


def test_exact_device_beats_wildcard(tmp_path: Path) -> None:
    """An exact device key takes precedence over any matching pattern."""
    registry = _registry_from_yaml(
        tmp_path,
        'devices:\n'
        '  "Org1 / plant *":\n    position: Org1\n'
        '  "Org1 / plant 1":\n    position: Special\n',
    )
    assert registry.device("Org1 / plant 1").position == "Special"
    assert registry.device("Org1 / plant 2").position == "Org1"


def test_most_specific_pattern_wins(tmp_path: Path) -> None:
    """When two patterns match, the longest (most specific) one wins."""
    registry = _registry_from_yaml(
        tmp_path,
        'devices:\n'
        '  "Ca / *":\n    position: Broad\n'
        '  "Ca / plant *":\n    position: Narrow\n',
    )
    assert registry.device("Ca / plant 5").position == "Narrow"


def test_no_matching_pattern_returns_empty(tmp_path: Path) -> None:
    """A device matching no exact key or pattern returns empty defaults."""
    registry = _registry_from_yaml(
        tmp_path,
        'devices:\n  "Org1 / plant *":\n    position: Org1\n',
    )
    assert registry.device("K / plant 5") == DeviceMetadata()


def test_wildcard_device_supplies_sensor_intention(tmp_path: Path) -> None:
    """A wildcard device's sensor block enriches matching devices."""
    registry = _registry_from_yaml(
        tmp_path,
        "sensor_defaults:\n"
        '  shoot_length:\n    unit: cm\n'
        "devices:\n"
        '  "Org1 / plant *":\n'
        "    position: Org1\n"
        "    sensors:\n"
        "      shoot_length:\n"
        '        intention: "Cane length"\n',
    )
    meta = registry.sensor("shoot_length", "Org1 / plant 7")
    assert meta.unit == "cm"  # from defaults
    assert meta.intention == "Cane length"  # from the matched wildcard device
