"""HTML cell/badge builders for the red "Crop Climate by Height" (prescriptive) page.

The grid is dense (5×4 trends), so cells use lightweight inline-SVG sparklines
(no per-cell plotly) plus the latest value. Every cell builder takes a series
the view-model already computed (``*_from_values``), so the page never computes
a series twice and the cells stay free of climate maths.
"""

import html
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd  # type: ignore[import-untyped]

from wp6_data.shared import render_card

from ..utils import value_to_color

MEASUREMENT_COLORS = {
    "par": "#f59e0b",
    "temp": "#ef4444",
    "hum": "#06b6d4",
    "co2": "#8b5cf6",
}

# Display name + unit per measurement type, keyed by the db measurement key.
WIRE_MEASUREMENT_LABELS = {
    "par": ("PAR", "µmol/m²/s"),
    "temp": ("Temperature", "°C"),
    "hum": ("Humidity", "%RH"),
    "co2": ("CO₂", "ppm"),
}

# The plant rail is a single rowspanned SVG; aligning it to rows means each body
# row is exactly CROP_ROW_HEIGHT tall and the SVG is len(sections) * that.
CROP_ROW_HEIGHT = 72
PLANT_SVG_PATH = Path(__file__).parent.parent / "static/crop_plant.svg"


def plant_zone_cell(index: int, total: int, uri: str) -> str:
    """Left rail: this row's vertical slice of the plant SVG.

    The full SVG is cropped to the row's zone via a negative offset, so the rows
    together reconstruct the whole plant while each row stays independent (a
    detail row can expand between rows without breaking a rowspan).
    """
    return (
        '<td style="padding:0;width:90px;vertical-align:middle;">'
        f'<div style="height:{CROP_ROW_HEIGHT}px;width:80px;overflow:hidden;margin:auto;">'
        f'<img src="{uri}" width="80" height="{total * CROP_ROW_HEIGHT}" '
        f'style="display:block;margin-top:-{index * CROP_ROW_HEIGHT}px;"></div></td>'
    )


def sparkline_svg(values, color, width=96, height=28):
    """Minimal inline-SVG sparkline (no JS), self-normalised to its own range."""
    pts = [float(v) for v in values if v is not None and not pd.isna(v)]
    if len(pts) < 2:
        return '<span style="color:#9ca3af;">—</span>'
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    last = len(pts) - 1
    coords = " ".join(
        f"{(i / last) * (width - 2) + 1:.1f},"
        f"{height - 1 - ((v - lo) / span) * (height - 2):.1f}"
        for i, v in enumerate(pts)
    )
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'style="display:block;">'
        f'<polyline points="{coords}" fill="none" stroke="{color}" '
        'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def _cell_open(height, metric, extra_style="") -> str:
    """Opening <td> for a clickable cell (expands a line chart on click)."""
    return (
        f'<td data-height="{height}" data-metric="{metric}" '
        'onclick="ccChart(this)" title="Click to expand a chart" '
        f'style="padding:0.5rem 0.75rem;vertical-align:middle;cursor:pointer;{extra_style}">'
    )


# CO₂ is the one measured quantity with a physically meaningful absolute floor
# (≈ambient), so its sparkline marks the carbon-limitation floor where the others
# stay deliberately threshold-free. Red = the depletion zone below the floor.
CO2_FLOOR_COLOR = "#dc2626"


def _co2_sparkline_svg(values, floor, width=96, height=28):
    """CO₂ sparkline with the depletion floor drawn and the below-floor zone shaded.

    The domain spans the day's CO₂ *and* the floor, so the dashed floor line is
    always in view; a faint red wash below it reads as "carbon-limited" at a
    glance. The line itself stays CO₂-purple to match the column. (The actual
    risk verdict is daylight-gated in the engine; this is a visual aid.)
    """
    pts = [float(v) for v in values if v is not None and not pd.isna(v)]
    if len(pts) < 2:
        return '<span style="color:#9ca3af;">—</span>'
    lo, hi = min(min(pts), floor), max(max(pts), floor)
    span = (hi - lo) or 1.0
    last = len(pts) - 1

    def _y(val):
        return height - 1 - ((val - lo) / span) * (height - 2)

    floor_y = _y(floor)
    coords = " ".join(
        f"{(i / last) * (width - 2) + 1:.1f},{_y(v):.1f}" for i, v in enumerate(pts)
    )
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'style="display:block;">'
        f'<rect x="0" y="{floor_y:.1f}" width="{width}" '
        f'height="{height - floor_y:.1f}" fill="{CO2_FLOOR_COLOR}" opacity="0.12"/>'
        f'<line x1="0" y1="{floor_y:.1f}" x2="{width}" y2="{floor_y:.1f}" '
        f'stroke="{CO2_FLOOR_COLOR}" stroke-width="0.75" stroke-dasharray="3 2" '
        'opacity="0.6"/>'
        f'<polyline points="{coords}" fill="none" stroke="{MEASUREMENT_COLORS["co2"]}" '
        'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def format_reading(value: float) -> str:
    """Box label: whole numbers for large readings, one decimal for small."""
    return f"{value:.0f}" if abs(value) >= 100 else f"{value:.1f}"


