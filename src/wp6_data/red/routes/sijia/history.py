"""Audit history page (issue 011).

Read-only listing of `manual_uploads` rows for ``source = 'sijia'`` in
reverse-chronological order. Pruned uploads still appear — only the file
on disk is gone, the audit row is preserved indefinitely.
"""

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from psycopg.rows import dict_row

from wp6_data.db.pool import get_pool
from wp6_data.red.sijia.parser import SOURCE
from wp6_data.shared import render_page

router = APIRouter()

PAGE_TITLE = "Sijia upload history"


def _format_row(row: dict) -> str:
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


@router.get("/history", response_class=HTMLResponse)
async def history() -> str:
    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, uploaded_at, file_hash, filename, row_count, "
            "       file_pruned, error "
            "FROM manual_uploads "
            "WHERE source = %s "
            "ORDER BY uploaded_at DESC",
            (SOURCE,),
        )
        rows = await cur.fetchall()

    if not rows:
        body_html = "<p>No uploads yet.</p>"
    else:
        body_rows = "".join(_format_row(r) for r in rows)
        body_html = f"""
            <table>
                <thead>
                    <tr>
                        <th>Uploaded at</th>
                        <th>Hash</th>
                        <th>Filename</th>
                        <th>Rows</th>
                        <th>File state</th>
                        <th>Error</th>
                    </tr>
                </thead>
                <tbody>{body_rows}</tbody>
            </table>
        """

    body = f"""
        <h1>Sijia upload history</h1>
        <p>Audit log of every Sijia upload. Pruned uploads still appear;
           only the latest 2 files per source are kept on disk.</p>
        {body_html}
    """
    return render_page(
        PAGE_TITLE, body, show_back_link=True, back_url="/status",
    )
