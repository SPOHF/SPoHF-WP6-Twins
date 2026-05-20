# WP6 Digital Twins Developer guide

[Documentation site on Github Pages](https://spohf.github.io/SPoHF-WP6-Twins/)


## Dashboards

| Dashboard | Backend | Auth | URL |
|-----------|---------|------|-----|
| **Blue** | TimescaleDB (synced from SPoHF API) | Public | `wp6-blue.spohf.fontysvenlo.dev` |
| **Red** | MySQL (`spohf2`) | Basic Auth | `wp6-red.spohf.fontysvenlo.dev` |

Both dashboards serve interactive Plotly charts via FastAPI.

### Blue Data Sources

The Blue dashboard supports two data sources, switchable via a cookie (`wp6_blue_source`):

| Source | Description | Sync |
|--------|-------------|------|
| **SPoHF Datalake** (`spohf-datalake`) | Bulk data from `backoffice.spohf.com` | `WP6_ENDPOINTS=yookr-data` sync job |
| **Yookr API** (`yookr`) | Per-sensor data from `api.yookr.org` | `--yookr` sync job |

Both sources store data in the same TimescaleDB instance, separated by the `project` column in the `readings` table.

## Quick Start

```bash
# 1. Start TimescaleDB
docker compose -f docker-compose.tsdb.yml up -d

# 2. Install dependencies
uv sync
uv sync --extra dev                    # with dev tools

# 3. Run sync (populates the database)
uv run python -m wp6_data                             # SPoHF datalake sync (incremental)
WP6_SYNC_MODE=full uv run python -m wp6_data          # SPoHF historical sync (full, may take hours)
uv run python -m wp6_data --yookr                     # Yookr direct sync

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
| `WP6_SYNC_MODE` | `incremental` | `full` (all history from 2024-01-01) or `incremental` (recent data) |
| `WP6_ENDPOINTS` | `yookr-data` | SPoHF API endpoints to sync |
| `WP6_YOOKR_EMAIL` | — | Yookr API credentials (for `--yookr` sync) |
| `WP6_YOOKR_PASSWORD` | — | Yookr API credentials (for `--yookr` sync) |

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
