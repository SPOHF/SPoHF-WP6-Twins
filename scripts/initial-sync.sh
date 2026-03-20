#!/usr/bin/env bash
# Initial full sync for TimescaleDB migration
# Triggers both SPoHF datalake and Yookr direct full syncs as one-off K8s Jobs
set -euo pipefail

NAMESPACE="${NAMESPACE:-spohf-system}"

echo "=== Starting initial full syncs in namespace: $NAMESPACE ==="

echo ""
echo "--- SPoHF Datalake Full Sync ---"
kubectl create job wp6-data-sync-full \
  --from=cronjob/wp6-data-sync \
  -n "$NAMESPACE" \
  --dry-run=client -o yaml | \
  sed 's/value: "incremental"/value: "full"/' | \
  kubectl apply -f -

echo ""
echo "--- Yookr Direct Full Sync ---"
kubectl create job wp6-data-yookr-sync-full \
  --from=cronjob/wp6-data-yookr-sync \
  -n "$NAMESPACE" \
  --dry-run=client -o yaml | \
  sed 's/value: "incremental"/value: "full"/' | \
  kubectl apply -f -

echo ""
echo "=== Jobs created. Monitor with: ==="
echo "  kubectl logs -f job/wp6-data-sync-full -n $NAMESPACE"
echo "  kubectl logs -f job/wp6-data-yookr-sync-full -n $NAMESPACE"
