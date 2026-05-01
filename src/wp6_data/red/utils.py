import base64
import re
from pathlib import Path

import pandas as pd
from plotly.colors import sample_colorscale

GREENHOUSE_TZ = "Europe/Berlin"

PAR_COLORSCALE = [
    [0.00, "#fff7bc"],
    [0.25, "#fee391"],
    [0.50, "#fec44f"],
    [0.75, "#fe9929"],
    [1.00, "#cc4c02"],
]

SENSOR_TO_DEVICE = {
    "s_01": "s2100:s2100-01-par",
    "s_02": "s2100:s2100-02-par",
    "s_10": "s2100:s2100-10-par",
    "s_11": "s2100:s2100-11-par",
    "s_12": "s2100:s2100-12-par",
    "s_13": "s2100:s2100-13-par",
    "s_14": "s2100:s2100-14-par",
}


def svg_to_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:image/svg+xml;base64,{encoded}"


def svg_rect_to_plotly_rect(rect, canvas_h):
    x0 = rect["x"]
    x1 = rect["x"] + rect["width"]

    y0 = canvas_h - (rect["y"] + rect["height"])
    y1 = canvas_h - rect["y"]

    return x0, x1, y0, y1


def value_to_color(value, vmin, vmax, colorscale=PAR_COLORSCALE, alpha=None):

    if value is None or pd.isna(value):
        return "rgba(180,180,180,0.45)"

    if vmax <= vmin:
        t = 0.5
    else:
        t = max(0, min(1, (value - vmin) / (vmax - vmin)))

    color = sample_colorscale(colorscale, [t])[0]

    if alpha is None:
        return color

    nums = re.findall(r"\d+", color)
    r, g, b = nums[:3]
    return f"rgba({r},{g},{b},{alpha})"