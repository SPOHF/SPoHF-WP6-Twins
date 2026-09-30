"""Copy manual uploads from a PVC into the object store, and verify every byte.

Phase 3 of issue 061. Exports regenerate nightly and models refit, but these are
manually-uploaded source files that exist nowhere else — so unlike the other two
volumes, this one has to be *migrated* before the PVC is pruned, not simply
abandoned.

Designed to run INSIDE a dashboard pod, which is the one place that has both
sides: it still mounts the uploads PVC and already holds the object-store
credentials. No separate Job, and no credentials moved around. Piped in over
stdin, so the running image does not need to contain this file:

    kubectl -n spohf-system exec -i <pod> -c dashboard -- \
        python - --twin red < scripts/migrate-uploads-to-object-store.py

Reports by default and writes nothing. Pass --apply to copy.

**Deliberately self-contained.** It builds its own store from
``ObjectStoreSettings`` and an explicit prefix rather than importing a twin's
``deps.UPLOADS_STORE``, because the whole point is to run it against the image
that is deployed *now* — which is the one from before uploads moved, and has no
such attribute. A migration tool that requires the migration to have shipped is
no use.

What it does, in order:

1. Walks the PVC and copies every file to the same relative key. *Every* file —
   not only those the audit table references. A file nobody references is still
   data, and deciding it is junk is not this script's call.
2. Verifies each copy by reading it back and comparing sha256. A copy that does
   not verify makes the whole run fail, loudly, with a non-zero exit.
3. Cross-checks against `manual_uploads` and reports drift both ways:
   - **unresolved**: a live audit row whose file is not on the PVC. Do NOT read
     this as "lost" — see below.
   - **orphan**: a file on the PVC no live audit row points at. Copied anyway.

An unresolved row usually means the *same object* was deleted on behalf of a
different row. Uploads are content-addressed, so re-uploading identical bytes
produces a second row naming the same key, and `prune` used to delete per row
without checking whether a retained row still needed it. That destroyed the live
copies of blue's `long_data` workbooks (re-issued yearly, so guaranteed to hit
it) and red's `sijia` seed. Fixed in `shared.upload_storage.prune`; this script
reports the symptom, which can still appear for rows pruned before the fix.

Before concluding anything is lost, check whether another row shares the hash,
and whether the bytes exist under a different name — red's seed turned out to be
sitting at the PVC root as `sijia_seed.xlsx`, hashing to exactly the key its
"unresolved" row named.

Idempotent: the store is content-addressed and `put` replaces, so a second run
re-copies and re-verifies without changing the outcome.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path


def _twin_parts(twin: str) -> tuple[Path, str, str]:
    """(pvc_dir, store_prefix, tsdb_env) for a twin.

    The prefix is spelled out rather than imported from the twin's deps: see the
    module docstring on why this must not depend on the new code.
    """
    if twin == "red":
        return Path("/data/manual-uploads"), "red/manual-uploads", "WP6_RED_TSDB_URL"
    if twin == "blue":
        return (
            Path("/data/blue-manual-uploads"), "blue/manual-uploads", "WP6_TSDB_URL",
        )
    raise SystemExit(f"unknown twin {twin!r} (expected red or blue)")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _key_of(stored: str) -> str:
    """The object key an audit row's ``file_path`` refers to.

    Same rule as ``shared.upload_storage.stored_key``, repeated here rather than
    imported for the reason in the module docstring: the deployed image does not
    have it yet. Both an absolute path and a bare key end in ``{source}/{name}``.
    """
    parts = [p for p in stored.replace("\\", "/").split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else stored


def _local_files(root: Path) -> list[tuple[str, Path]]:
    """(key, path) for every file under ``root``, keyed by relative path.

    The relative path *is* the key: the on-PVC layout was already
    ``{source}/{sha256}{suffix}``, which is an object-key scheme wearing a path,
    so preserving it keeps the audit table's references meaningful.
    """
    if not root.is_dir():
        return []
    return sorted(
        (str(p.relative_to(root)), p)
        for p in root.rglob("*")
        if p.is_file() and not p.name.startswith(".")
    )


async def _audit_paths(dsn: str) -> list[str]:
    """`file_path` for every live (un-pruned) audit row."""
    import psycopg

    conn = await psycopg.AsyncConnection.connect(dsn)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT file_path FROM manual_uploads WHERE file_path IS NOT NULL",
            )
            return [r[0] for r in await cur.fetchall()]
    finally:
        await conn.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--twin", required=True, choices=["red", "blue"])
    parser.add_argument(
        "--apply", action="store_true",
        help="actually copy; without it the run only reports",
    )
    args = parser.parse_args()

    pvc_dir, prefix, tsdb_env = _twin_parts(args.twin)

    from wp6_data.config import ObjectStoreSettings
    from wp6_data.shared.blob import make_store

    store = make_store(ObjectStoreSettings(), prefix=prefix)

    files = _local_files(pvc_dir)
    print(f"twin       {args.twin}")
    print(f"prefix     {prefix}")
    print(f"pvc        {pvc_dir}")
    print(f"files      {len(files)}")
    print(f"mode       {'APPLY' if args.apply else 'report only'}")
    print()

    # --- drift, before touching anything ------------------------------------
    dsn = os.environ.get(tsdb_env, "")
    on_pvc = {key for key, _ in files}
    if dsn:
        referenced = {_key_of(p) for p in await _audit_paths(dsn)}
        dangling = sorted(referenced - on_pvc)
        orphans = sorted(on_pvc - referenced)
        if dangling:
            print("UNRESOLVED — live audit rows whose file is not on the PVC.")
            print("  NOT necessarily lost. Uploads are content-addressed, so check")
            print("  for another row with the same hash, and for the bytes under a")
            print("  different name, before concluding anything. See the module")
            print("  docstring.")
            for key in dangling:
                print(f"    {key}")
            print()
        if orphans:
            print("ORPHANS — files no live audit row points at. Copied anyway.")
            for key in orphans:
                print(f"    {key}")
            print()
    else:
        print(f"WARNING: {tsdb_env} unset — skipping the audit cross-check.\n")

    # --- copy + verify -------------------------------------------------------
    failures: list[str] = []
    copied = 0
    for key, path in files:
        raw = path.read_bytes()
        digest = _sha256(raw)
        if not args.apply:
            print(f"  would copy  {len(raw):>10,}  {key}")
            continue

        await store.put(key, raw)
        # Read it back rather than trusting the write: this is the one dataset
        # that cannot be regenerated, so "probably fine" is not good enough.
        back = await store.try_get(key)
        if back is None:
            failures.append(f"{key}: absent after write")
        elif _sha256(back) != digest:
            failures.append(f"{key}: sha256 mismatch after write")
        else:
            copied += 1
            print(f"  copied      {len(raw):>10,}  {key}  sha256 ok")

    print()
    if not args.apply:
        print(f"Report only. Re-run with --apply to copy {len(files)} file(s).")
        return 0

    if failures:
        print(f"FAILED — {len(failures)} file(s) did not verify:")
        for f in failures:
            print(f"    {f}")
        print("\nDo NOT prune the PVC.")
        return 1

    print(f"OK — {copied}/{len(files)} file(s) copied and verified by sha256.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
