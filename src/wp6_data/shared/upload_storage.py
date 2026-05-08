"""Twin-agnostic upload storage for manually-uploaded source files.

Files land at ``{base_dir}/{source}/{sha256}.xlsx`` so they're addressable by
hash (the validation_id used by the upload flow) and grouped per source for
the 2-file prune policy (issue 008).

The audit table (``manual_uploads``) is the system of record for upload
provenance — pruning unlinks files from disk and marks the corresponding
audit rows ``file_pruned = true, file_path = NULL``, but never deletes the
row itself.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from psycopg_pool import AsyncConnectionPool


class UploadStorage:
    def __init__(self, base_dir: Path, pool: AsyncConnectionPool) -> None:
        self.base_dir = base_dir
        self.pool = pool

    def write(self, source: str, file_bytes: bytes) -> tuple[Path, str]:
        """Persist `file_bytes` under the per-source directory.

        The filename is the sha256 hex of the bytes, which makes writes
        idempotent (the same bytes always land at the same path) and lets
        callers use the hash as the validation_id.
        """
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        source_dir = self.base_dir / source
        source_dir.mkdir(parents=True, exist_ok=True)
        path = source_dir / f"{file_hash}.xlsx"
        path.write_bytes(file_bytes)
        return path, file_hash

    def read(self, path: Path) -> bytes:
        return path.read_bytes()

    async def prune(self, source: str) -> list[Path]:
        """Keep the latest two audit rows' files for `source` on disk.

        Older audit rows have their files unlinked and are marked
        ``file_path = NULL, file_pruned = TRUE``. The audit rows
        themselves are preserved indefinitely as upload history.
        """
        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, file_path FROM manual_uploads "
                    "WHERE source = %s AND file_path IS NOT NULL "
                    "ORDER BY uploaded_at DESC OFFSET 2",
                    (source,),
                )
                rows = await cur.fetchall()
                if rows:
                    await cur.execute(
                        "UPDATE manual_uploads "
                        "SET file_path = NULL, file_pruned = TRUE "
                        "WHERE id = ANY(%s)",
                        ([row_id for row_id, _ in rows],),
                    )
            await conn.commit()

        unlinked: list[Path] = []
        for _, file_path in rows:
            p = Path(file_path)
            if p.exists():
                p.unlink()
            unlinked.append(p)
        return unlinked
