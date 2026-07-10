# WP6 Digital Twins Developer guide

[Documentation site on Github Pages](https://spohf.github.io/SPoHF-WP6-Twins/)


## Dashboards

| Dashboard | Backend | Auth | URL |
|-----------|---------|------|-----|
| **Blue** | TimescaleDB (synced from SPoHF API) | Public | `wp6-blue.spohf.fontysvenlo.dev` |
| **Red** | MySQL (`spohf2`) | Basic Auth | `wp6-red.spohf.fontysvenlo.dev` |

Both dashboards serve interactive Plotly charts via FastAPI.

### Blue Data Source

Blue's automated sensors are physical Yookr devices, read through the **SPoHF
datalake** relay (`backoffice.spohf.com`, endpoint `yookr-data`) — the single
canonical source. Blue does not talk to `api.yookr.org`; the `yookr-direct`
ingest and its `readings.project` column were retired in July 2026 (see
[`docs/blue/yookr-direct-retirement.md`](docs/blue/yookr-direct-retirement.md)).

Manual uploads (long_data, insects, fertigation) live in the same `readings`
table and are distinguished by the `source` column, matching the Red twin.

> The relay caps a single query at 10,000 records. `SpoHFClient.fetch_window`
> bisects any window that overflows — offset paging silently stops at the cap.

## Quick Start

```bash
# 1. Start TimescaleDB
docker compose -f docker-compose.tsdb.yml up -d

# 2. Install dependencies
uv sync
uv sync --extra dev                    # with dev tools

# 3. Run sync (populates the database)
uv run python -m wp6_data                             # SPoHF datalake sync (incremental)
WP6_SYNC_MODE=full uv run python -m wp6_data          # historical sync (full, may take hours)
WP6_SYNC_MODE=full WP6_SYNC_START=2025-01-01 WP6_SYNC_END=2025-03-01 \
  uv run python -m wp6_data                           # backfill one window

# 4. Start dashboards
uv run python -m wp6_data.blue.dashboard  # Blue dashboard (port 8000)
uv run python -m wp6_data.red.dashboard   # Red dashboard (port 8000)
# alternatively, run both dashboards together with hot reloading (port 8000 for blue, 8001 for red):
./scripts/dev.sh
```

```bash
# Dev commands
uv run ruff check src/ --fix   # Lint
uv run pytest                  # Run tests
uv run pytest tests/e2e/ -v    # E2E tests (requires running blue dashboard + TimescaleDB)
```

## Configuration

All via `WP6_*` environment variables — see `.env.example` for the full list.

### Key Blue Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WP6_TSDB_URL` | `postgresql://wp6:wp6dev@localhost:5433/wp6_blue` | TimescaleDB connection string |
| `WP6_SYNC_MODE` | `incremental` | `full` (bounded by `WP6_SYNC_START`/`END`) or `incremental` (recent data) |
| `WP6_SYNC_START` | `2024-01-01` | First day of a full sync |
| `WP6_SYNC_END` | — | Last day of a full sync (default: tomorrow). Ignored when incremental |
| `WP6_ENDPOINTS` | `yookr-data` | SPoHF API endpoints to sync |

## TimescaleDB Schema

```
readings          — time-series sensor data (hypertable, partitioned by time)
sync_metadata     — per-endpoint sync state (last run, errors, record counts)
daily_coverage    — device/sensor/day presence index for coverage views
```

Non-numeric sensor values (e.g. `"high"`, `"low"`) are stored as `NULL` in the `value` column and preserved in `raw_value`.

## Docker

### Local Development Database

```bash
docker compose -f docker-compose.tsdb.yml up -d    # Start TimescaleDB on port 5433
docker compose -f docker-compose.tsdb.yml down -v   # Fresh start (destroys data)
```

### Application Images

Multi-target build for separate images:

```bash
docker build --target blue -t wp6-data-blue .
docker build --target red -t wp6-data-red .
docker run -p 8000:8000 --env-file .env wp6-data-blue
```

## Deployment

Deployed via Helm + ArgoCD with auto-deploy on push to `main`. Images are pushed to Harbor with versioning `1.0.<commit-count>-<short-sha>`.

## License

MIT
