"""Red dashboard health check (no auth)."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for k8s probes (no auth required)."""
    return {"status": "ok"}