def measurement_cell(series, measurement, vmin, vmax, height, co2_floor=None):
    """A clickable measured cell: latest value (+ unit) above the day's sparkline.

    Background is a relative tint (white→measurement-colour by rank within the
    column), so colour means "high/low vs the other heights", never an absolute
    threshold. Clicking expands a line chart for this height + measurement. CO₂ is
    the exception: when ``co2_floor`` is given its sparkline marks that floor.
    """
    _, unit = WIRE_MEASUREMENT_LABELS[measurement]
    latest = series[-1] if series else None
    value = "—" if latest is None else f"{format_reading(latest)} {unit}"
    scale = [[0.0, "#ffffff"], [1.0, MEASUREMENT_COLORS[measurement]]]
    bg = value_to_color(latest, vmin, vmax, colorscale=scale, alpha=0.5)
    spark = (
        _co2_sparkline_svg(series, co2_floor)
        if measurement == "co2" and co2_floor is not None
        else sparkline_svg(series, MEASUREMENT_COLORS[measurement])
    )
    return (
        _cell_open(height, measurement, f"background:{bg};")
        + f'<div style="font-weight:600;font-size:0.9rem;">{value}</div>'
        + spark
        + "</td>"
    )


### Derived risk columns (issue 016) — threshold-free trends, computed on read ###
# Derived metrics share their source measurement's colour to show the lineage:
# DLI ← PAR, Fungal ← Humidity. VPD ← Temp + Humidity, so it gets a red→cyan
# gradient (two parents) rather than a single colour.
HEIGHT_DLI_COLOR = MEASUREMENT_COLORS["par"]
FUNGAL_COLOR = MEASUREMENT_COLORS["hum"]
VPD_LINE_COLOR = "#0ea5e9"
# Display name + unit per derived metric, keyed like the measured ones above so
# a caller holding any of the seven metric keys can label it without knowing
# which kind it is. The table's derived headers are read straight off this, so a
# renamed column and its chart title can never drift apart.
DERIVED_METRIC_LABELS = {
    "dli": ("Height DLI", "mol/m²"),
    "vpd": ("VPD", "kPa"),
    "fungal": ("Fungal risk", "h"),
}
METRIC_LABELS = {**WIRE_MEASUREMENT_LABELS, **DERIVED_METRIC_LABELS}
DERIVED_COLUMNS = [label for label, _ in DERIVED_METRIC_LABELS.values()]

# One colour per metric, so a metric reads the same on every multi-height page.
# The derived ones inherit their source's hue (see the lineage note below).

# Every metric's line colour in one lookup, so a caller holding any of the seven
# keys can draw it without knowing whether it is measured or derived.
METRIC_COLORS = {
    **MEASUREMENT_COLORS,
    "dli": HEIGHT_DLI_COLOR,
    "vpd": VPD_LINE_COLOR,
    "fungal": FUNGAL_COLOR,
}

# Vertical separator between the measured (left) and derived (right) blocks.
SEP_BORDER = "border-left:2px solid #cbd5e1;"
_VPD_GRADIENT = (
    f"linear-gradient(90deg,{MEASUREMENT_COLORS['temp']},{MEASUREMENT_COLORS['hum']})"
)
# Inline style for a derived value's text (its lineage colour).
DERIVED_VALUE_STYLE = {
    "dli": f"color:{HEIGHT_DLI_COLOR};",
    "vpd": f"background:{_VPD_GRADIENT};-webkit-background-clip:text;"
           "background-clip:text;color:transparent;",
    "fungal": f"color:{FUNGAL_COLOR};",
}
# Coloured header underlines tying each derived column to its source(s).
DERIVED_HEADER_ACCENTS = {
    "Height DLI": f"border-bottom:3px solid {HEIGHT_DLI_COLOR};{SEP_BORDER}",
    "VPD": f"border-width:0 0 3px;border-style:solid;border-image:{_VPD_GRADIENT} 1;",
    "Fungal risk": f"border-bottom:3px solid {FUNGAL_COLOR};",
}


