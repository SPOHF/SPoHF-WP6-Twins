"""Upload + preview + apply endpoints for the Sijia source.

Two-step flow per PRD §Upload flow (lines 285-294):

  1. POST /sources/sijia/preview — multipart upload. The handler persists the
     bytes via UploadStorage, runs ManualIngestService.validate, and renders
     the validation report with an Apply button.
  2. POST /sources/sijia/apply — validation_id + filename hidden inputs.
     Runs ManualIngestService.apply transactionally, then redirects back to
     /status with a success flash.
"""

from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from wp6_data.red.routes.sijia.deps import get_sijia_service
from wp6_data.red.sijia.parser import SijiaParseError, ValidationReport
from wp6_data.red.sijia.service import ManualIngestService
from wp6_data.shared import render_page

router = APIRouter()

PAGE_TITLE = "Sijia Upload"


def _format_date_range(date_range) -> str:
    if date_range is None:
        return "—"
    start, end = date_range
    return f"{start.isoformat()} → {end.isoformat()}"


def _render_warnings(report: ValidationReport) -> str:
    """Render warning cards for regressions / dropped identifiers."""
    parts: list[str] = []

    if report.emitted_row_count < report.existing_row_count:
        parts.append(
            f'<article class="warning">'
            f"<strong>Regression warning:</strong> applying this file will "
            f"insert {report.emitted_row_count} rows, replacing the existing "
            f"{report.existing_row_count} rows. Re-applying will "
            f"<em>shrink</em> the stored data."
            f"</article>"
        )

    if report.devices_removed:
        items = "".join(
            f"<li><code>{escape(d)}</code></li>" for d in report.devices_removed
        )
        parts.append(
            f'<article class="warning">'
            f"<strong>Devices missing from new upload:</strong>"
            f"<ul>{items}</ul>"
            f"</article>"
        )

    if report.sensors_removed:
        items = "".join(
            f"<li><code>{escape(s)}</code></li>" for s in report.sensors_removed
        )
        parts.append(
            f'<article class="warning">'
            f"<strong>Sensors missing from new upload:</strong>"
            f"<ul>{items}</ul>"
            f"</article>"
        )

    return "\n".join(parts)


def _render_skipped(report: ValidationReport) -> str:
    if not report.skipped_rows:
        return "<p>No rows were skipped.</p>"
    rows = "".join(
        f"<tr><td>{r.row_index}</td><td><code>{escape(r.reason)}</code></td></tr>"
        for r in report.skipped_rows
    )
    return f"""
        <details>
          <summary>{len(report.skipped_rows)} rows skipped (click to expand)</summary>
          <table>
            <thead><tr><th>Row</th><th>Reason</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </details>
    """


def _render_preview(report: ValidationReport, filename: str) -> str:
    devices_html = ", ".join(f"<code>{escape(d)}</code>" for d in report.devices) or "—"
    sensors_html = ", ".join(f"<code>{escape(s)}</code>" for s in report.sensors) or "—"

    body = f"""
        <h1>Preview — Sijia upload</h1>
        <p>File: <code>{escape(filename)}</code></p>
        <p>Hash: <code>{report.file_hash[:12]}…</code> · Size: {report.file_size:,} bytes</p>

        {_render_warnings(report)}

        <article>
          <h3>Parsed</h3>
          <ul>
            <li>Excel rows: <strong>{report.total_rows}</strong>
                ({report.valid_rows} valid · {len(report.skipped_rows)} skipped)</li>
            <li>Rows to insert (after aggregation):
                <strong>{report.emitted_row_count}</strong></li>
            <li>Date range: <strong>{_format_date_range(report.date_range)}</strong></li>
            <li>Devices in upload: {devices_html}</li>
            <li>Sensors in upload: {sensors_html}</li>
          </ul>
          {_render_skipped(report)}
        </article>

        <article>
          <h3>Existing data for source <code>sijia</code></h3>
          <ul>
            <li>Row count: <strong>{report.existing_row_count}</strong></li>
            <li>Date range:
                <strong>{_format_date_range(report.existing_date_range)}</strong></li>
          </ul>
        </article>

        <article>
          <h3>Apply</h3>
          <p>Pressing Apply will atomically replace all existing
             <code>source = sijia</code> data with the parsed rows above.</p>
          <form method="post" action="/sources/sijia/apply">
            <input type="hidden" name="validation_id" value="{report.file_hash}">
            <input type="hidden" name="filename" value="{escape(filename)}">
            <button type="submit">Apply</button>
            <a href="/status" role="button" class="outline">Cancel</a>
          </form>
        </article>
    """
    return body


@router.post("/preview", response_class=HTMLResponse)
async def preview(
    service: Annotated[ManualIngestService, Depends(get_sijia_service)],
    file: Annotated[UploadFile, File()],
) -> str:
    """Persist the uploaded bytes, validate them, and render the preview.

    Structural parse errors (wrong sheet, wrong headers) are rendered as a
    friendly error page rather than a 500 — admins need to see *what* was
    wrong with the file so they can fix it before re-uploading.
    """
    file_bytes = await file.read()
    filename = file.filename or "uploaded.xlsx"
    try:
        report = await service.validate(file_bytes)
    except SijiaParseError as exc:
        return render_page(
            PAGE_TITLE,
            f"""
                <h1>Upload rejected</h1>
                <article class="warning">
                  <p>The file <code>{escape(filename)}</code> could not be
                     parsed.</p>
                  <pre>{escape(str(exc))}</pre>
                </article>
                <p><a href="/status" role="button" class="outline">
                   Back to status</a></p>
            """,
            show_back_link=True, back_url="/status",
        )
    return render_page(
        PAGE_TITLE,
        _render_preview(report, filename),
        show_back_link=True, back_url="/status",
    )


@router.post("/apply")
async def apply(
    service: Annotated[ManualIngestService, Depends(get_sijia_service)],
    validation_id: Annotated[str, Form()],
    filename: Annotated[str, Form()],
) -> RedirectResponse:
    """Run the transactional apply and redirect back to /status with success flash."""
    result = await service.apply(validation_id, filename=filename)
    return RedirectResponse(
        url=f"/status?sijia_applied={result.upload_id}&rows={result.row_count}",
        status_code=303,
    )
