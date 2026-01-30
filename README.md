# WP6 Digital Twins Developer guide

[Documentation site on Github Pages](https://lenntt.github.io/SPoHF-WP6-Twins/)


## Dashboards

| Dashboard | Backend | Auth | URL |
|-----------|---------|------|-----|
| **Blue** | Neo4j (synced from SPoHF API) | Public | `wp6-blue.spohf.fontysvenlo.dev` |
| **Red** | MySQL (`spohf2`) | Basic Auth | `wp6-red.spohf.fontysvenlo.dev` |

Both dashboards serve interactive Plotly charts via FastAPI.

## Quick Start

```bash
cp .env.example .env       # Configure credentials
uv sync                    # Install dependencies
docker compose up -d       # Start Neo4j (for blue)
uv run python -m wp6_data  # Run sync job
uv run python -m wp6_data.blue.dashboard  # Blue dashboard on :8000
uv run python -m wp6_data.red.dashboard   # Red dashboard on :8000
```

## Configuration

All via `WP6_*` environment variables — see `.env.example` for the full list.

### Sync Modes (`WP6_SYNC_MODE`)

| Mode | Behavior |
|------|----------|
| `auto` (default) | Windowed on first run, incremental after |
| `windowed` | Full historical fetch using time windows from 2024-01-01 |
| `incremental` | Only new data since last sync |

`WP6_SYNC_WINDOW_DAYS` controls the window step size (default: 1 day, use 30 for monthly).

Data is upserted via MERGE queries — re-running windowed sync updates existing records without duplicates.

## Neo4j Graph Model

```
(Project)-[:HAS_DEVICE]->(Device)-[:HAS_SENSOR]->(Sensor)-[:RECORDED]->(Reading)
```

Example queries:
```cypher
-- Latest readings per device
MATCH (d:Device)-[:HAS_SENSOR]->(s:Sensor)-[:RECORDED]->(r:Reading)
RETURN d.device_name, s.tag, r.value, r.datetime_measure
ORDER BY r.datetime_measure DESC LIMIT 20

-- Soil moisture trend (24h)
MATCH (d:Device)-[:HAS_SENSOR]->(s:Sensor {tag: "soilMoisture"})-[:RECORDED]->(r:Reading)
WHERE r.datetime_measure > datetime() - duration({hours: 24})
RETURN d.device_name, r.datetime_measure, r.value
ORDER BY r.datetime_measure
```

## Docker

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
