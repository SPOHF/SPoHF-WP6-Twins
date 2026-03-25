#!/usr/bin/env bash
# Run both blue and red dashboards locally on different ports.
# Blue: http://localhost:8000
# Red:  http://localhost:8001

set -e
trap 'kill 0' EXIT

echo "Starting Blue on :8000 and Red on :8001 ..."
uv run uvicorn wp6_data.blue.dashboard:app --host 0.0.0.0 --port 8000 --reload &
uv run uvicorn wp6_data.red.dashboard:app  --host 0.0.0.0 --port 8001 --reload &
wait
