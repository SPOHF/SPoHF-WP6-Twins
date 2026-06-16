"""GET /mixed-views — Cross-domain correlation hub (sensor × manual × fertilizer)."""

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated

import openpyxl
import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.blue.long_data import MEASURE_MAP
from wp6_data.blue.long_data import TREATMENT_MAP as _LONG_DATA_TREATMENT_MAP
from wp6_data.blue.routes.monitor._treatment import load_device_treatment_map
from wp6_data.blue.routes.monitor.manual import (
    MEASURE_LABELS,
    MEASURE_UNITS,
    render_correlation_explanation,
)
from wp6_data.shared import render_hub_card, render_hub_grid, render_page
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.charts import render_correlation_heatmap_html
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider

router = APIRouter(dependencies=[Depends(verify_session_user)])

PAGE_TITLE = "SPoHF Blue - Mixed Views"

_YEAR_START = datetime(2025, 1, 1, tzinfo=UTC)
_YEAR_END = datetime(2026, 1, 1, tzinfo=UTC)

_FERTILIZER_XLSX = (
    Path(__file__).parent.parent.parent / "fertilizer_strategy_2025.xlsx"
)

_LONG_DATA_DEVICES: frozenset[str] = frozenset(_LONG_DATA_TREATMENT_MAP.values())
_ALL_LONG_DATA_SENSORS: list[str] = sorted(frozenset(MEASURE_MAP.values()))

_SENSOR_TAGS: list[str] = [
    "soilTemperature", "soilMoisture", "soil_pH", "soilConductivity", "par",
]

_SENSOR_LABELS: dict[str, str] = {
    "soilTemperature": "Soil Temp (°C)",
    "soilMoisture": "Moisture (%VWC)",
    "soil_pH": "pH",
    "soilConductivity": "EC (μS/cm)",
    "par": "PAR (μmol/m²/s)",
}

_NUTRIENT_COLS: list[str] = ["N", "P2O5", "K2O", "MgO", "CaO", "Br"]
_NUTRIENT_LABELS: dict[str, str] = {
    "N": "N (kg/ha)",
    "P2O5": "P₂O₅ (kg/ha)",
    "K2O": "K₂O (kg/ha)",
    "MgO": "MgO (kg/ha)",
    "CaO": "CaO (kg/ha)",
    "Br": "Br (kg/ha)",
}

_XLSX_TREATMENT_MAP: dict[str, str] = {
    "DCM (Org-1)": "Org1",
    "Den Ouden (Org-2)": "Org2",
    "Standaard (3rijen)": "Std",
    "V_Ca": "V_CA",
    "Ca": "Ca",
    "V_Ca_GBrPK": "V_CA_G_BrPK",
    "G_K": "G_K",
    "K": "K",
    "V_K_G_CaBrP": "V_K_G_CaBrP",
}

_MIN_TREATMENT_OVERLAP = 4  # Spearman ρ is unreliable below n=4 paired observations


def _col_label(col: str) -> str:
    if col in _SENSOR_LABELS:
        return _SENSOR_LABELS[col]
    if col in _NUTRIENT_LABELS:
        return _NUTRIENT_LABELS[col]
    base = MEASURE_LABELS.get(col, col.replace("_", " ").title())
    unit = MEASURE_UNITS.get(col)
    return f"{base} ({unit})" if unit else base


@lru_cache(maxsize=1)
def _load_fertilizer_wide() -> pd.DataFrame:
    """Parse fertilizer_strategy_2025.xlsx into a treatment-indexed DataFrame."""
    wb = openpyxl.load_workbook(_FERTILIZER_XLSX, read_only=True, data_only=True)
    ws = wb.active
    data: dict[str, list[float | None]] = {}
    for row in ws.iter_rows(values_only=True):
        key = str(row[0]).strip() if row[0] is not None else ""
        if key not in _XLSX_TREATMENT_MAP:
            continue
        if row[1] is None or "Totaal" not in str(row[1]):
            continue
        code = _XLSX_TREATMENT_MAP[key]
        values = [
            float(row[i]) if isinstance(row[i], (int, float)) else None
            for i in range(2, 8)
        ]
        data[code] = values
    wb.close()
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame.from_dict(data, orient="index", columns=_NUTRIENT_COLS)
    df.index.name = "treatment"
    return df


