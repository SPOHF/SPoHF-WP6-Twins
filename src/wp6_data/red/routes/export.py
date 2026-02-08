"""Red dashboard CSV export endpoint."""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from wp6_data.red import deps

router = APIRouter()


@router.get("/download/{table}")
async def download_csv(table: str, user: str = Depends(deps.verify_auth)) -> FileResponse:
    """Download pre-generated CSV for a sensor table."""
    from fastapi import HTTPException

    csv_path = deps.EXPORT_DIR / f"{table}.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"No export available for {table}")

    return FileResponse(
        path=csv_path,
        media_type="text/csv",
        filename=f"{table}.csv",
    )
