"""Twin-agnostic blob storage: a key-to-bytes map, backed by disk or by S3.

Why this exists: the dashboards' PVCs (exports, models, manual uploads) are
``ReadWriteOnce`` on a block StorageClass, and a block volume attaches to exactly
one node. Two generations of the pod therefore cannot coexist, which is why both
dashboards run ``strategy: Recreate`` and why a deploy is a full outage. None of
those volumes needs POSIX semantics -- no random access, no appends, no locking
-- so moving them to object storage removes the exclusivity and lets the
deployments roll. See ``issues/061-object-storage-to-end-deploy-downtime.md``.

The interface is deliberately small: put, get, exists, list, delete. That is the
whole of what the call sites do today (``UploadStorage`` is already
content-addressed by sha256 -- ``path_for`` builds an object key and calls it a
path), and a smaller surface is a smaller thing to reimplement per backend.

Async, even though ``boto3`` is synchronous and local file IO is cheap: a 4MB
model read measured 620ms against the real store, which would stall the event
loop and every in-flight request with it. Blocking work goes through
``asyncio.to_thread``.

Nothing here knows about red or blue. Callers supply their own key prefixes.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import uuid4

from botocore.exceptions import ClientError

from wp6_data.config import ObjectStoreSettings


class BlobNotFound(KeyError):
    """No object at that key."""


@runtime_checkable
class BlobStore(Protocol):
    """A flat key-to-bytes map.

    Keys are ``/``-separated strings (``exports/s2100-01-par.csv``). They are
    not paths: there are no directories, no relative segments, and no guarantee
    that a "directory" exists before something is written into it.
    """

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        """Write ``data`` at ``key``, replacing whatever was there.

        Atomic: a reader sees either the old object or the new one, never a
        mix. This is stronger than the ``open(path, 'wb')`` it replaces, which
        can leave a truncated file if the process dies mid-write.
        """
        ...

    async def get(self, key: str) -> bytes:
        """The bytes at ``key``. Raises :class:`BlobNotFound` if absent."""
        ...

    async def try_get(self, key: str) -> bytes | None:
        """The bytes at ``key``, or ``None`` if absent.

        Exists because most callers here treat "missing" as an ordinary
        outcome rather than an error -- a model that has not been fitted yet,
        an export that has not run -- and exception-driven control flow at
        those call sites reads worse than a ``None`` check.
        """
        ...

    async def exists(self, key: str) -> bool:
        """Whether anything is stored at ``key``."""
        ...

    async def list(self, prefix: str) -> list[str]:
        """Every key beginning with ``prefix``, sorted.

        Returns full keys, not names relative to the prefix, so the result can
        be fed straight back to :meth:`get` and :meth:`delete`.
        """
        ...

    async def delete(self, *keys: str) -> int:
        """Remove ``keys``. Returns how many existed. Missing keys are not an error."""
        ...


class LocalBlobStore:
    """A :class:`BlobStore` over a directory tree.

    For development and tests. Keys become paths under ``root``, so the layout
    on disk matches the key layout in the bucket and a dev machine's
    ``exports-red/`` stays browsable.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        """Resolve ``key`` beneath ``root``, refusing anything that escapes it.

        Keys reach this from HTTP routes (the download path is user-supplied),
        so ``../`` has to be rejected rather than normalised away quietly.
        """
        candidate = (self.root / key).resolve()
        root = self.root.resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError(f"key escapes store root: {key!r}")
        return candidate

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        # content_type is meaningless on a filesystem; accepted so the two
        # backends stay interchangeable.
        del content_type

        def _write() -> None:
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-rename, so this backend keeps the atomicity promise the
            # interface makes. os.replace is atomic within a filesystem, and the
            # temp file is a sibling precisely to stay on one.
            #
            # The suffix is unique per write, not per key: two writers racing on
            # one key would otherwise share a temp name, and the first rename
            # would pull the file out from under the second -- which fails with
            # FileNotFoundError instead of the last-writer-wins the interface
            # promises and the S3 backend delivers.
            tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                tmp.write_bytes(data)
                tmp.replace(path)
            finally:
                tmp.unlink(missing_ok=True)

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes:
        data = await self.try_get(key)
        if data is None:
            raise BlobNotFound(key)
        return data

    async def try_get(self, key: str) -> bytes | None:
        def _read() -> bytes | None:
            path = self._path(key)
            if not path.is_file():
                return None
            return path.read_bytes()

        return await asyncio.to_thread(_read)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(lambda: self._path(key).is_file())

    async def list(self, prefix: str) -> list[str]:
        def _list() -> list[str]:
            root = self.root.resolve()
            if not root.is_dir():
                return []
            found = [
                str(p.resolve().relative_to(root))
                for p in root.rglob("*")
                if p.is_file() and not p.name.startswith(".")
            ]
            return sorted(k for k in found if k.startswith(prefix))

        return await asyncio.to_thread(_list)

    async def delete(self, *keys: str) -> int:
        def _delete() -> int:
            removed = 0
            for key in keys:
                path = self._path(key)
                if path.is_file():
                    path.unlink()
                    removed += 1
            return removed

        return await asyncio.to_thread(_delete)

    async def clear(self) -> None:
        """Drop everything. Tests and local resets only."""
        await asyncio.to_thread(lambda: shutil.rmtree(self.root, ignore_errors=True))


