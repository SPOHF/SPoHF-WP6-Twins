#!/usr/bin/env bash
# Initial full sync for TimescaleDB migration
# Runs SPoHF datalake sync first, then Yookr sync (sequential to avoid deadlocks)
# Suspends CronJobs during the sync to prevent concurrent writes
# Overrides: sync_mode=full, activeDeadlineSeconds=43200 (12h), backoffLimit=3
set -euo pipefail

NAMESPACE="${NAMESPACE:-spohf-system}"
CRONJOBS=("wp6-data-sync" "wp6-data-yookr-sync")

# Match 'value: incremental' with or without quotes
SED_ARGS=(
  -e 's/value: "\{0,1\}incremental"\{0,1\}/value: full/'
  -e 's/activeDeadlineSeconds: 900/activeDeadlineSeconds: 43200/'
  -e 's/backoffLimit: 2/backoffLimit: 3/'
)

unsuspend() {
  echo ""
  echo "--- Unsuspending CronJobs ---"
  for cj in "${CRONJOBS[@]}"; do
    kubectl patch cronjob "$cj" -n "$NAMESPACE" -p '{"spec":{"suspend":false}}'
  done
}
trap unsuspend EXIT

echo "=== Initial full sync ==="

echo ""
echo "--- Suspending CronJobs ---"
for cj in "${CRONJOBS[@]}"; do
  kubectl patch cronjob "$cj" -n "$NAMESPACE" -p '{"spec":{"suspend":true}}'
done

echo ""
echo "--- Step 1/2: SPoHF Datalake Full Sync ---"
kubectl create job wp6-data-sync-full \
  --from=cronjob/wp6-data-sync \
  -n "$NAMESPACE" \
  --dry-run=client -o yaml | \
  sed "${SED_ARGS[@]}" | \
  kubectl apply -f -

echo "Waiting for SPoHF sync to complete..."
kubectl wait --for=condition=complete job/wp6-data-sync-full \
  -n "$NAMESPACE" --timeout=43200s

echo ""
echo "--- Step 2/2: Yookr Direct Full Sync ---"
kubectl create job wp6-data-yookr-sync-full \
  --from=cronjob/wp6-data-yookr-sync \
  -n "$NAMESPACE" \
  --dry-run=client -o yaml | \
  sed "${SED_ARGS[@]}" | \
  kubectl apply -f -

echo "Waiting for Yookr sync to complete..."
kubectl wait --for=condition=complete job/wp6-data-yookr-sync-full \
  -n "$NAMESPACE" --timeout=43200s

echo ""
echo "=== Both syncs complete ==="
echo "Verify: kubectl logs job/wp6-data-sync-full -n $NAMESPACE --tail=5"
echo "Verify: kubectl logs job/wp6-data-yookr-sync-full -n $NAMESPACE --tail=5"
