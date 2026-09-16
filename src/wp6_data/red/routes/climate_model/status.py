"""GET /climate/model — what the climate chain can and cannot do.

The page leads with **skill against baselines**, not R². A model of a
slowly-moving indoor quantity scores well by echoing the present, so an R² grid
alone would read as success everywhere. Each cell says how much of a baseline's
error the model actually removed, and a cell that removed none says so.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from wp6_data.red.climate.charts import (
    hour_error_chart,
    month_error_chart,
    skill_matrix_chart,
)
from wp6_data.red.climate.downscale import DownscaleStats, HeightFit
from wp6_data.red.climate.forecast import UNITS, quantity
from wp6_data.red.climate.model import ClimateModelStats
from wp6_data.red.climate.training import TrainedChain, load_chain, mean_skill
from wp6_data.shared import render_card, render_page, render_stat_grid, render_table

router = APIRouter()

PAGE_TITLE = "SPoHF Red - Climate Model"

# Skill below this is not worth calling an improvement; at or below zero the
# baseline won and the cell says so outright.
SKILL_MEANINGFUL = 0.05


def _skill_cell(skill: float | None) -> str:
    """A skill score coloured by whether it beat the baseline at all."""
    if skill is None:
        return "<span class='muted'>—</span>"
    if skill <= 0:
        return f"<span style='color:var(--pico-del-color,#b3261e)'>{skill:+.2f}</span>"
    if skill < SKILL_MEANINGFUL:
        return f"<span class='muted'>{skill:+.2f}</span>"
    return f"<strong style='color:var(--pico-ins-color,green)'>{skill:+.2f}</strong>"


CHAIN_DIAGRAM = """
<pre style="line-height:1.35;overflow-x:auto;margin:0 0 .75rem 0"><code>OpenMeteo hourly weather
      |  link 1   calibrate the API to this site
      v
s1000 outdoor station
      |  link 2   how the house responds, given its own recent state
      v
greenhouse level  ({reference})
      |  + lamps  observed level and hours, added back for light only
      |  link 3   how each growth section differs from the house
      v