class S3BlobStore:
    """A :class:`BlobStore` over an S3-compatible bucket.

    Built for the CloudStack/MinIO store at educloud, but nothing here is
    specific to it beyond the defaults carried in
    :class:`~wp6_data.config.ObjectStoreSettings` (path-style addressing, an
    explicit CA bundle).

    ``boto3`` is synchronous, so every call goes through ``asyncio.to_thread``.
    The client is built once and shared: botocore clients are safe for
    concurrent *calls*, unlike concurrent construction.
    """

    def __init__(self, settings: ObjectStoreSettings) -> None:
        if not settings.enabled:
            raise ValueError("object store is not configured (WP6_S3_BUCKET is empty)")
        self.bucket = settings.bucket
        self._client = _build_client(settings)

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        kwargs = {"Bucket": self.bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        await asyncio.to_thread(lambda: self._client.put_object(**kwargs))

    async def get(self, key: str) -> bytes:
        data = await self.try_get(key)
        if data is None:
            raise BlobNotFound(key)
        return data

    async def try_get(self, key: str) -> bytes | None:
        def _read() -> bytes | None:
            try:
                return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            except self._client.exceptions.NoSuchKey:
                return None
            except ClientError as e:
                # MinIO answers a missing key on some paths with a bare 404
                # rather than NoSuchKey, so match on status too.
                if _is_not_found(e):
                    return None
                raise

        return await asyncio.to_thread(_read)

    async def exists(self, key: str) -> bool:
        def _head() -> bool:
            try:
                self._client.head_object(Bucket=self.bucket, Key=key)
            except ClientError as e:
                if _is_not_found(e):
                    return False
                raise
            return True

        return await asyncio.to_thread(_head)

    async def list(self, prefix: str) -> list[str]:
        def _list() -> list[str]:
            paginator = self._client.get_paginator("list_objects_v2")
            return sorted(
                obj["Key"]
                for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix)
                for obj in page.get("Contents", [])
            )

        return await asyncio.to_thread(_list)

    async def delete(self, *keys: str) -> int:
        if not keys:
            return 0

        def _delete() -> int:
            # delete_objects reports success for keys that never existed, so
            # the count has to come from what was actually there beforehand.
            present = [k for k in keys if _head_ok(self._client, self.bucket, k)]
            for chunk in (present[i : i + 1000] for i in range(0, len(present), 1000)):
                self._client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": [{"Key": k} for k in chunk]},
                )
            return len(present)

        return await asyncio.to_thread(_delete)


