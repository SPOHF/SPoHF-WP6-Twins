"""Generic CLI runner shared by every manual-source ingest command.

A per-twin console script (``wp6-red-ingest-sijia``,
``wp6-blue-ingest-insects``) is a thin wrapper that builds the twin's
``ManualIngestService`` and delegates the validate→apply round-trip here, so
the CLI and the admin web UI exercise exactly one apply path.
"""

from __future__ import annotations

from pathlib import Path

from wp6_data.shared.manual_ingest.service import ApplyResult, ManualIngestService


async def run_ingest(service: ManualIngestService, path: Path) -> ApplyResult:
    """Validate and apply the file at ``path`` through ``service``.

    Structural parse errors propagate (the source's parse_error) so the CLI
    fast-fails without touching the DB — same contract as the web preview.
    """
    file_bytes = path.read_bytes()
    report = await service.validate(file_bytes)
    return await service.apply(report.file_hash, filename=path.name)