def _derived_cell(value: str, spark: str, height, metric: str) -> str:
    # The first derived column (DLI) carries the vertical separator border.
    td = _cell_open(height, metric, SEP_BORDER if metric == "dli" else "")
    vstyle = DERIVED_VALUE_STYLE.get(metric, "")
    return (
        td
        + f'<div style="font-weight:600;font-size:0.9rem;{vstyle}">{value}</div>'
        + f"{spark}</td>"
    )


def vpd_sparkline_svg(values, band_min, band_max, width=96, height=28):
    """VPD sparkline on a fixed 0..max scale with the healthy band shaded.

    Unlike the self-normalising raw sparkline, this fixes the y-domain so the
    band rectangle is stable across cells and excursions read consistently.
    """
    pts = [float(v) for v in values if v is not None and not pd.isna(v)]
    if len(pts) < 2:
        return '<span style="color:#9ca3af;">—</span>'
    vmax = (max(max(pts), band_max) * 1.05) or 1.0
    last = len(pts) - 1

    def _y(val):
        return height - 1 - (val / vmax) * (height - 2)

    band_top = _y(band_max)
    band_h = max(0.0, _y(band_min) - band_top)
    coords = " ".join(
        f"{(i / last) * (width - 2) + 1:.1f},{_y(v):.1f}" for i, v in enumerate(pts)
    )
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'style="display:block;">'
        f'<rect x="0" y="{band_top:.1f}" width="{width}" height="{band_h:.1f}" '
        'fill="#16a34a" opacity="0.15"/>'
        f'<polyline points="{coords}" fill="none" stroke="{VPD_LINE_COLOR}" '
        'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def height_dli_cell_from_values(values, height):
    """Height-DLI cell from a precomputed cumulative-DLI value series."""
    if not values:
        return _derived_cell("—", sparkline_svg([], HEIGHT_DLI_COLOR), height, "dli")
    return _derived_cell(
        f"{values[-1]:.1f} mol", sparkline_svg(values, HEIGHT_DLI_COLOR), height, "dli"
    )


def vpd_cell_from_values(values, band_min, band_max, height):
    """VPD cell from a precomputed VPD value series (kPa)."""
    if not values:
        return _derived_cell("—", '<span style="color:#9ca3af;">—</span>', height, "vpd")
    return _derived_cell(
        f"{values[-1]:.2f} kPa", vpd_sparkline_svg(values, band_min, band_max),
        height, "vpd",
    )


def fungal_cell_from_values(values, height):
    """Fungal wet-hours cell from a precomputed (day-trimmed) wet-hours series."""
    if not values:
        return _derived_cell("—", sparkline_svg([], FUNGAL_COLOR), height, "fungal")
    return _derived_cell(
        f"{values[-1]:.1f} h", sparkline_svg(values, FUNGAL_COLOR), height, "fungal"
    )


def section_label_cell(section, state, vpd_band_min, vpd_band_max):
    """Growth-section label, with any active-risk badges beneath it."""
    badges = section_badges(state, vpd_band_min, vpd_band_max)
    badge_html = f'<div style="margin-top:4px;">{badges}</div>' if badges else ""
    return (
        '<td style="padding:0.5rem 0.75rem;font-weight:600;white-space:nowrap;">'
        f'<span style="color:#6b7280;">H{section.height}</span> · '
        f"{html.escape(section.label)}{badge_html}</td>"
    )


### Risk verdict + admin build (issue 015) ###
def _badge(text: str, color: str, tip: str = "") -> str:
    style = (
        f"background:{color};color:#fff;border-radius:6px;"
        "padding:2px 8px;font-size:0.8rem;margin-right:4px;"
    )
    if not tip:
        return f'<span style="{style}">{html.escape(text)}</span>'
    return (
        f'<span class="cc-badge" style="{style}">{html.escape(text)}'
        f'<span class="cc-tip">{html.escape(tip)}</span></span>'
    )


def section_badges(state, vpd_band_min, vpd_band_max) -> str:
    """Prescriptive active-risk badges for a section from its persisted state.

    Each badge names the *action*, with a tooltip explaining why. Only active
    risks render (no "OK"), so a healthy section stays clean. Empty when state is
    absent or nothing is flagged. The VPD badge is directional — the state's
    latest VPD vs the band decides whether the air is too dry or too humid.
    """
    if not state:
        return ""
    badges = []
    if state.get("canopy_deficit"):
        badges.append(_badge(
            "Add light", "#b45309",
            "Canopy DLI below target — add supplemental light or extend the photoperiod",
        ))
    if state.get("fungal_active"):
        badges.append(_badge(
            "Dry the air", "#7c3aed",
            "Humidity has stayed high too long — Botrytis/fungal pressure; "
            "ventilate or add heat to dry the canopy",
        ))
    if state.get("co2_depleted"):
        badges.append(_badge(
            "Enrich CO₂", "#0d9488",
            "CO₂ below the floor while the canopy is lit — the crop is "
            "carbon-limited; enrich CO₂ or reduce venting",
        ))
    if state.get("vpd_in_band") is False:
        vpd = state.get("vpd_latest")
        if vpd is not None and vpd > vpd_band_max:
            badges.append(_badge(
                "Raise humidity", "#b91c1c",
                "VPD above the healthy band — air too dry; raise humidity "
                "(misting/fogging) or lower temperature",
            ))
        else:
            badges.append(_badge(
                "Ventilate", "#b91c1c",
                "VPD below the healthy band — air too humid; ventilate or "
                "raise temperature",
            ))
    return "".join(badges)


