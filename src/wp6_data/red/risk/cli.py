"""CLI: ``wp6-red-eval-risk`` — evaluate prescriptive risk over wire data.

Read-only. Fetches multi-height wire readings for a date range + wire, runs the
pure risk engine, and prints per-section state + risk episodes. Runs locally or
against prod (it uses the same red DB settings as the app); it writes nothing.
This is the CLI-first validation path for the still-provisional thresholds —
inspect the output, retune ``risk_thresholds`` in ``metadata.yaml``, re-run.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import pandas as pd

from wp6_data.red import deps
from wp6_data.red.db import MySQLConnection, wire_physical_id
from wp6_data.red.risk.config import load_risk_thresholds
from wp6_data.red.risk.engine import RiskEvaluation, evaluate
from wp6_data.shared.compat import run_async


def _wire_ids() -> list[str]:
    return sorted({
        wire_physical_id(device_id)
        for device_id, meta in deps.metadata.devices.items()
        if meta.type == "wire"
    })


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="wp6-red-eval-risk",
        description="Evaluate prescriptive risk over multi-height wire data (read-only).",
    )
    p.add_argument("--wire", help="Wire id (e.g. WS_01_01); default: first declared")
    p.add_argument(
        "--start", type=date.fromisoformat,
        help="Range start YYYY-MM-DD (default: 7 days ago)",
    )
    p.add_argument(
        "--end", type=date.fromisoformat,
        help="Range end YYYY-MM-DD (default: today)",
    )
    return p.parse_args(argv)


async def _load_wire(start_utc, end_utc) -> pd.DataFrame:
    db = MySQLConnection(
        deps.DB_HOST, deps.DB_PORT, deps.DB_USER, deps.DB_PASSWORD, deps.DB_NAME,
    )
    await db.connect()
    try:
        return await db.get_wire_sensor_readings(start=start_utc, end=end_utc)
    finally:
        await db.close()


def format_evaluation(
    result: RiskEvaluation, wire: str, start_day: date, end_day: date,
) -> str:
    """Render an evaluation as plain text (pure — used by the CLI and tests)."""
    lines = [
        f"Risk evaluation — wire {wire}, {start_day}..{end_day}",
        "",
        "Sections (latest state):",
    ]
    for s in result.states:
        dli = "—" if s.height_dli is None else f"{s.height_dli:.1f}"
        vpd = "—" if s.vpd_latest is None else f"{s.vpd_latest:.2f}"
        wet = "—" if s.wet_hours_latest is None else f"{s.wet_hours_latest:.1f}"
        flags = []
        if s.fungal_active:
            flags.append("FUNGAL")
        if s.vpd_in_band is False:
            flags.append("VPD-OOB")
        if s.canopy_deficit:
            flags.append("LIGHT-DEFICIT")
        lines.append(
            f"  H{s.height} {s.label:<22} DLI={dli:>6} VPD={vpd:>5} "
            f"wetH={wet:>5}  {' '.join(flags)}"
        )

    lines += ["", f"Episodes ({len(result.episodes)}):"]
    for e in sorted(result.episodes, key=lambda e: (e.start, e.height, e.risk)):
        end = e.end.isoformat() if e.end else "ongoing"
        lines.append(
            f"  H{e.height} {e.risk:<7} {e.start.isoformat()} -> {end}  "
            f"peak={e.peak:.2f}  thresholds={e.thresholds}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    tz = deps.base_settings.display_timezone

    wires = _wire_ids()
    wire = args.wire or (wires[0] if wires else "")
    end_day = args.end or date.today()
    start_day = args.start or (end_day - timedelta(days=7))

    start_utc = pd.Timestamp(start_day, tz=tz).tz_convert("UTC").to_pydatetime()
    end_utc = (
        (pd.Timestamp(end_day, tz=tz) + pd.Timedelta(days=1))
        .tz_convert("UTC")
        .to_pydatetime()
    )

    df = run_async(_load_wire(start_utc, end_utc))
    if not df.empty:
        df = df[df["device"].map(wire_physical_id) == wire]

    thresholds = load_risk_thresholds(deps._METADATA_PATH)
    result = evaluate(df, deps.growth_sections, thresholds)
    print(format_evaluation(result, wire, start_day, end_day))
    return 0


if __name__ == "__main__":
    sys.exit(main())
