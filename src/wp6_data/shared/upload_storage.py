"""Twin-agnostic upload storage for manually-uploaded source files.

Files land at ``{source}/{sha256}{suffix}`` in a
:class:`~wp6_data.shared.blob.BlobStore` — addressable by hash (the
validation_id the upload flow uses) and grouped per source for the 2-file prune
policy. ``suffix`` comes from the source descriptor and defaults to ``.xlsx`` so
callers that omit it are unaffected.

This was a directory on a ReadWriteOnce PVC, which is what kept both dashboards
on ``strategy: Recreate`` and made a deploy a full outage: a block volume
attaches to exactly one node, so two generations of the pod cannot coexist. The
layout was already an object-key scheme wearing a path — content-addressed, no
random access, no appends — so moving it removes the last such volume. See
``issues/061-object-storage-to-end-deploy-downtime.md``.

The audit table (``manual_uploads``) remains the system of record for upload
provenance: pruning removes the object and marks the corresponding audit rows
``file_pruned = true, file_path = NULL``, but never deletes the row itself.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

    from wp6_data.shared.blob import BlobStore


def stored_key(value: str) -> str:
    """Normalise a ``manual_uploads.file_path`` value to an object key.

    The column holds a key for anything written since the move to object
    storage, but rows from before it hold an absolute filesystem path
    (``/data/manual-uploads/sijia/<sha>.xlsx``). Prune reads the column back, so
    without this those rows would try to delete a key that cannot exist, leave
    the migrated object orphaned, and still mark the row pruned — a silent leak
    rather than an error.

    Both shapes end in ``{source}/{name}``, which is exactly the key.
    """
    parts = [p for p in value.replace("\\", "/").split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else value


class UploadStorage:
    def __init__(self, store: BlobStore, pool: AsyncConnectionPool) -> None:
        self.store = store
        self.pool = pool

    def key_for(self, source: str, file_hash: str, suffix: str = ".xlsx") -> str:
        """Where the file for ``file_hash`` lives — the single place that knows
        the ``{source}/{hash}{suffix}`` layout, so write and the service's
        read-back agree."""
        return f"{source}/{file_hash}{suffix}"

    async def write(
        self, source: str, file_bytes: bytes, suffix: str = ".xlsx",
    ) -> tuple[str, str]:
        """Persist ``file_bytes`` under the per-source prefix.

        The name is the sha256 hex of the bytes, which makes writes idempotent
        (the same bytes always land at the same key) and lets callers use the
        hash as the validation_id. Returns ``(key, file_hash)``.
        """
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        key = self.key_for(source, file_hash, suffix)
        await self.store.put(key, file_bytes)
        return key, file_hash

    async def read(self, key: str) -> bytes:
        return await self.store.get(key)

    async def prune(self, source: str) -> list[str]:
        """Keep the latest two audit rows' files for ``source``.

        Older audit rows have their objects removed and are marked
        ``file_path = NULL, file_pruned = TRUE``. The audit rows themselves are
        preserved indefinitely as upload history.

        **An object a retained row still points at is never deleted.** Uploads
        are content-addressed, so re-uploading identical bytes produces a second
        audit row naming the *same* object — which is exactly what happens with
        ``long_data``, where the same yearly workbook is re-issued. Deleting per
        row without checking destroyed the file the newest row referenced: blue
        lost both live ``long_data`` uploads and red lost its ``sijia`` seed that
        way, each looking like a dangling audit row long afterwards.
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

                # The keys the rows we are KEEPING still depend on. Read inside
                # the same transaction as the select above, so a concurrent
                # upload cannot slip between the two and have its object deleted.
                await cur.execute(
                    "SELECT file_path FROM manual_uploads "
                    "WHERE source = %s AND file_path IS NOT NULL "
                    "ORDER BY uploaded_at DESC LIMIT 2",
                    (source,),
                )
                retained = {stored_key(p) for (p,) in await cur.fetchall()}

                if rows:
                    await cur.execute(
                        "UPDATE manual_uploads "
                        "SET file_path = NULL, file_pruned = TRUE "
                        "WHERE id = ANY(%s)",
                        ([row_id for row_id, _ in rows],),
                    )
            await conn.commit()

        # Marking the row pruned is right either way — it is no longer one of the
        # latest two. Only the object is spared.
        keys = sorted({stored_key(stored) for _, stored in rows} - retained)
        if keys:
            await self.store.delete(*keys)
        return keys