def _render_nan_report(
    wide: pd.DataFrame,
    columns: list[str],
    labels: dict[str, str],
    corr: pd.DataFrame,
) -> str:
    notna = wide[columns].notna().astype(int)
    overlap = notna.T.dot(notna)
    stdev = wide[columns].std(skipna=True)

    rows: list[str] = []
    for i, left in enumerate(columns):
        for right in columns[i + 1:]:
            if pd.notna(corr.loc[left, right]):
                continue
            pair_overlap = int(overlap.loc[left, right])
            reasons: list[str] = []
            if pair_overlap < _MIN_TREATMENT_OVERLAP:
                reasons.append(
                    f"only {pair_overlap} overlapping treatments "
                    f"(minimum {_MIN_TREATMENT_OVERLAP})"
                )
            if float(stdev.get(left, 0.0)) == 0.0:
                reasons.append(f"{labels[left]} has zero variance")
            if float(stdev.get(right, 0.0)) == 0.0:
                reasons.append(f"{labels[right]} has zero variance")
            if not reasons:
                reasons.append("all pairwise values are missing after aggregation")
            rows.append(
                "<tr>"
                f"<td>{labels[left]}</td><td>{labels[right]}</td>"
                f"<td>{pair_overlap}</td>"
                f"<td>{'; '.join(reasons)}</td>"
                "</tr>"
            )

    if not rows:
        return ""
    body = "".join(rows)
    return f"""
        <article>
          <h3>NaN Diagnostics</h3>
          <p>Rows after aggregation: <strong>{len(wide)}</strong>
            (one per treatment). Pairs with fewer than {_MIN_TREATMENT_OVERLAP}
            overlapping treatments are excluded.</p>
          <table>
            <thead>
              <tr>
                <th>Variable A</th><th>Variable B</th>
                <th>Overlap</th><th>Why excluded</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </article>
    """


def _render_correlation_page(
    wide: pd.DataFrame,
    title: str,
    description: str,
    *,
    provider_label: str,
) -> str:
    """Render a full correlation matrix page from a treatment-indexed wide DataFrame."""
    columns = [c for c in wide.columns if wide[c].notna().sum() >= _MIN_TREATMENT_OVERLAP]
    if len(columns) < 2:
        content = f"<h1>{title}</h1><p>Insufficient data to compute correlations.</p>"
    else:
        corr = wide[columns].corr(method="spearman")
        labels = {c: _col_label(c) for c in columns}
        heatmap_html = render_correlation_heatmap_html(
            corr, [labels[c] for c in columns], include_js=True, value_label="ρ",
        )
        nan_html = _render_nan_report(wide, columns, labels, corr)
        content = f"""
            <h1>{title}</h1>
            <p>{description}</p>
            {render_correlation_explanation()}
            <article>
              {heatmap_html}
            </article>
            {nan_html}
        """
    return render_page(
        PAGE_TITLE,
        content,
        show_back_link=True,
        back_url="/mixed-views",
        data_source=provider_label,
    )


