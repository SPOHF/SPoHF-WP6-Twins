import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from .. import deps
from ..utils import (
    GREENHOUSE_TZ,
    SENSOR_TO_DEVICE,
    svg_rect_to_plotly_rect,
    svg_to_data_uri,
    value_to_color,
)

SVG_PATH = Path(__file__).parent.parent / "static/par_profile.svg"
USE_LATEST_DATE_IN_DATA = False

router = APIRouter()

@router.get("/par-profile", response_class=HTMLResponse)
async def par_profile_page():
    df = await load_par_data()

    df_today, target_day = filter_today(df)
    metrics = compute_sensor_metrics(df_today)

    canvas_w, canvas_h, sensor_boxes, sensor_bands = parse_svg(SVG_PATH)

    fig = make_par_greenhouse_plot(
        metrics,
        canvas_w,
        canvas_h,
        sensor_boxes,
        sensor_bands,
        target_day,
    )

    return HTMLResponse(fig.to_html(include_plotlyjs="cdn"))

### Parse SVG ###
def parse_viewbox(svg_path: Path):
    root = ET.parse(svg_path).getroot()
    viewbox = root.attrib.get("viewBox")

    if viewbox:
        x, y, w, h = map(float, viewbox.split())
        return x, y, w, h

    width = float(re.sub(r"[^0-9.]", "", root.attrib["width"]))
    height = float(re.sub(r"[^0-9.]", "", root.attrib["height"]))
    return 0.0, 0.0, width, height


def parse_svg_rects(svg_path: Path):
    ns = {"svg": "http://www.w3.org/2000/svg"}
    root = ET.parse(svg_path).getroot()

    rects = {}

    for rect in root.findall(".//svg:rect", ns):
        rect_id = rect.attrib.get("id")
        if not rect_id:
            continue

        rects[rect_id] = {
            "x": float(rect.attrib.get("x", 0)),
            "y": float(rect.attrib.get("y", 0)),
            "width": float(rect.attrib.get("width", 0)),
            "height": float(rect.attrib.get("height", 0)),
            "rx": rect.attrib.get("rx"),
        }

    return rects

def parse_svg(svg_path: Path):
    _, _, canvas_w, canvas_h = parse_viewbox(svg_path)
    rects = parse_svg_rects(svg_path)

    sensor_boxes = {
        k: v for k, v in rects.items()
        if k.startswith("s_") and not k.endswith("_bg")
    }

    sensor_bands = {
        k.replace("_bg", ""): v for k, v in rects.items()
        if k.startswith("s_") and k.endswith("_bg")
    }

    return canvas_w, canvas_h, sensor_boxes, sensor_bands


### Load data ###
async def load_par_data():
    df = await deps.db.get_readings_by_measurement("par")

    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    return df.dropna(subset=["time", "device", "value"])


### Filter today data ###
def filter_today(df, use_latest_date_in_data=USE_LATEST_DATE_IN_DATA):
    df_local = df.copy()
    df_local["time_local"] = df_local["time"].dt.tz_convert(GREENHOUSE_TZ)

    if use_latest_date_in_data:
        target_day = df_local["time_local"].max().normalize()
    else:
        target_day = pd.Timestamp.now(tz=GREENHOUSE_TZ).normalize()

    next_day = target_day + pd.Timedelta(days=1)

    mask = (
        (df_local["time_local"] >= target_day) &
        (df_local["time_local"] < next_day)
    )

    return df_local.loc[mask].drop(columns=["time_local"]), target_day


### DLI ###
def compute_dli(sensor_df):
    d = sensor_df.sort_values("time").copy()

    if len(d) < 2:
        return None

    d["next_time"] = d["time"].shift(-1)
    d["next_value"] = d["value"].shift(-1)

    d["dt_seconds"] = (d["next_time"] - d["time"]).dt.total_seconds()
    d["dt_seconds"] = d["dt_seconds"].clip(lower=0, upper=900)

    d["avg_value"] = (d["value"] + d["next_value"]) / 2
    d = d.dropna(subset=["dt_seconds", "avg_value"])

    return float((d["avg_value"] * d["dt_seconds"]).sum() / 1_000_000)


### Metrics ###
def compute_sensor_metrics(df_day):
    rows = []

    for sensor_id, device in SENSOR_TO_DEVICE.items():
        d = df_day[df_day["device"] == device].sort_values("time")

        if d.empty:
            rows.append({
                "sensor_id": sensor_id,
                "latest_par": None,
                "dli_today": None,
            })
            continue

        latest = d.iloc[-1]

        rows.append({
            "sensor_id": sensor_id,
            "latest_par": float(latest["value"]),
            "dli_today": compute_dli(d),
        })

    return pd.DataFrame(rows)


### Plot ###
def make_par_greenhouse_plot(
    metrics,
    canvas_w,
    canvas_h,
    sensor_boxes,
    sensor_bands,
    target_day,
):
    fig = go.Figure()

    latest_vals = metrics["latest_par"].dropna()
    dli_vals = metrics["dli_today"].dropna()

    latest_min = float(latest_vals.min()) if not latest_vals.empty else 0.0
    latest_max = float(latest_vals.max()) if not latest_vals.empty else 1.0

    dli_min = float(dli_vals.min()) if not dli_vals.empty else 0.0
    dli_max = float(dli_vals.max()) if not dli_vals.empty else 1.0

    # background
    fig.add_layout_image(
        dict(
            source=svg_to_data_uri(SVG_PATH),
            xref="x",
            yref="y",
            x=0,
            y=canvas_h,
            sizex=canvas_w,
            sizey=canvas_h,
            layer="below",
        )
    )

    for _, row in metrics.iterrows():
        sid = row["sensor_id"]

        # --- bands ---
        if sid in sensor_bands:
            x0, x1, y0, y1 = svg_rect_to_plotly_rect(sensor_bands[sid], canvas_h)

            fig.add_shape(
                type="rect",
                x0=x0,
                x1=x1,
                y0=y0,
                y1=y1,
                fillcolor=value_to_color(row["dli_today"], dli_min, dli_max, alpha=0.4),
                line=dict(width=0),
                layer="below",
            )

        # --- sensor box ---
        if sid in sensor_boxes:
            x0, x1, y0, y1 = svg_rect_to_plotly_rect(sensor_boxes[sid], canvas_h)

            fig.add_shape(
                type="rect",
                x0=x0,
                x1=x1,
                y0=y0,
                y1=y1,
                fillcolor=value_to_color(row["latest_par"], latest_min, latest_max, alpha=0.9),
                line=dict(color="black"),
            )

            label = "—" if pd.isna(row["latest_par"]) else f"{row['latest_par']:.0f}"

            fig.add_annotation(
                x=(x0 + x1) / 2,
                y=(y0 + y1) / 2,
                text=label,
                showarrow=False,
            )

    fig.update_layout(
        title=f"PAR profile — {target_day.date()}",
        width=850,
        height=760,
    )

    fig.update_xaxes(range=[0, canvas_w], visible=False)
    fig.update_yaxes(range=[0, canvas_h], visible=False)

    return fig