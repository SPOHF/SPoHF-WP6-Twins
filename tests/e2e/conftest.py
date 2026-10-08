"""Shared fixtures for e2e tests requiring a real TimescaleDB instance."""

import os

# Blue is an authenticated twin (require_auth=True), so building its app
# enters a lifespan that runs OIDC startup. e2e runs in a clean env with no
# OIDC secrets and no reachable issuer; dev-auth mode makes startup_oidc
# short-circuit before any secret check or network call. setdefault so a
# real OIDC env still wins. Must be set before the blue app is imported.
os.environ.setdefault("WP6_OIDC_DEV_AUTH", "true")

# Object storage is mandatory, and importing a twin's deps builds its export
# store. Point at the local container so an imported twin is usable; individual
# fixtures still build their own settings explicitly rather than reading these.
os.environ.setdefault("WP6_S3_BUCKET", "wp6-e2e")
os.environ.setdefault("WP6_S3_ENDPOINT_URL", "http://localhost:9100")
os.environ.setdefault("WP6_S3_ACCESS_KEY_ID", "wp6")
os.environ.setdefault("WP6_S3_SECRET_ACCESS_KEY", "wp6devsecret")

import asyncio  # noqa: E402
import sys  # noqa: E402
import warnings  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from psycopg_pool import AsyncConnectionPool  # noqa: E402

from wp6_data.blue.tsdb import ensure_schema_blue  # noqa: E402
from wp6_data.config import ObjectStoreSettings  # noqa: E402
from wp6_data.shared.blob import S3BlobStore  # noqa: E402

TSDB_DSN = "postgresql://wp6:wp6dev@localhost:5433/wp6_blue"
RED_TSDB_DSN = "postgresql://wp6_red:wp6dev@localhost:5433/wp6_red"
E2E_PREFIX = "e2e-"
_TSDB_HINT = (
    "Start it with: docker compose -f docker-compose.tsdb.yml up -d "
    "(use `down -v` once if you have an old volume without the wp6_red database)"
)


async def remove_cagg_refresh_policy(conn) -> None:
    """Delete the cagg refresh policy so no background job races the tests.

    `ensure_aggregates` installs a continuous-aggregate refresh policy: a
    TimescaleDB background job the scheduler picks up the moment it is created
    (`next_start` is NULL until its first run). On a *fresh* database — which
    CI always has, and a developer rarely does — that puts a refresh in flight
    exactly while the first tests run. It then either holds the cagg lock that
    a foreground `refresh_continuous_aggregate` needs (`LockNotAvailable:
    concurrent refresh`) or touches the catalog row a teardown DROP is removing
    (`InternalError: tuple concurrently updated`). Local runs usually win the
    race because the policy already exists from an earlier run, so its next
    start is up to 15 minutes away.

    e2e refreshes the cagg explicitly wherever it needs fresh data, so the
    policy earns nothing here. Removing it deletes the job *and blocks until
    any in-flight run finishes*, making callers genuinely unraced rather than
    merely usually-unraced — unlike a sleep or a retry, which would leave a
    flake to resurface on a slower runner inside some unrelated diff.

    Guarded inside PL/pgSQL, not with a plain `WHERE EXISTS`: the function
    takes a REGCLASS, and Postgres resolves 'sensors_daily_summary'::regclass
    at *plan* time — so a top-level SELECT fails to plan at all when the view
    is absent (the normal case on a pre-test drop against a fresh database),
    however the WHERE clause is written. Inside a DO block the inner statement
    is only planned once the IF is reached.
    """
    await conn.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM timescaledb_information.continuous_aggregates
                WHERE view_name = 'sensors_daily_summary'
            ) THEN
                PERFORM remove_continuous_aggregate_policy(
                    'sensors_daily_summary', if_exists => true);
            END IF;
        END $$;
        """
    )


@pytest.fixture(scope="session")
def event_loop_policy():
    """SelectorEventLoop on Windows, for the same reason as ``shared.compat.run_async``.

    psycopg's async mode needs ``add_reader()``, which the default
    ``ProactorEventLoop`` lacks, so on Windows every pool connect fails and the
    whole suite errors out with ``PoolTimeout``. CI runs on Linux and never sees it.

    Event-loop policies are deprecated since Python 3.14, but pytest-asyncio
    1.3 offers no loop-factory hook yet; switch once it does.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        if sys.platform == "win32":
            return asyncio.WindowsSelectorEventLoopPolicy()
        return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _bootstrap_blue_schema():
    """Create blue tables once per session so cleanup_e2e_data has something to delete from."""
    pool = AsyncConnectionPool(TSDB_DSN, min_size=1, max_size=1, open=False)
    await pool.open()
    try:
        await ensure_schema_blue(pool)
        yield
    finally:
        await pool.close()


