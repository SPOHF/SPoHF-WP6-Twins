"""Shared CSV export helpers used by both blue and red dashboards.

Exports live in a :class:`~wp6_data.shared.blob.BlobStore` rather than on a
directory. On a dev machine that store is still a directory, so nothing about
the local layout changes; in the cluster it is a prefix in the shared bucket,
which is what lets the dashboard Deployment drop its ReadWriteOnce PVC and
roll instead of being torn down first. See
``issues/061-object-storage-to-end-deploy-downtime.md``.

The store handed in here is already scoped to one twin's exports, so keys are
bare names (``s2100-01-par.csv``) with no twin or directory component.
"""

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response

from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.blob import BlobStore

log = structlog.get_logger()

#: Where the per-device export timestamps live, beside the CSVs.
METADATA_KEY = "metadata.json"

CSV_SUFFIX = ".csv"


def csv_key(name: str) -> str:
    """The key holding the export for device ``name``."""
    return f"{name}{CSV_SUFFIX}"


def sanitise_name(name: str) -> str:
    """Flatten a device name into something usable as a key.

    Blue's device names contain ``/`` and spaces, which would otherwise create
    accidental key hierarchy in the bucket and accidental subdirectories on
    disk.
    """
    return name.replace("/", "_").replace(" ", "_")


async def clear_exports(store: BlobStore) -> int:
    """Remove every CSV and the metadata file. Returns how many were removed.

    Deliberately not "delete everything in the store": the twin's export prefix
    should hold nothing else, but an unexpected object is better left in place
    for someone to notice than silently swept up by a nightly job.
    """
    keys = await store.list("")
    doomed = [k for k in keys if k.endswith(CSV_SUFFIX) or k == METADATA_KEY]
    if not doomed:
        return 0
    return await store.delete(*doomed)


async def write_export_metadata(store: BlobStore, metadata: dict) -> None:
    """Record which devices were exported and when."""
    await store.put(
        METADATA_KEY,
        json.dumps(metadata, indent=2).encode("utf-8"),
        content_type="application/json",
    )


async def get_export_metadata(store: BlobStore) -> dict | None:
    """Metadata about available CSV exports, or ``None`` when there is none.

    A missing or unreadable metadata file means "no exports yet", which the
    home page already renders. An export job that has never run, and one whose
    output is corrupt, are the same thing to a caller that can only offer
    download links.

    **An unreachable store is also "no exports yet."** This is called while
    rendering the home page, so letting a connection error escape would take
    the whole dashboard down over a decorative set of download links -- the
    same failure shape as issue 033, where an unreachable identity provider
    crash-looped both twins because startup pre-cached URLs it did not yet
    need. Fail fast on configuration, fail soft on dependencies.
    """
    try:
        raw = await store.try_get(METADATA_KEY)
    except Exception as exc:
        log.warning("export_metadata_unavailable", error=str(exc))
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
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
    store: BlobStore,
    *,
    sanitise: bool = False,
) -> APIRouter:
    """Create an authenticated CSV download router.

    Args:
        store: Blob store holding the pre-generated CSVs, scoped to this twin.
        sanitise: If True, flatten ``/`` and spaces in the name before
                  resolving the key (needed for blue device names).
    """
    router = APIRouter(dependencies=[Depends(verify_session_user)])

    path_param = "/download/{name:path}" if sanitise else "/download/{name}"

    @router.get(path_param)
    async def download_csv(name: str) -> Response:
        """Download a pre-generated CSV export.

        Read whole rather than streamed: a device CSV is around a megabyte, and
        the store's own read is a single round trip. If an export ever grows
        enough for that to matter, a presigned URL is the better answer than a
        streaming proxy -- it takes the bytes off this process entirely.
        """
        safe_name = sanitise_name(name) if sanitise else name
        try:
            data = await store.try_get(csv_key(safe_name))
        except Exception as exc:
            # 503, not 404: the export may well exist. Telling the user "no
            # export available" when the store is simply unreachable sends
            # them looking for the wrong problem.
            log.warning("export_download_unavailable", device=name, error=str(exc))
            raise HTTPException(
                status_code=503, detail="Export storage is unavailable",
            ) from exc
        if data is None:
            raise HTTPException(status_code=404, detail=f"No export available for {name}")

        return Response(
            content=data,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
        )

    return router
