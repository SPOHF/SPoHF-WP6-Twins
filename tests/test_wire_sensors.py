"""Tests for the red multi-height wire_sensors read path.

The external ``wire_sensors`` table is wide: the four measurement types at five
heights live in 20 columns named ``<measurement><height>`` (e.g. ``par1`` ..
``co25``). ``unpivot_wire_rows`` flattens that into tidy long records. These
tests pin the column-name convention and the sparsity behaviour without needing
a live MySQL connection.
"""

from __future__ import annotations

from datetime import datetime

from wp6_data.red.db import (
    WIRE_SENSOR_HEIGHTS,
    WIRE_SENSOR_MEASUREMENTS,
    unpivot_wire_rows,
    wire_device_id,
    wire_height_from_device,
    wire_physical_id,
    wire_value_columns,
)

TS = datetime(2026, 5, 26, 14, 17, 28)


def _full_row() -> dict:
    """A row with every (measurement, height) cell populated."""
    row: dict = {"device_id": "WS_01_01", "received_at": TS}
    for measurement in WIRE_SENSOR_MEASUREMENTS:
        for height in WIRE_SENSOR_HEIGHTS:
            row[f"{measurement}{height}"] = float(height)
    return row


class TestWireValueColumns:
    def test_count_is_measurements_times_heights(self):
        assert len(wire_value_columns()) == (
            len(WIRE_SENSOR_MEASUREMENTS) * len(WIRE_SENSOR_HEIGHTS)
        )

    def test_naming_convention(self):
        cols = wire_value_columns()
        # No separator between measurement and height index, e.g. co2 + 5 -> "co25"
        assert "par1" in cols
        assert "co25" in cols


class TestUnpivotWireRows:
    def test_full_row_yields_every_cell(self):
        records = unpivot_wire_rows([_full_row()])
        assert len(records) == len(WIRE_SENSOR_MEASUREMENTS) * len(WIRE_SENSOR_HEIGHTS)

    def test_record_shape_and_mapping(self):
        records = unpivot_wire_rows([_full_row()])
        # Each height's value was set to the height number, so mapping is verifiable.
        co2_h3 = next(
            r for r in records if r["measurement"] == "co2" and r["height"] == 3
        )
        assert co2_h3 == {
            "device": "WS_01_01-h3",
            "height": 3,
            "measurement": "co2",
            "time": TS,
            "value": 3.0,
        }

    def test_height_becomes_virtual_device(self):
        records = unpivot_wire_rows([_full_row()])
        devices = {r["device"] for r in records}
        assert devices == {f"WS_01_01-h{h}" for h in WIRE_SENSOR_HEIGHTS}

    def test_empty_cells_are_skipped(self):
        # Mirrors the real example row: only par at height 1, full temp/hum/co2.
        row = {"device_id": "WS_01_01", "received_at": TS, "par1": 7.0}
        for measurement in ("temp", "hum", "co2"):
            for height in WIRE_SENSOR_HEIGHTS:
                row[f"{measurement}{height}"] = 10.0

        records = unpivot_wire_rows([row])

        par_records = [r for r in records if r["measurement"] == "par"]
        assert len(par_records) == 1
        assert par_records[0]["height"] == 1
        # 1 PAR + 5 each for the three full measurements
        assert len(records) == 1 + 3 * len(WIRE_SENSOR_HEIGHTS)

    def test_values_are_cast_to_float(self):
        row = {"received_at": TS, "par1": "7.000"}
        records = unpivot_wire_rows([row])
        assert records[0]["value"] == 7.0
        assert isinstance(records[0]["value"], float)

    def test_no_rows_yields_no_records(self):
        assert unpivot_wire_rows([]) == []


class TestGreenhouseLayout:
    def test_svg_box_and_band_ids_match_heights(self):
        """The greenhouse SVG ids must be height_N, one box + band per height.

        Boxes (latest value) and bands (per-height DLI) are looked up by these
        ids, which `compute_sensor_metrics` reproduces as `height_{n}`.
        """
        from wp6_data.red.multi_height.svg import SVG_LAYOUT_PATH, parse_svg

        _, _, boxes, bands = parse_svg(SVG_LAYOUT_PATH)
        expected = {f"height_{h}" for h in WIRE_SENSOR_HEIGHTS}

        assert set(boxes) == expected
        assert set(bands) == expected


