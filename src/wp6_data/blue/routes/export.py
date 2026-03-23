"""Blue dashboard CSV export endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from wp6_data.blue.deps import EXPORT_DIR
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/download/{device:path}")
async def download_csv(device: str) -> FileResponse:
    """Download pre-generated CSV for a device."""
    safe_name = device.replace("/", "_").replace(" ", "_")
    csv_path = EXPORT_DIR / f"{safe_name}.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"No export available for {device}")

    return FileResponse(
        path=csv_path,
        media_type="text/csv",
        filename=f"{safe_name}.csv",
    )
