# Deployment Runbook: TimescaleDB Migration

## Prerequisites
- `kubectl` configured for the target cluster
- Access to the `spohf-system` namespace
- Helm chart changes pushed to the repo (ArgoCD auto-syncs)

## Steps

### 1. Update Kubernetes Secret

Add the new keys and remove the old `neo4j-password` key from `wp6-data-secrets`:

```bash
# Edit the existing secret (or recreate it)
kubectl edit secret wp6-data-secrets -n spohf-system
```

Required keys in `wp6-data-secrets`:
- `api-token` — SPoHF API token (existing)
- `tsdb-url` — Full PostgreSQL connection URL, e.g. `postgresql://wp6:PASSWORD@wp6-data-timescaledb:5432/wp6`
- `tsdb-password` — TimescaleDB postgres password (used by the StatefulSet's `POSTGRES_PASSWORD`)
- `yookr-email` — Yookr API email
- `yookr-password` — Yookr API password

Remove:
- `neo4j-password` (no longer needed)

### 2. Push Helm Chart Changes

```bash
git push origin main
```

ArgoCD will auto-sync and deploy:
- TimescaleDB StatefulSet
- Updated blue dashboard (using `WP6_TSDB_URL`)
- Updated SPoHF sync CronJob (using `WP6_TSDB_URL`)
- New Yookr sync CronJob

### 3. Verify TimescaleDB is Running

```bash
kubectl get statefulset wp6-data-timescaledb -n spohf-system
kubectl get pods -l app.kubernetes.io/name=wp6-data-timescaledb -n spohf-system
```

### 4. Run Initial Full Syncs

Both data sources need a one-time full sync to populate TimescaleDB:

```bash
# Option A: Use the provided script
bash scripts/initial-sync.sh

# Option B: Manual one-off jobs
kubectl create job --from=cronjob/wp6-data-sync wp6-data-sync-full -n spohf-system \
  -- env WP6_SYNC_MODE=full
kubectl create job --from=cronjob/wp6-data-yookr-sync wp6-data-yookr-sync-full -n spohf-system \
  -- env WP6_SYNC_MODE=full
```

Monitor progress:
```bash
kubectl logs -f job/wp6-data-sync-full -n spohf-system
kubectl logs -f job/wp6-data-yookr-sync-full -n spohf-system
```

### 5. Verify Dashboard

Open https://wp6-blue.spohf.fontysvenlo.dev and verify data is loading.

### 6. Clean Up Neo4j PVC

Once everything is confirmed working:

```bash
kubectl delete pvc data-wp6-data-neo4j-0 -n spohf-system
```

### 7. Verify No Neo4j Resources Remain

```bash
kubectl get all,pvc -n spohf-system | grep neo4j
# Should return nothing
```
