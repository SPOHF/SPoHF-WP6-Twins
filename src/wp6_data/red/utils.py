import base64
import pathlib
import re

import pandas as pd  # type: ignore[import-untyped]
from plotly.colors import sample_colorscale  # type: ignore[import-untyped]

PAR_COLORSCALE = [
    [0.00, "#fff7bc"],
    [0.25, "#fee391"],
    [0.50, "#fec44f"],
    [0.75, "#fe9929"],
    [1.00, "#cc4c02"],
]

# Greenhouse SVG box ids encode the height directly (``height_1`` .. ``height_5``);
# the wire device is derived from the selected wire + height (ADR 0001), so no
# fixed box→device map is needed here.


def svg_to_data_uri(path: pathlib.Path) -> str:
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

    t = 0.5 if vmax <= vmin else max(0, min(1, (value - vmin) / (vmax - vmin)))

    color = sample_colorscale(colorscale, [t])[0]

    if alpha is None:
        return color

    nums = re.findall(r"\d+", color)
    r, g, b = nums[:3]
    return f"rgba({r},{g},{b},{alpha})"