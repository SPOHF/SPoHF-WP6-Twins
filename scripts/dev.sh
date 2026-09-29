#!/usr/bin/env bash
# Run blue, red, and grey dashboards locally on different ports.
# Grey: http://localhost:8000
# Blue: http://localhost:8001
# Red:  http://localhost:8002
#
# Backing services are NOT started here -- this script assumes TimescaleDB is
# already up (see README), and treats the MinIO object store the same way:
# detect it, wire the dashboards to it, and carry on without it if absent.
# Starting containers would change what this script is responsible for, and
# would fight a setup that points .env at a remote database instead.
#
#   docker compose -f docker-compose.tsdb.yml up -d
#
# Set WP6_DEV_NO_S3=1 to leave object storage off even when MinIO is running.

set -e

PORTS=(8000 8001 8002)
PIDS=()

cleanup() {
    trap - EXIT INT TERM HUP
    echo ""
    echo "Shutting down..."
    for pid in "${PIDS[@]}"; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP

# Kill any leftover processes on our ports
for port in "${PORTS[@]}"; do
    pid=$(lsof -ti :"$port" 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo "Port $port in use (pid $pid), killing..."
        kill "$pid" 2>/dev/null || true
        sleep 0.5
    fi
done

# --- Object store ------------------------------------------------------------
# Reports what .env resolves to; it does NOT set anything itself.
#
# An earlier version exported WP6_S3_* here, which was a trap: those vars reach
# only the dashboards this script launches, so an export job run in another
# terminal wrote to disk while the dashboards read an empty bucket, and no
# download links appeared. Config that several processes must agree on belongs
# in .env, which all of them read. See .env.example.
if ! uv run python - <<'PYEOF'
import sys

from wp6_data.config import ObjectStoreSettings

s = ObjectStoreSettings()
if not s.enabled:
    print("Object store: NOT CONFIGURED - the dashboards will refuse to start.")
    print("  add the WP6_S3_* block to .env (see .env.example), then:")
    print("  docker compose -f docker-compose.tsdb.yml up -d")
    sys.exit(1)

print(f"Object store: {s.endpoint_url} bucket={s.bucket}")

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

client = boto3.client(
    "s3",
    endpoint_url=s.endpoint_url or None,
    aws_access_key_id=s.access_key_id or None,
    aws_secret_access_key=s.secret_access_key or None,
    region_name=s.region,
    config=Config(s3={"addressing_style": s.addressing_style}),
)
try:
    try:
        client.head_bucket(Bucket=s.bucket)
    except ClientError:
        client.create_bucket(Bucket=s.bucket)
        print(f"  created bucket {s.bucket}")
    print("  reachable (console http://localhost:9101)")
except Exception as exc:
    print(f"  NOT reachable: {type(exc).__name__}")
    print("  start it with: docker compose -f docker-compose.tsdb.yml up -d minio")
PYEOF
then
    echo ""
    echo "Refusing to start: exports require object storage. See .env.example."
    exit 1
fi

echo "Starting dashboards... grey at 8000, blue at 8001, red at 8002"
uv run uvicorn wp6_data.grey.dashboard:app --host 0.0.0.0 --port 8000 --reload --reload-dir src/wp6_data &
PIDS+=($!)
uv run uvicorn wp6_data.blue.dashboard:app --host 0.0.0.0 --port 8001 --reload --reload-dir src/wp6_data &
PIDS+=($!)
uv run uvicorn wp6_data.red.dashboard:app  --host 0.0.0.0 --port 8002 --reload --reload-dir src/wp6_data &
PIDS+=($!)

wait
