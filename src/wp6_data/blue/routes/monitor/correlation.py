"""GET /monitor/correlation — Sensor correlation matrix for SPoHF."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.shared import render_date_filter, render_page, resolve_date_range
from wp6_data.shared.charts import make_correlation_matrix
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider

router = APIRouter()

PAGE_TITLE = "SPoHF Blue - Sensor Correlations"

ALL_SENSORS = [
    "temperature",
    "humidity",
    "soilTemperature",
    "soilMoisture",
    "soilConductivity",
    "soil_pH",
    "leaf_temperature",
    "leaf_moisture",
    "par",
]


@router.get("/correlation", response_class=HTMLResponse)
async def correlation_page(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    method: Annotated[str, Query(regex="^(pearson|spearman|kendall)$")] = "pearson",
) -> str:
    """Sensor correlation heatmap across all sensor types."""
    start, end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await provider.fetch_data(
            sensor_tags=ALL_SENSORS,
            start=start_dt,
            end=end_dt,
        )
    except Exception as exc:
        return render_page(
            PAGE_TITLE,
            f"<p>Error fetching data: {exc}</p>",
            show_back_link=True,
            back_url="/monitor",
            data_source=provider.data_source_label,
        )

    date_filter = render_date_filter(start, end)

    method_tabs = "".join(
        f'<a href="?start={start}&end={end}&method={m}" '
        f'role="button" class="{"" if m != method else "secondary"}" '
        f'style="padding:0.3rem 0.8rem;margin-right:4px">{m.capitalize()}</a>'
        for m in ("pearson", "spearman", "kendall")
    )

    if df.empty:
        return render_page(
            PAGE_TITLE,
            f"<h1>Sensor Correlations</h1>{date_filter}"
            "<p>No data for the selected period.</p>",
            show_back_link=True,
            back_url="/monitor",
            data_source=provider.data_source_label,
        )

    fig = make_correlation_matrix(df, method=method, title="")
    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    content = f"""
        <h1>Sensor Correlations</h1>
        {date_filter}
        <div style="margin-bottom:1rem">{method_tabs}</div>
        {chart_html}
    """
    return render_page(
        PAGE_TITLE,
        content,
        show_back_link=True,
        back_url="/monitor",
        data_source=provider.data_source_label,
    )
