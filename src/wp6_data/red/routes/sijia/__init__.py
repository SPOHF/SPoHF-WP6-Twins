"""Admin upload UI for the Sijia (Neurath) manual measurement source.

The upload form is rendered as a section on the shared `/status` page
(see `card.render_sijia_card`). The form posts to `/sources/sijia/preview`,
which renders a validation report; that report's Apply button posts to
`/sources/sijia/apply`, which runs the transactional ingest.

A separate admin-gated `GET /sources/sijia/history` page lists all
`manual_uploads` rows for audit/forensics (issue 011).
"""

from fastapi import APIRouter, Depends

from wp6_data.red.routes.sijia import history, upload
from wp6_data.shared.auth import verify_session_admin

router = APIRouter(
    prefix="/sources/sijia",
    dependencies=[Depends(verify_session_admin)],
)
router.include_router(upload.router)
router.include_router(history.router)
