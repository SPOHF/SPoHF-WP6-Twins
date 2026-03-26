#!/usr/bin/env bash
# Run both blue and red dashboards locally on different ports.
# Blue: http://localhost:8000
# Red:  http://localhost:8001

set -e

PORTS=(8000 8001)

cleanup() {
    echo ""
    echo "Shutting down..."
    kill 0 2>/dev/null
    wait 2>/dev/null
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

echo "Starting Blue on :8000 and Red on :8001 ..."
uv run uvicorn wp6_data.blue.dashboard:app --host 0.0.0.0 --port 8000 --reload &
uv run uvicorn wp6_data.red.dashboard:app  --host 0.0.0.0 --port 8001 --reload &
wait
