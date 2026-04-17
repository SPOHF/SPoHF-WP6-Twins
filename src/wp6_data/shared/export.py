"""Shared CSV export helpers used by both blue and red dashboards."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from wp6_data.shared.auth import verify_session_user


def clear_export_dir(export_dir: Path) -> int:
    """Remove all CSV and metadata files from the export directory.

    Returns the number of files removed.
    """
    removed = 0
    for f in export_dir.glob("*.csv"):
        f.unlink()
        removed += 1
    metadata = export_dir / "metadata.json"
    if metadata.exists():
        metadata.unlink()
        removed += 1
    return removed


def get_export_metadata(export_dir: Path) -> dict | None:
    """Get metadata about available CSV exports."""
    metadata_path = export_dir / "metadata.json"
    if not metadata_path.exists():
        return None
    try:
        return json.loads(metadata_path.read_text())
    except Exception:
        return None


def render_download_link(name: str, available_exports: dict[str, str]) -> str:
    """Render an HTML download link cell for a CSV export.

    Returns a link with timestamp if the export exists, or "-" otherwise.
    """
    if name in available_exports:
        export_ts = available_exports[name][:16].replace("T", " ") + " UTC"
        return (
            f'<a href="/download/{name}" title="Download CSV">CSV</a> '
            f"<small>({export_ts})</small>"
        )
    return "-"


def make_download_router(
    export_dir: Path,
    *,
    sanitise: bool = False,
) -> APIRouter:
    """Create an authenticated CSV download router.

    Args:
        export_dir: Directory containing pre-generated CSV files.
        sanitise: If True, replace ``/`` and spaces in the name with ``_``
                  before resolving the filename (needed for blue device names).
    """
    router = APIRouter(dependencies=[Depends(verify_session_user)])

    path_param = "/download/{name:path}" if sanitise else "/download/{name}"

    @router.get(path_param)
    async def download_csv(name: str) -> FileResponse:
        """Download a pre-generated CSV export."""
        safe_name = name.replace("/", "_").replace(" ", "_") if sanitise else name
        csv_path = export_dir / f"{safe_name}.csv"
        if not csv_path.exists():
            raise HTTPException(status_code=404, detail=f"No export available for {name}")

        return FileResponse(
            path=csv_path,
            media_type="text/csv",
            filename=f"{safe_name}.csv",
        )

    return router