def admin_build_panel(wire: str, day: date) -> str:
    """Admin-only Update (to now) + Rebuild (date range) build controls."""
    update_form = (
        '<form method="post" action="/multi_height/crop-climate/update" '
        'style="display:inline;">'
        f'<input type="hidden" name="wire" value="{wire}">'
        '<button type="submit">Update (to now)</button></form>'
    )
    rebuild_form = (
        '<form method="post" action="/multi_height/crop-climate/rebuild" '
        'style="display:flex;gap:8px;align-items:flex-end;margin-top:8px;'
        'flex-wrap:wrap;">'
        f'<input type="hidden" name="wire" value="{wire}">'
        f'<label>From<br><input type="date" name="start" value="{day.isoformat()}"></label>'
        f'<label>To<br><input type="date" name="end" value="{day.isoformat()}"></label>'
        '<button type="submit">Rebuild range</button></form>'
    )
    audit_link = (
        '<p style="margin-top:10px;">'
        f'<a href="/multi_height/crop-climate/audit?wire={wire}">Open risk log →</a>'
        "</p>"
    )
    return render_card(
        "Admin — build risk log",
        update_form + rebuild_form + audit_link,
        description="Update extends the log to now; Rebuild recomputes a date "
        "range from raw data. Runs on demand.",
        card_class="card",
    )


### Risk-episode audit log (issue 018) ###
RISK_LABELS = {
    "vpd": "VPD out of band",
    "fungal": "Fungal risk",
    "co2": "CO₂ depletion",
    "canopy": "Canopy light deficit",
}


def fmt_local(dt, tz: str) -> str:
    """Render a tz-aware datetime in the display timezone, e.g. '2026-06-03 20:18 CEST'.

    Cache/audit timestamps are stored as ``TIMESTAMPTZ`` (UTC), so this is a pure
    presentation convert to ``WP6_DISPLAY_TIMEZONE``; ``%Z`` tracks DST itself.
    """
    return dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M %Z")


def _fmt_duration(td) -> str:
    """Human duration like '1d 3h' / '2h 30m' / '45m'."""
    total = int(td.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins or not parts:
        parts.append(f"{mins}m")
    return " ".join(parts)


def audit_table(episodes, tz: str = "UTC") -> str:
    """Render persisted risk episodes (cache dicts) as an HTML table.

    Episode timestamps are stored in UTC and shown in ``tz`` (the display
    timezone) so the log reads in local wall-clock like the rest of the view.
    """
    if not episodes:
        return (
            '<p style="color:#6b7280;">No risk episodes in this range — build the '
            "log from the Crop Climate page first.</p>"
        )
    headers = ("Section", "Risk", "Present from", "Resolved", "Duration", "Peak",
               "Thresholds")
    head = "<thead><tr>" + "".join(
        f'<th style="padding:0.4rem 0.75rem;text-align:left;">{h}</th>'
        for h in headers
    ) + "</tr></thead>"

    rows = ""
    for e in episodes:
        start, end = e["start_time"], e["end_time"]
        resolved = (
            fmt_local(end, tz) if end is not None
            else '<em style="color:#b45309;">ongoing</em>'
        )
        duration = _fmt_duration(end - start) if end is not None else "—"
        cells = [
            f'H{e["height"]} {html.escape(e["label"])}',
            html.escape(RISK_LABELS.get(e["risk"], e["risk"])),
            fmt_local(start, tz),
            resolved,
            duration,
            f'{e["peak"]:.2f}',
            f'<code style="font-size:0.8rem;">{html.escape(str(e["thresholds"]))}</code>',
        ]
        rows += (
            "<tr style='border-top:1px solid #e5e7eb;'>"
            + "".join(f'<td style="padding:0.4rem 0.75rem;">{c}</td>' for c in cells)
            + "</tr>"
        )
    return (
        '<table style="width:100%;border-collapse:collapse;">'
        f"{head}<tbody>{rows}</tbody></table>"
    )
