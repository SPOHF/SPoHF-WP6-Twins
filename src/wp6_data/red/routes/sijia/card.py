"""Render the Sijia source section that appears on /status for admins.

Wired into ``TwinConfig.status_extras`` from `red/dashboard.py`. Returns
empty for non-admin users so the section is invisible to them.
"""

from fastapi import Request

from wp6_data.shared import render_card
from wp6_data.shared.auth import is_admin


def render_sijia_card(request: Request) -> str:
    if not is_admin(request):
        return ""

    flash = ""
    upload_id = request.query_params.get("sijia_applied")
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
        <p>Upload a Neurath measurements .xlsx file. You'll preview the parsed
           result before any data is written.</p>
        <form method="post" action="/sources/sijia/preview"
              enctype="multipart/form-data">
            <input type="file" name="file" accept=".xlsx" required>
            <button type="submit">Upload &amp; Preview</button>
        </form>
        <p style="margin-top:1rem">
            <a href="/sources/sijia/history">View upload history</a>
        </p>
    """
    return render_card("Manual source: Sijia (Neurath)", body)