per-height values on a wire  (H1 Head .. H5 Substrate)</code></pre>
"""


def _overview(chain: TrainedChain, stats: ClimateModelStats) -> str:
    """What the model is, before any judgement of how well it does.

    A reader arriving at this page needs to know what the three links are and
    which sensors they run between; the scores below mean little without it.
    """
    lamp = chain.lamp
    if lamp is None:
        lamp_row = "not derived"
    elif lamp.is_lighting:
        lamp_row = (
            f"{lamp.power_par:g} µmol/m²/s over {len(lamp.hours_on)} h/day, "
            f"observed across the last {lamp.observed_days} days"
        )
    else:
        lamp_row = f"not running in the last {lamp.observed_days} days"

    span = " to ".join(str(day) for day in stats.span if day is not None)
    rows = [
        ["Link 1", "OpenMeteo → <code>s1000</code>",
         "Modelled weather calibrated to the site's own outdoor station. "
         "A stage that cannot beat its own mean is dropped rather than passed on."],
        ["Link 2", f"<code>s1000</code> → <code>{chain.chosen_reference}</code>",
         "Greenhouse-level temperature, humidity, CO₂ and <em>natural</em> PAR at "
         f"+{'/+'.join(str(h) for h in stats.horizons)} h, from the house's recent "
         "state plus link 1's output. One model per target and horizon."],
        ["Lamps", "observed, not predicted",
         "Lamp hours are an operator decision weather cannot explain, so the "
         "level and schedule are read off the sensors and added back before "
         f"link 3. Currently: {lamp_row}."],
        ["Link 3", "greenhouse level → each height",
         "How each growth section deviates from the house — a difference for "
         "temperature and CO₂, a ratio for light, and a moisture-content "
         "difference for humidity."],
    ]
    return render_card(
        "How the model works",
        CHAIN_DIAGRAM.format(reference=chain.chosen_reference)
        + render_table(["Stage", "From → to", "What it does"], rows, sortable=False)
        + f"<p class='muted'>Trained on {span} "
          f"({chain.span_days:,} days, {stats.excluded_days:,} excluded).</p>",
        description=(
            "Three links, each fitted on the data that supports it. The wires "
            "have only a few months of history, so only the last and smallest "
            "link depends on them."
        ),
    )


def _link2_skill_charts(stats: ClimateModelStats) -> str:
    """Target × horizon, once per baseline.

    Two matrices rather than one: a model can beat "the value now" and still
    lose to "the average for this hour and month", and those are different
    failures. Showing them side by side makes which one visible at a glance.
    """
    horizons = [f"+{h} h" for h in stats.horizons]
    charts = []
    for index, baseline in enumerate(("persistence", "climatology")):
        z = [
            [
                (fit.stats.skill.get(baseline) if fit else None)
                for horizon in stats.horizons
                for fit in [stats.fit_for(target, horizon)]
            ]
            for target in stats.targets
        ]
        chart = skill_matrix_chart(
            z, horizons, [quantity(target) for target in stats.targets],
            baseline=baseline, include_js=index == 0, x_title="horizon",
        )
        if chart:
            charts.append(
                f"<h4>vs {baseline}</h4>{chart}"
            )
    return "".join(charts)


def _link3_skill_chart(downscale: DownscaleStats) -> str:
    """Height × (wire, measurement), against the no-gradient baseline."""
    rows = sorted({(f.wire, f.measurement) for f in downscale.fits})
    heights = sorted({f.height for f in downscale.fits})
    if not rows or not heights:
        return ""
    by_key = {
        (f.wire, f.measurement, f.height): f.stats.skill.get("reference")
        for f in downscale.fits
    }
    z = [
        [by_key.get((wire, measurement, height)) for height in heights]
        for wire, measurement in rows
    ]
    chart = skill_matrix_chart(
        z, [f"H{h}" for h in heights],
        [f"{wire} · {quantity(measurement)}" for wire, measurement in rows],
        baseline="reference", x_title="growth section",
    )
    return chart or ""


def _seasonal_spread_note(stats: ClimateModelStats) -> str:
    """State each target's measured seasonal range, rather than quoting figures.

    An earlier version of this description carried hardcoded ratios that went
    stale the moment the PAR reference changed. Computing them from the fits
    means the page cannot disagree with the model it is describing.
    """
    import statistics

    spans = []
    for target in stats.targets:
        # Within each horizon, then across horizons: pooling every horizon
        # together would mix the seasonal range with the horizon range and
        # overstate both.
        ratios = []
        for horizon in stats.horizons:
            fit = stats.fit_for(target, horizon)
            errors = [value for _, value in (fit.error_by_month if fit else [])]
            if len(errors) > 1 and min(errors) > 0:
                ratios.append(max(errors) / min(errors))
        if ratios:
            spans.append((target, statistics.median(ratios)))
    if not spans:
        return ""
    ranked = sorted(spans, key=lambda pair: pair[1], reverse=True)
    parts = ", ".join(f"{quantity(target)} {ratio:.1f}×" for target, ratio in ranked)
    return (
        f" Typical range between the best and worst month at a given "
        f"horizon, widest first: {parts}."
    )


def _period_error_charts(stats: ClimateModelStats, *, by: str) -> str:
    """One matrix per target: where the error actually sits, in day or year."""
    builder = hour_error_chart if by == "hour" else month_error_chart
    attribute = "error_by_hour" if by == "hour" else "error_by_month"
    charts = []
    for index, target in enumerate(stats.targets):
        rows = [
            (fit.horizon_hours, getattr(fit, attribute))
            for horizon in stats.horizons
            for fit in [stats.fit_for(target, horizon)]
            if fit is not None
        ]
        chart = builder(rows, UNITS.get(target, ""), include_js=index == 0)
        if chart:
            charts.append(f"<h4>{quantity(target)}</h4>{chart}")
    return "".join(charts)


def _link2_table(stats: ClimateModelStats) -> str:
    """Target × horizon, with skill against both baselines in every cell."""
    headers = ["Target", "Horizon", "RMSE (held out)", "R²", "vs persistence", "vs climatology"]
    rows = []
    for target in stats.targets:
        for horizon in stats.horizons:
            fit = stats.fit_for(target, horizon)
            if fit is None:
                continue
            s = fit.stats
            rows.append([
                target,
                f"+{horizon} h",
                f"{s.holdout_rmse:g}" if s.holdout_rmse is not None else "—",
                f"{s.holdout_r2:g}" if s.holdout_r2 is not None else "—",
                _skill_cell(s.skill.get("persistence")),
                _skill_cell(s.skill.get("climatology")),
            ])
    return render_table(headers, rows, group_col=0)


def _link3_table(fits: list[HeightFit]) -> str:
    headers = ["Wire", "Measurement", "Height", "Deviation", "Seasonal",
               "RMSE (held out)", "vs reference", "vs constant offset"]
    rows = [
        [
            fit.wire, fit.measurement, f"H{fit.height}", fit.mode,
            "yes" if fit.seasonal else "no",
            f"{fit.stats.holdout_rmse:g}" if fit.stats.holdout_rmse is not None else "—",
            _skill_cell(fit.stats.skill.get("reference")),
            _skill_cell(fit.stats.skill.get("constant_offset")),
        ]
        for fit in sorted(fits, key=lambda f: (f.wire, f.measurement, f.height))
    ]
    return render_table(headers, rows, group_col=0)


def _gradient_table(downscale: DownscaleStats) -> str:
    """The acceptance criterion, made visible: is the profile *shape* right?"""
    headers = ["Wire", "Measurement", "Profile RMSE", "Gradient sign agreement", "Points"]
    rows = [
        [wire, measurement, f"{score.rmse:g}",
         f"{score.sign_agreement:.1%}", f"{score.n:,}"]
        for (wire, measurement), score in sorted(downscale.gradients.items())
    ]
    return render_table(headers, rows, group_col=0)


def _comparison_table(chain: TrainedChain) -> str:
    headers = ["Reference", "Targets covered", "Mean skill vs persistence", "Chosen"]
    rows = [
        [
            key,
            ", ".join(stats.targets) or "—",
            f"{mean_skill(stats):+.4f}",
            "✓" if key == chain.chosen_reference else "",
        ]
        for key, stats in sorted(chain.comparison.items())
    ]
    return render_table(headers, rows, sortable=False)


def _untrained_page() -> str:
    return render_page(
        PAGE_TITLE,
        render_card(
            "No climate model yet",
            "<p>The model lives on ephemeral storage, so a restart clears it and "
            "the dashboard retrains on boot. If this persists, train it here.</p>"
            "<form method='post' action='/climate/model/train'>"
            "<button type='submit'>Train now</button></form>",
        ),
        show_back_link=True,
    )


@router.get("/", response_class=HTMLResponse)
async def climate_model_status() -> str:
    """Model status: what it was trained on, and what it actually beats."""
    chain = load_chain()
    if chain is None or chain.stats is None:
        return _untrained_page()

    stats = chain.stats
    downscale = chain.downscale
    beating = len(stats.horizons_beating_persistence)

    summary = render_stat_grid([
        (chain.chosen_reference, "Reference"),
        (f"{chain.span_days:,}", "Days trained on"),
        (f"{stats.excluded_days:,}", "Days excluded"),
        (f"{beating}/{len(stats.link2)}", "Beat persistence"),
        (
            f"{len(downscale.earned_its_place)}/{len(downscale.fits)}"
            if downscale else "—",
            "Heights beating reference",
        ),
    ], cols=5)

    link1_rows = [
        [name.removeprefix("out_"),
         f"{s.holdout_r2:g}" if s.holdout_r2 is not None else "—",
         f"{s.holdout_rmse:g}" if s.holdout_rmse is not None else "—",
         f"{s.n_samples:,}",
         "used" if (s.holdout_r2 or 0) > 0 else "dropped — no better than its own mean"]
        for name, s in sorted(stats.link1.items())
    ]

    suggestions = ""
    if chain.suggestions:
        items = "".join(f"<li>{note}</li>" for note in chain.suggestions)
        suggestions = render_card(
            "Configuration that has become improvable",
            f"<ul>{items}</ul>",
            description="Config that has become improvable since it was written.",
        )

    content = f"""
        <h1>Climate model</h1>
        {summary}
        <p class="muted">Trained {chain.trained_at:%Y-%m-%d %H:%M} UTC.
        Every score below is out-of-fold: each row was predicted by a fit that
        never saw the block of days it belongs to.</p>

        {_overview(chain, stats)}

        {suggestions}

        {render_card(
            "Choice of greenhouse-level reference",
            _comparison_table(chain),
            description=(
                "Both declared greenhouse-level sensors are trained and compared. "
                "Coverage wins over a marginally better score — picking on skill "
                "alone would silently drop a target."
            ),
        )}

        {render_card(
            "Link 1 · Weather calibration to the s1000 outdoor station",
            render_table(
                ["Sensor", "R² (held out)", "RMSE", "Rows", "Fed to link 2"],
                link1_rows,
            ),
            description="Calibrates the modelled weather to what red's own station records.",
        )}

        {render_card(
            "Link 2 · Skill against baselines, by target and horizon",
            _link2_skill_charts(stats),
            description=(
                "Skill is the fraction of a baseline's error the model "
                "removes. Blue beat the baseline, red lost to it, grey neither. "
                "Two baselines because they fail differently: persistence is "
                "hard to beat at short horizons, climatology at long ones."
            ),
        )}

        {render_card(
            "Link 2 · Error by hour of day",
            _period_error_charts(stats, by="hour")
            or "<p class='muted'>No per-hour residuals stored; retrain to "
               "populate them.</p>",
            description=(
                "Held-out RMSE by hour of day. A model that merely tracks the "
                "daily mean scores evenly across the row; one that has learnt "
                "the day's shape does not."
            ),
        )}

        {render_card(
            "Link 2 · Error by calendar month",
            _period_error_charts(stats, by="month")
            or "<p class='muted'>No per-month residuals stored; retrain to "
               "populate them.</p>",
            description=(
                "Held-out RMSE by calendar month. Absolute error tracks the "
                "size of the signal, so a target whose magnitude swings with "
                "the season has a headline figure that averages over a wide "
                "range." + _seasonal_spread_note(stats)
            ),
        )}

        {render_card(
            "Link 2 · Full results",
            _link2_table(stats),
            description=(
                "Held-out error and skill for every target and horizon, "
                "including the combinations the matrices above summarise."
            ),
        )}

        {render_card(
            "Link 3 · Skill against assuming no vertical gradient",
            _link3_skill_chart(downscale) if downscale and downscale.fits
            else "<p class='muted'>No wire data available for the configured span.</p>",
            description=(
                "Skill against assuming each height simply equals the "
                "greenhouse-level reference. Red means the gradient model lost "
                "to ignoring the gradient."
            ),
        )}

        {render_card(
            "Link 3 · Full results, per wire and height",
            _link3_table(downscale.fits) if downscale and downscale.fits
            else "<p class='muted'>No wire data available for the configured span.</p>",
            description=(
                "Per-height deviation from the greenhouse-level reference, "
                "with skill against both ignoring the gradient and assuming a "
                "fixed one. 'Seasonal' is measured per fit rather than "
                "configured: each height is fitted with and without a "
                "day-of-year term and the better held-out score wins."
            ),
        )}

        {render_card(
            "Link 3 · Accuracy of the H1→H5 profile shape",
            _gradient_table(downscale) if downscale and downscale.gradients
            else "<p class='muted'>Needs two or more heights on a wire.</p>",
            description=(
                "Error on the shape of the H1→H5 profile rather than on each "
                "height's level, so a model that is uniformly warm still scores "
                "well and one that inverts the profile does not. Sign agreement "
                "is how often the gradient points the same way as measured."
            ),
        )}

        <form method="post" action="/climate/model/train">
            <button type="submit">Retrain</button>
        </form>
        <p class="muted">Retraining re-reads everything from the configured
        start to now, so the model widens as the record grows.</p>
    """
    return render_page(PAGE_TITLE, content, show_back_link=True)