class TestComputeSensorMetrics:
    """The greenhouse view's per-height metric, driven by the measurement toggle."""

    @staticmethod
    def _df():
        import pandas as pd

        rows = []
        for measurement, base in (("par", 100.0), ("temp", 25.0)):
            for i, minute in enumerate((0, 30)):
                rows.append({
                    "device": "WS_01_01-h1",
                    "height": 1,
                    "measurement": measurement,
                    "time": pd.Timestamp(f"2026-05-26T12:{minute:02d}:00", tz="UTC"),
                    "value": base + i,
                })
        return pd.DataFrame(rows)

    def test_selects_chosen_measurement_and_skips_dli(self):
        import pandas as pd

        from wp6_data.red.multi_height.data import compute_sensor_metrics

        metrics = compute_sensor_metrics(self._df(), "temp", "WS_01_01")
        h1 = metrics[metrics["sensor_id"] == "height_1"].iloc[0]
        assert h1["latest_value"] == 26.0          # latest temp reading
        assert pd.isna(h1["dli_today"])            # DLI is PAR-only

    def test_par_gets_dli_aggregate(self):
        import pandas as pd

        from wp6_data.red.multi_height.data import compute_sensor_metrics

        metrics = compute_sensor_metrics(self._df(), "par", "WS_01_01")
        h1 = metrics[metrics["sensor_id"] == "height_1"].iloc[0]
        assert h1["latest_value"] == 101.0
        assert not pd.isna(h1["dli_today"])


class TestWireDeviceId:
    def test_round_trip(self):
        for height in WIRE_SENSOR_HEIGHTS:
            device = wire_device_id("WS_01_01", height)
            assert wire_height_from_device(device) == height

    def test_non_wire_id_has_no_height(self):
        assert wire_height_from_device("s2100-01-par") is None

    def test_physical_id_strips_height_suffix(self):
        assert wire_physical_id("WS_01_02-h4") == "WS_01_02"
        assert wire_physical_id("s2100-01-par") == "s2100-01-par"


class TestWireEnumeration:
    def test_wire_ids_lists_declared_wires(self):
        """Every wire declared in metadata is enumerated, de-duped, sorted."""
        from wp6_data.red.multi_height.data import wire_ids

        assert wire_ids() == ["WS_01_01", "WS_01_02", "WS_01_03"]


class TestUndeclaredWireDrift:
    """A wire reporting into wire_sensors but missing from metadata is invisible
    to every view, since views enumerate wires from metadata. Startup warns."""

    @staticmethod
    def _summary(*physical_ids: str) -> dict:
        return {
            wire_device_id(physical_id, height): {"readings": 1, "last_seen": TS}
            for physical_id in physical_ids
            for height in WIRE_SENSOR_HEIGHTS
        }

    async def _undeclared_for(self, monkeypatch, summary):
        from wp6_data.red import deps
        from wp6_data.red.multi_height.data import undeclared_wire_ids

        class _StubDb:
            async def get_wire_device_summary(self):
                return summary

        monkeypatch.setattr(deps, "db", _StubDb())
        return await undeclared_wire_ids()

    async def test_reporting_wire_missing_from_metadata_is_flagged(self, monkeypatch):
        summary = self._summary("WS_01_01", "WS_99_99")
        assert await self._undeclared_for(monkeypatch, summary) == ["WS_99_99"]

    async def test_all_declared_wires_reporting_is_no_drift(self, monkeypatch):
        from wp6_data.red.multi_height.data import wire_ids

        summary = self._summary(*wire_ids())
        assert await self._undeclared_for(monkeypatch, summary) == []

    async def test_declared_wire_not_yet_reporting_is_not_drift(self, monkeypatch):
        """Drift is one-directional: a silent wire is a sensor problem, not config."""
        summary = self._summary("WS_01_01")
        assert await self._undeclared_for(monkeypatch, summary) == []
