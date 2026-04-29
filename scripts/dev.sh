#!/usr/bin/env bash
# Run blue, red, and grey dashboards locally on different ports.
# Grey: http://localhost:8000
# Blue: http://localhost:8001
# Red:  http://localhost:8002

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

echo "Starting dashboards... grey at 8000, blue at 8001, red at 8002"
uv run uvicorn wp6_data.grey.dashboard:app --host 0.0.0.0 --port 8000 --reload --reload-dir src/wp6_data &
PIDS+=($!)
uv run uvicorn wp6_data.blue.dashboard:app --host 0.0.0.0 --port 8001 --reload --reload-dir src/wp6_data &
PIDS+=($!)
uv run uvicorn wp6_data.red.dashboard:app  --host 0.0.0.0 --port 8002 --reload --reload-dir src/wp6_data &
PIDS+=($!)

wait
