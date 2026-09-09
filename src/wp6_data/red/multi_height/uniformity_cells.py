"""HTML builders for the red "Uniformity across wires" page.

Where the crop-climate table tints every cell by rank among the five heights,
this page tints exactly **one** column — the spread — on an *absolute* scale
read from config. That is the difference the page depends on: a colour here has
to mean the same thing on every day, every metric and every wire, or a calm
greenhouse and a drifting one look alike. The reader scans one column to find
where the wires disagree, then reads across to see which wire is responsible.

The wire columns themselves are deliberately untinted. Three numbers side by
side already say which is highest; tinting them too would spend colour on the
thing the eye does for free and leave none for the thing it cannot.
"""

from __future__ import annotations

import html

from ..utils import value_to_color
from .cells import METRIC_COLORS, METRIC_LABELS, format_reading, sparkline_svg
from .uniformity import (
    LAST,
    MAX,
    METRIC_AGG,
    VERDICT_AGREES,
    VERDICT_DIVERGENT,
    VERDICT_EXCLUDED,
    VERDICT_OFFSET,
    SectionRow,
    UniformityDay,
    WireCell,
    WireVerdict,
)

# Disagreement gets a hue of its own rather than the metric's, because it is a
# different quantity from the readings around it — a wide temperature spread is
# not "a lot of temperature". Orange-600 appears nowhere else on these pages.
SPREAD_COLOR = "#ea580c"
SPREAD_SCALE = [[0.0, "#ffffff"], [1.0, SPREAD_COLOR]]

MUTED = "#6b7280"
GRID_BORDER = "1px solid #e5e7eb"
ROW_HEIGHT = 76


def _spread_tint(spread: float, notable: float) -> str:
    """White→orange over ``0..notable``, saturating rather than running away.

    Clamping at ``notable`` is the point: past "worth reporting" the colour has
    said all it can, and letting one wild day rescale the ramp would make every
    other day on the same page look calm.
    """
    return value_to_color(
        min(spread, notable), 0.0, notable, colorscale=SPREAD_SCALE, alpha=0.85,
    )


def _fmt(value: float | None, unit: str, precision: int | None = None) -> str:
    if value is None:
        return "—"
    number = f"{value:.{precision}f}" if precision is not None else format_reading(value)
    return f"{number} {unit}".strip()


# How to name, in prose, the number a metric is compared on. Read off the same
# mapping the aggregation uses, so the sentence cannot describe one thing while
# the column shows another.
AGG_PHRASE = {LAST: "the day's total", MAX: "the day's peak"}
DEFAULT_AGG_PHRASE = "the day's mean"


def aggregate_phrase(metric: str) -> str:
    """What the compared number is, in words — "the day's mean", "its total"."""
    return AGG_PHRASE.get(METRIC_AGG[metric], DEFAULT_AGG_PHRASE)


### Cells ###
def uniformity_cell(cell: WireCell, metric: str, day: str) -> str:
    """One wire's reading of one growth section: aggregate, latest, sparkline.

    The aggregate leads because it is what the wires are compared on; the latest
    reading sits under it in small type so the number also reconciles with the
    crop-climate table without the reader holding two pages side by side.

    A wire that reported too little of the day still renders — greyed, with its
    coverage stated. Blanking it would make "we didn't look" indistinguishable
    from "there was nothing to see".
    """
    label, unit = METRIC_LABELS[metric]
    if cell.aggregate is None:
        body = (
            f'<div style="color:{MUTED};">—</div>'
            f'<div style="font-size:0.75rem;color:{MUTED};">no readings</div>'
        )
    else:
        ink = MUTED if not cell.comparable else "inherit"
        if not cell.comparable:
            note = f"{cell.coverage_hours} h reported"
        elif METRIC_AGG[metric] == LAST:
            # A cumulative metric's aggregate *is* its last point, so restating
            # it as "latest" would print the same number twice.
            note = "cumulative"
        else:
            note = f"latest {_fmt(cell.latest, unit)}"
        body = (
            f'<div style="font-weight:600;font-size:0.95rem;color:{ink};">'
            f"{_fmt(cell.aggregate, unit)}</div>"
            f'<div style="font-size:0.75rem;color:{MUTED};">{note}</div>'
            + sparkline_svg(cell.series, METRIC_COLORS[metric])
        )
    dim = "" if cell.comparable else "opacity:0.55;"
    return (
        f'<td style="padding:0.5rem 0.75rem;vertical-align:middle;{dim}" '
        f'title="{html.escape(cell.wire)} · {html.escape(label)} · {day}">'
        f"{body}</td>"
    )


def spread_cell(row: SectionRow, metric: str, notable: float) -> str:
    """How far apart the comparable wires are at this section.

    Tinted white→orange over ``0..notable``, so full colour means "this is the
    disagreement we said was worth reporting" on every metric alike. Below two
    comparable wires there is no spread to state, and the cell says which.
    """
    _, unit = METRIC_LABELS[metric]
    if row.spread is None:
        comparable = sum(1 for c in row.cells if c.comparable)
        reason = "one wire only" if comparable == 1 else "no wire reported"
        return (
            f'<td style="padding:0.5rem 0.75rem;color:{MUTED};'
            f'border-left:2px solid #cbd5e1;">—'
            f'<div style="font-size:0.75rem;">{reason}</div></td>'
        )
    background = _spread_tint(row.spread, notable)
    return (
        f'<td style="padding:0.5rem 0.75rem;border-left:2px solid #cbd5e1;'
        f'background:{background};font-weight:600;">'
        f"{_fmt(row.spread, unit)}</td>"
    )


