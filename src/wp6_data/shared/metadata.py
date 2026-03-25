"""Device and sensor metadata registry.

Loads manually-enriched metadata from a per-twin YAML file and provides
lookup + API enrichment helpers. Complements the dynamic sensor lists
from the database (cached by sensor_summary.py) with static descriptive
information that rarely changes.

YAML structure::

    sensor_defaults:          # shared unit/alias/type for measurement keys
      par:
        type: radiation
        unit: "μmol/m²/s"
        alias: PAR

    devices:                  # each device lists its sensors inline
      s2100-01-par:
        description: "PAR above lamp level"
        position: B4
        sensors:
          par:                # inherits from sensor_defaults, can override
            intention: "Measures PAR above grow lamp"
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import yaml
from pydantic import BaseModel


class SensorMetadata(BaseModel):
    """Metadata for a sensor / measurement type."""

    type: str = ""
    unit: str = ""
    alias: str = ""
    intention: str = ""


class DeviceMetadata(BaseModel):
    """Metadata for a physical device and its location."""

    description: str = ""
    position: str = ""
    latitude: float | None = None
    longitude: float | None = None
    type: str = ""
    sensors: dict[str, SensorMetadata] = {}


class TwinMetadata(BaseModel):
    """Complete metadata for one digital twin, loaded from YAML."""

    sensor_defaults: dict[str, SensorMetadata] = {}
    devices: dict[str, DeviceMetadata] = {}


class MetadataRegistry:
    """Loads and serves device/sensor metadata from a YAML file."""

    def __init__(self, yaml_path: Path) -> None:
        if yaml_path.exists():
            with yaml_path.open() as f:
                raw = yaml.safe_load(f) or {}
            self._meta = TwinMetadata(**raw)
        else:
            self._meta = TwinMetadata()

    def device(self, device_key: str) -> DeviceMetadata:
        """Return metadata for a device, or empty defaults if not enriched."""
        return self._meta.devices.get(device_key, DeviceMetadata())

    def sensor_default(self, sensor_key: str) -> SensorMetadata:
        """Return the global default metadata for a measurement key."""
        return self._meta.sensor_defaults.get(sensor_key, SensorMetadata())

    def sensor(
        self, sensor_key: str, device_key: str | None = None,
    ) -> SensorMetadata:
        """Return merged sensor metadata (device-specific over defaults).

        Fields set on the device-level sensor override the defaults.
        """
        defaults = self.sensor_default(sensor_key)
        if device_key is None:
            return defaults

        dev = self._meta.devices.get(device_key)
        if dev is None:
            return defaults

        override = dev.sensors.get(sensor_key)
        if override is None:
            return defaults

        # Merge: override wins for non-default fields
        merged = defaults.model_dump()
        for field, value in override.model_dump(exclude_defaults=True).items():
            merged[field] = value
        return SensorMetadata(**merged)

    def sensor_types(self) -> dict[str, list[str]]:
        """Return mapping of sensor type → list of sensor keys.

        Built from sensor_defaults. Useful for home page grouping.
        """
        types: dict[str, list[str]] = defaultdict(list)
        for key, meta in self._meta.sensor_defaults.items():
            if meta.type:
                types[meta.type].append(key)
        return dict(types)

    def enrich_sensor_list(
        self, flat_sensors: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        """Group a flat sensor list by device and attach metadata.

        Input:  [{"device": "d1", "sensor": "s1"}, ...]
        Output: nested by device with metadata attached.
        """
        grouped: dict[str, list[str]] = defaultdict(list)
        device_order: list[str] = []
        for entry in flat_sensors:
            dev = entry["device"]
            if dev not in grouped:
                device_order.append(dev)
            grouped[dev].append(entry["sensor"])

        result: list[dict[str, Any]] = []
        for dev in device_order:
            dev_obj = self.device(dev)
            device_meta = dev_obj.model_dump(
                exclude_defaults=True, exclude={"sensors"},
            )
            sensors = []
            for sensor_key in grouped[dev]:
                merged = self.sensor(sensor_key, dev)
                sensor_meta = merged.model_dump(exclude_defaults=True)
                entry: dict[str, Any] = {"sensor": sensor_key}
                if sensor_meta:
                    entry["meta"] = sensor_meta
                sensors.append(entry)

            device_entry: dict[str, Any] = {"device": dev, "sensors": sensors}
            if device_meta:
                device_entry["meta"] = device_meta
            result.append(device_entry)

        return result
