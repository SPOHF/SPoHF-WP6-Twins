# WP6 Data Sync

Syncs sensor data from the SPoHF API to Neo4j graph database, with a web dashboard for visualization.

Part of the [SPoHF (Smart Production of Healthy Food) project](https://www.spohf.com/) - WP6 digital twin workpackage.

![alt text](./static/interreg.png)

## Architecture

```
SPoHF API ──> CronJob (sync) ──> Neo4j ──> Dashboard (FastAPI)
                                              │
                                        Plotly charts
```

**Components:**
- **Sync Job**: Fetches sensor readings from SPoHF API using daily time windows, stores in Neo4j
- **Dashboard**: FastAPI web UI with Plotly charts for data exploration
- **Neo4j**: Graph database storing devices, sensors, and readings

## Quick Start (Local Development)

### Prerequisites
- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (for Neo4j)

### Setup

1. **Start Neo4j:**
   ```bash
   docker compose up -d
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your SPoHF API token
   ```

3. **Install dependencies:**
   ```bash
   uv sync
   ```

4. **Run initial sync:**
   ```bash
   uv run python -m wp6_data sync
   ```

5. **Start dashboard:**
   ```bash
   uv run python -m wp6_data.dashboard
   # Open http://localhost:8000
   ```

## Configuration

All configuration via `WP6_*` environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `WP6_API_BASE_URL` | SPoHF API base URL | `https://backoffice.spohf.com` |
| `WP6_API_TOKEN` | Bearer token for API auth | *required* |
| `WP6_NEO4J_URI` | Neo4j connection URI | *required* |
| `WP6_NEO4J_USER` | Neo4j username | `neo4j` |
| `WP6_NEO4J_PASSWORD` | Neo4j password | *required* |
| `WP6_NEO4J_DATABASE` | Neo4j database name | `neo4j` |
| `WP6_SYNC_LOOKBACK_HOURS` | Hours to look back on first sync | `24` |
| `WP6_SYNC_PAGE_SIZE` | Records per API page | `100` |
| `WP6_SYNC_MAX_PAGES` | Max pages/windows per sync run | `100` |
| `WP6_SYNC_MODE` | Sync mode: `auto`, `windowed`, or `incremental` | `auto` |
| `WP6_ENDPOINTS` | Comma-separated API endpoints | `yookr-data` |
| `WP6_LOG_LEVEL` | Log level (DEBUG, INFO, WARN, ERROR) | `INFO` |
| `WP6_LOG_FORMAT` | Log format (`json` or `console`) | `json` |

### Sync Modes

The sync job supports three modes via `WP6_SYNC_MODE`:

| Mode | Behavior |
|------|----------|
| `auto` | (default) Uses windowed mode on first run, incremental after |
| `windowed` | Full historical fetch using daily time windows from 2024-01-01 |
| `incremental` | Only fetch new data since last sync timestamp |

**Windowed mode** iterates through daily time windows to fetch all historical data. Use this to backfill data or re-sync after the API provider fixes data.

**Incremental mode** fetches only new records since the last successful sync, using the stored sync state.

Data is upserted using MERGE queries - running windowed sync multiple times will update existing records (if values changed) without creating duplicates.

### Available Endpoints

| Endpoint | Description |
|----------|-------------|
| `yookr-data` | Main sensor data (soil moisture, leaf wetness, etc.) |
| `yookr-data-weather` | Weather data from Yookr stations |
| `weather-station` | Weather station devices |
| `dragino-nodes` | Dragino IoT sensor nodes |

## Neo4j Graph Model

```
(Project)-[:HAS_DEVICE]->(Device)-[:HAS_SENSOR]->(Sensor)-[:RECORDED]->(Reading)
```

**Nodes:**
- `Project`: Grouping for devices (e.g., "SPoHF", "Weerdata")
- `Device`: Physical device with `sensor_id` (UUID) and `device_name`
- `Sensor`: Measurement type on a device (e.g., soilMoisture, leafWetness)
- `Reading`: Individual measurement with `value`, `datetime_measure`, `timestamp`

**Example queries:**

```cypher
-- Latest readings per device
MATCH (d:Device)-[:HAS_SENSOR]->(s:Sensor)-[:RECORDED]->(r:Reading)
RETURN d.device_name, s.tag, r.value, r.datetime_measure
ORDER BY r.datetime_measure DESC
LIMIT 20

-- Soil moisture trend for past 24 hours
MATCH (d:Device)-[:HAS_SENSOR]->(s:Sensor {tag: "soilMoisture"})-[:RECORDED]->(r:Reading)
WHERE r.datetime_measure > datetime() - duration({hours: 24})
RETURN d.device_name, r.datetime_measure, r.value
ORDER BY r.datetime_measure
```

## Kubernetes Deployment

The included Helm chart deploys:
- CronJob for periodic sync (default: every 15 minutes)
- Dashboard deployment with ingress
- Optional Neo4j (or use external)

### Helm Values

```yaml
image:
  repository: ghcr.io/yourorg/wp6-data  # Required
  tag: latest

dashboard:
  enabled: true
  replicas: 1
  ingress:
    enabled: true
    host: wp6.example.com  # Required

sync:
  enabled: true
  schedule: "*/15 * * * *"
  lookbackHours: 24
  mode: "auto"  # or "windowed" for full re-sync

neo4j:
  enabled: true  # Set false to use external Neo4j
  auth:
    password: ""  # Set via secret

secrets:
  create: false  # Use existing secret
  existingSecret: wp6-data-secrets
```

### Deploy with Helm

```bash
helm install wp6-data ./helm \
  --namespace spohf-system \
  --set image.repository=ghcr.io/yourorg/wp6-data \
  --set dashboard.ingress.host=wp6.example.com \
  --set secrets.existingSecret=wp6-data-secrets
```

### Running a Full Re-sync

To trigger a full historical sync (windowed mode) in Kubernetes:

```bash
# Create a one-off job with windowed mode
kubectl create job wp6-sync-full --from=cronjob/wp6-data-sync -n spohf-system
kubectl set env job/wp6-sync-full -n spohf-system WP6_SYNC_MODE=windowed

# Or update the helm release temporarily
helm upgrade wp6-data ./helm --set sync.mode=windowed
# Then revert after sync completes
helm upgrade wp6-data ./helm --set sync.mode=auto
```

### Required Secret

Create a Kubernetes secret with credentials:

```bash
kubectl create secret generic wp6-data-secrets \
  --namespace spohf-system \
  --from-literal=api-token='YOUR_SPOHF_TOKEN' \
  --from-literal=neo4j-password='YOUR_NEO4J_PASSWORD'
```

## Docker

Build and run the container:

```bash
# Build
docker build -t wp6-data .

# Run dashboard
docker run -p 8000:8000 --env-file .env wp6-data

# Run sync
docker run --env-file .env wp6-data python -m wp6_data sync
```

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run linter
uv run ruff check src/

# Run tests
uv run pytest
```

## Project Structure

```
wp6-data/
├── src/wp6_data/
│   ├── __init__.py
│   ├── __main__.py          # CLI entry point
│   ├── config.py            # Pydantic settings
│   ├── api/
│   │   ├── client.py        # SPoHF API client with pagination
│   │   └── models.py        # Pydantic models for API responses
│   ├── graph/
│   │   ├── driver.py        # Neo4j async driver
│   │   └── queries.py       # Cypher queries for upsert
│   ├── sync/
│   │   ├── orchestrator.py  # Main sync logic
│   │   └── state.py         # Sync state tracking
│   └── dashboard/
│       └── __init__.py      # FastAPI dashboard
├── helm/                    # Kubernetes Helm chart
├── docker-compose.yml       # Local Neo4j
├── Dockerfile              # Multi-stage build with uv
└── pyproject.toml          # Dependencies and tooling
```

## License

MIT