### Table ###
def uniformity_table(view: UniformityDay) -> str:
    """The matrix: growth sections down, declared wires across, spread last."""
    day = view.day_start.date().isoformat()
    wire_headers = "".join(
        '<th style="padding:0.5rem 0.75rem;text-align:left;">'
        f'<a href="/multi_height/crop-climate?wire={html.escape(wire)}&date={day}" '
        f'style="text-decoration:none;">{html.escape(wire)} ↗</a></th>'
        for wire in view.wires
    )
    rows = ""
    for row in view.rows:
        cells = "".join(
            uniformity_cell(cell, view.metric, day) for cell in row.cells
        )
        rows += (
            f"<tr style='border-top:{GRID_BORDER};height:{ROW_HEIGHT}px;'>"
            '<td style="padding:0.5rem 0.75rem;font-weight:600;white-space:nowrap;">'
            f'<span style="color:{MUTED};">H{row.height}</span> · '
            f"{html.escape(row.label)}</td>"
            f"{cells}{spread_cell(row, view.metric, view.notable_spread)}</tr>"
        )
    return (
        '<table style="width:100%;border-collapse:collapse;">'
        "<thead><tr>"
        '<th style="padding:0.5rem 0.75rem;text-align:left;">Growth section</th>'
        f"{wire_headers}"
        '<th style="padding:0.5rem 0.75rem;text-align:left;'
        f'border-bottom:3px solid {SPREAD_COLOR};border-left:2px solid #cbd5e1;">'
        "Spread</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def spread_legend(view: UniformityDay) -> str:
    """The key for the spread tint, built from the same numbers it drew with.

    Derived rather than written out, so the legend cannot fall out of step with
    the column when ``notable_spread`` is retuned in YAML.
    """
    _, unit = METRIC_LABELS[view.metric]
    stops = "".join(
        '<span style="display:inline-block;width:34px;height:14px;'
        f"background:{_spread_tint(view.notable_spread * fraction, view.notable_spread)};"
        f'border:{GRID_BORDER};"></span>'
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0)
    )
    return (
        f'<div style="display:flex;gap:10px;align-items:center;color:{MUTED};'
        'font-size:0.8rem;margin-top:10px;">'
        f"<span>agreeing</span>{stops}"
        f"<span>{_fmt(view.notable_spread, unit)} apart or more</span></div>"
    )


### Verdicts ###
def verdict_line(
    verdict: WireVerdict, metric: str, min_coverage_hours: float, sections: int,
) -> str:
    """One wire's finding as a sentence, in the twin's own words.

    The view-model carries the numbers and the kind; the unit and the phrasing
    belong here — the same split ``crop_cycles`` uses, where the route turns
    view-model properties into prose.
    """
    label, unit = METRIC_LABELS[metric]
    wire = html.escape(verdict.wire)
    if verdict.kind == VERDICT_EXCLUDED:
        # Two very different absences, and the reader has to be able to tell
        # them apart: a wire that does not measure this at all, and one that
        # measures it but was down for most of the day.
        body = (
            f"excluded — measured no {label.lower()} today"
            if verdict.coverage_hours == 0
            else (
                f"excluded — {verdict.coverage_hours} h of {label.lower()}, "
                f"under the {min_coverage_hours:.0f} h needed to compare"
            )
        )
        color = MUTED
    elif verdict.kind == VERDICT_OFFSET:
        body = (
            f"reads {verdict.offset:+.2f} {unit} against the wire median at "
            "every height — a consistent offset, so look at how it hangs or "
            "how it is calibrated"
        )
        color = "#b45309"
    elif verdict.kind == VERDICT_DIVERGENT:
        body = (
            f"disagrees at H{verdict.worst_height} ({verdict.worst_delta:+.2f} "
            f"{unit}) more than it does elsewhere — local, not an offset"
        )
        color = "#b91c1c"
    else:
        worst = abs(verdict.worst_delta or 0.0)
        body = f"agrees with the other wires (within {worst:.2f} {unit})"
        color = "#16a34a"
    return (
        f'<li style="margin-bottom:6px;"><b>{wire}</b> '
        f'<span style="color:{color};">{body}</span>'
        f"{_scope_note(verdict, sections)}</li>"
    )


def _scope_note(verdict: WireVerdict, sections: int) -> str:
    """How much of the profile the finding actually rests on.

    A verdict drawn from one section is a far weaker claim than one drawn from
    five, and the wires do not all report every metric at every height — so the
    sentence says how many sections it had, and stays quiet when it had them all.
    """
    if verdict.kind == VERDICT_EXCLUDED or verdict.sections_compared >= sections:
        return ""
    plural = "" if verdict.sections_compared == 1 else "s"
    return (
        f'<span style="color:{MUTED};font-size:0.85rem;"> · on '
        f"{verdict.sections_compared} section{plural}</span>"
    )


def verdict_list(view: UniformityDay, min_coverage_hours: float) -> str:
    """Every declared wire's finding, ordered worst first so problems lead."""
    order = {
        VERDICT_DIVERGENT: 0, VERDICT_OFFSET: 1,
        VERDICT_AGREES: 2, VERDICT_EXCLUDED: 3,
    }
    items = "".join(
        verdict_line(v, view.metric, min_coverage_hours, len(view.rows))
        for v in sorted(view.verdicts, key=lambda v: (order[v.kind], v.wire))
    )
    return f'<ul style="margin:0;padding-left:1.1rem;">{items}</ul>'