class PrefixedBlobStore:
    """A view of another store with every key under a fixed prefix.

    One bucket holds every twin's exports, models and uploads, so each caller
    gets a view scoped to its own corner (``red/exports/``) and never has to
    thread the prefix through its own code. Keys returned by :meth:`list` are
    relative to the prefix, so a caller sees only its own namespace.
    """

    def __init__(self, inner: BlobStore, prefix: str) -> None:
        self.inner = inner
        self.prefix = prefix if prefix.endswith("/") or not prefix else prefix + "/"

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        await self.inner.put(self._key(key), data, content_type=content_type)

    async def get(self, key: str) -> bytes:
        try:
            return await self.inner.get(self._key(key))
        except BlobNotFound:
            # Re-raise with the caller's key, not the prefixed one: the prefix
            # is this class's business and leaking it into errors makes the
            # message confusing at the call site.
            raise BlobNotFound(key) from None

    async def try_get(self, key: str) -> bytes | None:
        return await self.inner.try_get(self._key(key))

    async def exists(self, key: str) -> bool:
        return await self.inner.exists(self._key(key))

    async def list(self, prefix: str = "") -> list[str]:
        keys = await self.inner.list(self._key(prefix))
        return [k[len(self.prefix) :] for k in keys]

    async def delete(self, *keys: str) -> int:
        return await self.inner.delete(*(self._key(k) for k in keys))


def make_store(settings: ObjectStoreSettings, *, prefix: str) -> BlobStore:
    """The object store, scoped to ``prefix``. Raises if it is not configured.

    There is deliberately **no fallback to disk**. An earlier version returned
    a ``LocalBlobStore`` when ``WP6_S3_BUCKET`` was empty, and that silence was
    the bug: the nightly export job ran without the setting and wrote to a
    directory, while the dashboard read an empty bucket, so the CSVs simply
    never appeared and nothing anywhere said why. A missing bucket is our
    misconfiguration, it never self-heals, and per issue 033 the right answer
    to that is to crash loudly rather than to quietly do something else.

    (An unreachable *configured* store is the opposite case -- someone else's
    service, transient -- and callers degrade instead; see
    ``shared.export.get_export_metadata``.)

    ``LocalBlobStore`` is still a real backend, but it is now always chosen
    explicitly: by tests, and by the grey twin, which exports nothing.

    ``prefix`` scopes the caller to its own corner of the one shared bucket
    (``red/exports``, ``blue/models``).
    """
    if not settings.enabled:
        raise RuntimeError(
            "Object storage is not configured: set WP6_S3_BUCKET (plus "
            "WP6_S3_ENDPOINT_URL and credentials). Locally, uncomment the "
            "WP6_S3_* block in .env and start MinIO with "
            "`docker compose -f docker-compose.tsdb.yml up -d`.",
        )
    return PrefixedBlobStore(S3BlobStore(settings), prefix)


def _is_not_found(error: ClientError) -> bool:
    code = error.response.get("Error", {}).get("Code", "")
    status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"NoSuchKey", "404", "NotFound"} or status == 404


def _head_ok(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if _is_not_found(e):
            return False
        raise
    return True


def _build_client(settings: ObjectStoreSettings):
    """Construct the botocore client, resolving the CA bundle.

    See ObjectStoreSettings.ca_bundle for why an explicit bundle is required
    rather than botocore's vendored one.
    """
    import boto3
    from botocore.config import Config

    ca_bundle = settings.ca_bundle
    if not ca_bundle:
        import certifi

        ca_bundle = certifi.where()

    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url or None,
        region_name=settings.region,
        aws_access_key_id=settings.access_key_id or None,
        aws_secret_access_key=settings.secret_access_key or None,
        verify=ca_bundle,
        config=Config(s3={"addressing_style": settings.addressing_style}),
    )
