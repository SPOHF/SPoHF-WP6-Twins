"""Twin-agnostic manual-upload capability.

A manual source is anything that arrives as a file an admin uploads (no
automated sensor pipeline): the red Sijia Excel, the blue insect CSV, and
future sources. The per-source seam is a single :class:`ManualSource`
descriptor; everything else — content-addressed storage, transactional
all-or-nothing apply, the ``manual_uploads`` audit trail, the 2-file prune,
the preview/apply/history UI, and the CLI — is shared here.
"""

from wp6_data.shared.manual_ingest.cli import run_ingest
from wp6_data.shared.manual_ingest.routes import make_card, make_source_router
from wp6_data.shared.manual_ingest.service import ApplyResult, ManualIngestService
from wp6_data.shared.manual_ingest.source import ManualSource
from wp6_data.shared.manual_ingest.types import (
    ManualParseError,
    Reading,
    SkippedRow,
    ValidationReport,
)

__all__ = [
    "ApplyResult",
    "ManualIngestService",
    "ManualParseError",
    "ManualSource",
    "Reading",
    "SkippedRow",
    "ValidationReport",
    "make_card",
    "make_source_router",
    "run_ingest",
]