@pytest_asyncio.fixture()
async def tsdb_conn():
    """Async psycopg connection for e2e tests. Fails hard if TimescaleDB is unreachable."""
    try:
        conn = await psycopg.AsyncConnection.connect(TSDB_DSN)
    except Exception as exc:
        raise RuntimeError(
            f"TimescaleDB is not reachable at {TSDB_DSN}. {_TSDB_HINT}"
        ) from exc
    yield conn
    await conn.close()


@pytest_asyncio.fixture()
async def red_tsdb_conn():
    """Async psycopg connection to the red wp6_red database."""
    try:
        conn = await psycopg.AsyncConnection.connect(RED_TSDB_DSN)
    except Exception as exc:
        raise RuntimeError(
            f"Red TimescaleDB is not reachable at {RED_TSDB_DSN}. {_TSDB_HINT}"
        ) from exc
    yield conn
    await conn.close()


async def _delete_e2e_data(conn) -> None:
    """Delete all rows whose identifying properties start with the e2e prefix."""
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM readings WHERE device_name LIKE %(prefix)s",
            {"prefix": f"{E2E_PREFIX}%"},
        )
        await cur.execute(
            "DELETE FROM sync_metadata WHERE endpoint LIKE %(prefix)s",
            {"prefix": f"{E2E_PREFIX}%"},
        )
    await conn.commit()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_e2e_data(tsdb_conn):
    """Delete all e2e-prefixed data before and after each test."""
    await _delete_e2e_data(tsdb_conn)
    yield
    await _delete_e2e_data(tsdb_conn)


@pytest_asyncio.fixture(autouse=True)
async def disarm_cagg_refresh_policy(tsdb_conn):
    """Keep blue's cagg refresh policy disarmed for the whole run.

    Removing it once at bootstrap is not enough: every test that enters the
    blue app's lifespan runs `init_db` -> `ensure_schema_blue` ->
    `ensure_aggregates`, which re-adds the policy — freshly armed, so the
    scheduler fires it immediately. Disarming around each test means a re-arm
    lives only until that test ends, instead of leaving a background refresh
    running under everything that follows.

    Red's policy is handled by that suite's own schema teardown, which
    bootstraps and drops the red schema per test.
    """
    await remove_cagg_refresh_policy(tsdb_conn)
    await tsdb_conn.commit()
    yield
    await remove_cagg_refresh_policy(tsdb_conn)
    await tsdb_conn.commit()


# --- Object store ------------------------------------------------------------
# Exercises the real S3 code path -- botocore, path-style addressing, S3 error
# shapes, pagination -- which the LocalBlobStore unit tests cannot reach.
#
# The container is `adobe/s3mock`, a mock rather than a real store: MinIO's
# images stopped being anonymously pullable, so the "same implementation as
# production" property is gone (see docker-compose.tsdb.yml). That makes this a
# test of OUR CLIENT. The real store is covered by the probe harness in the
# wp6-data issue 061, run against the actual bucket.

S3_ENDPOINT = "http://localhost:9100"
S3_ACCESS_KEY = "wp6"       # s3mock accepts any credentials
S3_SECRET_KEY = "wp6devsecret"
S3_BUCKET = "wp6-e2e"
_S3_HINT = (
    "Start it with: docker compose -f docker-compose.tsdb.yml up -d s3mock"
)


def object_store_settings(bucket: str = S3_BUCKET) -> ObjectStoreSettings:
    """Settings pointed at the local MinIO.

    Built explicitly rather than read from the environment so an e2e run never
    picks up a developer's real bucket credentials from .env and writes test
    objects into production storage.
    """
    return ObjectStoreSettings(
        bucket=bucket,
        endpoint_url=S3_ENDPOINT,
        access_key_id=S3_ACCESS_KEY,
        secret_access_key=S3_SECRET_KEY,
    )


@pytest_asyncio.fixture()
async def s3_store():
    """An :class:`S3BlobStore` on a freshly-emptied local bucket.

    Fails hard rather than skipping, matching the TimescaleDB fixtures: CI
    gates the image build on e2e, so a silently-skipped object-store test
    would let a broken S3 path ship.
    """
    settings = object_store_settings()
    try:
        store = S3BlobStore(settings)
        await asyncio.to_thread(_ensure_bucket, store)
    except Exception as exc:
        raise RuntimeError(
            f"Object store is not reachable at {S3_ENDPOINT}. {_S3_HINT}"
        ) from exc

    await _empty(store)
    yield store
    await _empty(store)


def _ensure_bucket(store) -> None:
    client = store._client  # noqa: SLF001 - test setup reaches past the interface
    try:
        client.head_bucket(Bucket=store.bucket)
    except ClientError:
        client.create_bucket(Bucket=store.bucket)


async def _empty(store) -> None:
    keys = await store.list("")
    if keys:
        await store.delete(*keys)
