"""Sensor registry — loads the CSV mapping sensor_id → (sensor_tag, device_name)."""

import csv
from dataclasses import dataclass
from pathlib import Path

# CSV lives next to the blue package
_CSV_PATH = Path(__file__).parent.parent / "blue" / "sensor_overview_SPoHF.csv"


@dataclass(frozen=True, slots=True)
class SensorInfo:
    sensor_id: str
    sensor_tag: str
    device_name: str
    device_id: str


class SensorRegistry:
    """In-memory lookup for the sensor CSV."""

    def __init__(self, csv_path: Path = _CSV_PATH) -> None:
        self._by_id: dict[str, SensorInfo] = {}
        self._by_tag: dict[str, list[SensorInfo]] = {}
        self._by_device: dict[str, list[SensorInfo]] = {}
        self._load(csv_path)

    def _load(self, path: Path) -> None:
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                info = SensorInfo(
                    sensor_id=row["sensor_id"].strip(),
                    sensor_tag=row["sensor_tag"].strip(),
                    device_name=row["device_name"].strip(),
                    device_id=row["device_id"].strip(),
                )
                self._by_id[info.sensor_id] = info
                self._by_tag.setdefault(info.sensor_tag, []).append(info)
                self._by_device.setdefault(info.device_name, []).append(info)

    def get(self, sensor_id: str) -> SensorInfo | None:
        return self._by_id.get(sensor_id)

    def all_sensors(self) -> list[SensorInfo]:
        return list(self._by_id.values())

    def by_tag(self, tag: str) -> list[SensorInfo]:
        return self._by_tag.get(tag, [])

    def by_device(self, device_name: str) -> list[SensorInfo]:
        return self._by_device.get(device_name, [])

    def tags(self) -> list[str]:
        return sorted(self._by_tag.keys())

    def devices(self) -> list[str]:
        return sorted(self._by_device.keys())

    def sensors_for_tags(self, tags: list[str]) -> list[SensorInfo]:
        """Return all sensors matching any of the given tags."""
        result = []
        for tag in tags:
            result.extend(self._by_tag.get(tag, []))
        return result

    def sensors_for_devices(self, device_names: list[str]) -> list[SensorInfo]:
        """Return all sensors belonging to any of the given devices."""
        result = []
        for name in device_names:
            result.extend(self._by_device.get(name, []))
        return result
