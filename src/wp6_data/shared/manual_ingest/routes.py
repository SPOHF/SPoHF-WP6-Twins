"""Route + card factory for a manual source's admin upload UI.

``make_source_router`` builds the admin-gated ``/sources/{slug}`` router
(preview + apply + history); ``make_card`` builds the ``/status`` card. Both
are produced from a ``ManualSource`` descriptor, so every source shares one
implementation. Slug, display name, row noun and accepted suffix are the
only things that vary (manual data is always keyed by the ``source``
column).
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from psycopg.rows import dict_row

from wp6_data.db.pool import get_pool
from wp6_data.shared import render_card, render_page
from wp6_data.shared.auth import is_admin, verify_session_admin
from wp6_data.shared.manual_ingest.service import ManualIngestService
from wp6_data.shared.manual_ingest.source import ManualSource
from wp6_data.shared.manual_ingest.types import ValidationReport


def _format_date_range(date_range) -> str:
    if date_range is None:
        return "—"
    start, end = date_range
    return f"{start.isoformat()} → {end.isoformat()}"


def _render_warnings(report: ValidationReport) -> str:
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
            f"<ul>{items}</ul></article>"
        )
    if report.sensors_removed:
        items = "".join(
            f"<li><code>{escape(s)}</code></li>" for s in report.sensors_removed
        )
        parts.append(
            f'<article class="warning">'
            f"<strong>Sensors missing from new upload:</strong>"
            f"<ul>{items}</ul></article>"
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


def _render_preview(
    source: ManualSource, report: ValidationReport, filename: str,
) -> str:
    devices_html = ", ".join(
        f"<code>{escape(d)}</code>" for d in report.devices
    ) or "—"
    sensors_html = ", ".join(
        f"<code>{escape(s)}</code>" for s in report.sensors
    ) or "—"
    return f"""
        <h1>Preview — {escape(source.display_name)} upload</h1>
        <p>File: <code>{escape(filename)}</code></p>
        <p>Hash: <code>{report.file_hash[:12]}…</code> ·
           Size: {report.file_size:,} bytes</p>

        {_render_warnings(report)}

        <article>
          <h3>Parsed</h3>
          <ul>
            <li>{escape(source.row_noun)}: <strong>{report.total_rows}</strong>
                ({report.valid_rows} valid · {len(report.skipped_rows)} skipped)</li>
            <li>Rows to insert (after aggregation):
                <strong>{report.emitted_row_count}</strong></li>
            <li>Date range:
                <strong>{_format_date_range(report.date_range)}</strong></li>
            <li>Devices in upload: {devices_html}</li>
            <li>Sensors in upload: {sensors_html}</li>
          </ul>
          {_render_skipped(report)}
        </article>

        <article>
          <h3>Existing data for source <code>{escape(source.slug)}</code></h3>
          <ul>
            <li>Row count: <strong>{report.existing_row_count}</strong></li>
            <li>Date range:
                <strong>{_format_date_range(report.existing_date_range)}</strong></li>
          </ul>
        </article>

        <article>
          <h3>Apply</h3>
          <p>Pressing Apply will atomically replace all existing
             <code>source = {escape(source.categorical_value)}</code>
             data with the parsed rows above.</p>
          <form method="post" action="/sources/{source.slug}/apply">
            <input type="hidden" name="validation_id" value="{report.file_hash}">
            <input type="hidden" name="filename" value="{escape(filename)}">
            <button type="submit">Apply</button>
            <a href="/status" role="button" class="outline">Cancel</a>
          </form>
        </article>
    """


def _format_history_row(row: dict) -> str:
    uploaded_at = row["uploaded_at"].strftime("%Y-%m-%d %H:%M:%S UTC")
    file_hash_short = row["file_hash"][:12] + "…"
    pruned_badge = "<mark>pruned</mark>" if row["file_pruned"] else ""
    error = row.get("error") or ""
    error_html = (
        f'<code class="error">{escape(error)}</code>' if error else "—"
    )
    return f"""
        <tr>
            <td>{uploaded_at}</td>
            <td><code>{file_hash_short}</code></td>
            <td>{escape(row["filename"])}</td>
            <td>{row["row_count"]:,}</td>
            <td>{pruned_badge}</td>
            <td>{error_html}</td>
        </tr>
    """


def make_source_router(
    source: ManualSource, get_service: Callable[..., ManualIngestService],
) -> APIRouter:
    """Build the admin-gated ``/sources/{slug}`` router for ``source``.

    ``get_service`` is a FastAPI dependency returning the twin's
    ``ManualIngestService`` bound to ``source``.
    """
    router = APIRouter(
        prefix=f"/sources/{source.slug}",
        dependencies=[Depends(verify_session_admin)],
    )
    page_title = f"{source.display_name} upload"

    @router.post("/preview", response_class=HTMLResponse)
    async def preview(
        file: UploadFile = File(),  # noqa: B008
        service: ManualIngestService = Depends(get_service),  # noqa: B008
    ) -> str:
        """Persist the bytes, validate, render the preview.

        Structural parse errors are rendered as a friendly rejection page
        rather than a 500 — admins need to see *what* was wrong to fix it.
        """
        file_bytes = await file.read()
        filename = file.filename or f"uploaded{source.file_suffix}"
        try:
            report = await service.validate(file_bytes)
        except source.parse_error as exc:
            return render_page(
                page_title,
                f"""
                    <h1>Upload rejected</h1>
                    <article class="warning">
                      <p>The file <code>{escape(filename)}</code> could not
                         be parsed.</p>
                      <pre>{escape(str(exc))}</pre>
                    </article>
                    <p><a href="/status" role="button" class="outline">
                       Back to status</a></p>
                """,
                show_back_link=True, back_url="/status",
            )
        return render_page(
            page_title,
            _render_preview(source, report, filename),
            show_back_link=True, back_url="/status",
        )

    @router.post("/apply")
    async def apply(
        validation_id: str = Form(),  # noqa: B008
        filename: str = Form(),  # noqa: B008
        service: ManualIngestService = Depends(get_service),  # noqa: B008
    ) -> RedirectResponse:
        result = await service.apply(validation_id, filename=filename)
        return RedirectResponse(
            url=(
                f"/status?{source.slug}_applied={result.upload_id}"
                f"&rows={result.row_count}"
            ),
            status_code=303,
        )

    @router.get("/history", response_class=HTMLResponse)
    async def history() -> str:
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor(
            row_factory=dict_row,
        ) as cur:
            await cur.execute(
                "SELECT id, uploaded_at, file_hash, filename, row_count, "
                "       file_pruned, error "
                "FROM manual_uploads WHERE source = %s "
                "ORDER BY uploaded_at DESC",
                (source.slug,),
            )
            rows = await cur.fetchall()

        if not rows:
            body_html = "<p>No uploads yet.</p>"
        else:
            body_rows = "".join(_format_history_row(r) for r in rows)
            body_html = f"""
                <table>
                    <thead><tr>
                        <th>Uploaded at</th><th>Hash</th><th>Filename</th>
                        <th>Rows</th><th>File state</th><th>Error</th>
                    </tr></thead>
                    <tbody>{body_rows}</tbody>
                </table>
            """
        body = f"""
            <h1>{escape(source.display_name)} upload history</h1>
            <p>Audit log of every {escape(source.display_name)} upload.
               Pruned uploads still appear; only the latest 2 files per
               source are kept on disk.</p>
            {body_html}
        """
        return render_page(
            page_title, body, show_back_link=True, back_url="/status",
        )

    return router


def make_card(source: ManualSource) -> Callable[[Request], str]:
    """Build the ``/status`` upload card for ``source`` (admin-only).

    Returns "" for non-admins so the section is invisible to them.
    """

    def render(request: Request) -> str:
        if not is_admin(request):
            return ""

        flash = ""
        upload_id = request.query_params.get(f"{source.slug}_applied")
        rows = request.query_params.get("rows")
        if upload_id:
            flash = (
                f'<article class="success">'
                f"Applied <strong>{int(rows or 0):,}</strong> rows · "
                f"upload #<code>{int(upload_id)}</code>"
                f"</article>"
            )

        body = f"""
            {flash}
            <p>{escape(source.upload_hint)} You'll preview the parsed result
               before any data is written.</p>
            <form method="post" action="/sources/{source.slug}/preview"
                  enctype="multipart/form-data">
                <input type="file" name="file"
                       accept="{escape(source.accept)}" required>
                <button type="submit">Upload &amp; Preview</button>
            </form>
            <p style="margin-top:1rem">
                <a href="/sources/{source.slug}/history">
                   View upload history</a>
            </p>
        """
        return render_card(f"Manual source: {source.display_name}", body)

    return render