async def _fetch_manual_wide(provider: SensorDataProvider) -> pd.DataFrame:
    """Fetch 2025 long_data and pivot to treatment × measure wide format."""
    try:
        manual_df = await provider.fetch_data(
            sensor_tags=_ALL_LONG_DATA_SENSORS,
            device_names=sorted(_LONG_DATA_DEVICES),
            start=_YEAR_START,
            end=_YEAR_END,
        )
    except Exception:
        return pd.DataFrame()

    if manual_df.empty:
        return pd.DataFrame()

    m = manual_df.copy()
    m = m[m["time"].dt.year == 2025]
    m["treatment"] = m["device"]
    if m.empty:
        return pd.DataFrame()

    agg = m.groupby(["treatment", "sensor"])["value"].mean().reset_index()
    return agg.pivot_table(
        index="treatment", columns="sensor", values="value", aggfunc="mean",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/mixed-views", response_class=HTMLResponse)
async def mixed_views_hub() -> str:
    """Mixed Views hub — links to cross-domain correlation matrices."""
    content = f"""
        <h1>Mixed Views</h1>
        <p>
          Cross-domain Spearman ρ correlation matrices for 2025 — sensor readings
          and hand measurements aggregated to one value per treatment (n = 9).
        </p>
        {render_hub_grid([
            render_hub_card(
                "Soil & Light vs. Manual Measurements",
                "Spearman ρ between 2025 soil sensor readings and PAR vs. "
                "hand-measured quality metrics, aggregated to treatment-level seasonal means.",
                href="/mixed-views/sensor-manual",
                label="View Matrix",
            ),
            render_hub_card(
                "Manual Measurements vs. Fertilizer Inputs",
                "Spearman ρ between treatment-level quality metrics and total nutrient "
                "inputs (N, P₂O₅, K₂O, MgO, CaO, Br in kg/ha) from the 2025 fertilizer strategy.",
                href="/mixed-views/manual-fert",
                label="View Matrix",
            ),
        ])}
    """
    return render_page(PAGE_TITLE, content, show_back_link=True)


@router.get("/mixed-views/sensor-manual", response_class=HTMLResponse)
async def sensor_manual_matrix(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
) -> str:
    """Soil & PAR × manual measurements Spearman ρ (2025)."""
    sensor_wide: pd.DataFrame = pd.DataFrame()
    try:
        sensor_df = await provider.fetch_data(
            sensor_tags=_SENSOR_TAGS,
            start=_YEAR_START,
            end=_YEAR_END,
        )
        if not sensor_df.empty:
            treatment_map = load_device_treatment_map()
            s = sensor_df.copy()
            s["treatment"] = s["device"].map(treatment_map)
            s = s.dropna(subset=["treatment"])
            if not s.empty:
                agg = s.groupby(["treatment", "sensor"])["value"].mean().reset_index()
                sensor_wide = agg.pivot_table(
                    index="treatment", columns="sensor", values="value", aggfunc="mean",
                )
    except Exception:
        pass

    manual_wide = await _fetch_manual_wide(provider)

    parts = [df for df in [sensor_wide, manual_wide] if not df.empty]
    wide = (
        parts[0].join(parts[1], how="outer") if len(parts) == 2
        else parts[0] if parts
        else pd.DataFrame()
    )

    return _render_correlation_page(
        wide,
        "Soil &amp; Light vs. Manual Measurements (2025)",
        "Spearman ρ between 2025 soil sensor readings, PAR, and hand-measured quality "
        "metrics — aggregated to treatment-level seasonal means (n = 9 treatments).",
        provider_label=provider.data_source_label,
    )


@router.get("/mixed-views/manual-fert", response_class=HTMLResponse)
async def manual_fert_matrix(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
) -> str:
    """Manual measurements × fertilizer inputs Spearman ρ (2025)."""
    manual_wide = await _fetch_manual_wide(provider)
    fert_wide = _load_fertilizer_wide()

    wide = (
        manual_wide.join(fert_wide, how="inner")
        if not manual_wide.empty and not fert_wide.empty
        else pd.DataFrame()
    )

    return _render_correlation_page(
        wide,
        "Manual Measurements vs. Fertilizer Inputs (2025)",
        "Spearman ρ between treatment-level quality metrics and total nutrient inputs "
        "(kg/ha) from the SPoHF 2025 fertilizer strategy — non-parametric rank correlation "
        "appropriate for n = 9 treatment means.",
        provider_label=provider.data_source_label,
    )
