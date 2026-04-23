#!/usr/bin/env bash
# Full historical sync from SPoHF datalake API → TimescaleDB
# Suspends both CronJobs to avoid deadlocks, unsuspends on exit
set -euo pipefail

NAMESPACE="${NAMESPACE:-spohf-system}"
JOB_NAME="wp6-data-sync-full"
CRONJOBS=("wp6-data-sync" "wp6-data-yookr-sync")

SED_ARGS=(
  -e 's/value: "\{0,1\}incremental"\{0,1\}/value: full/'
  -e 's/activeDeadlineSeconds: 900/activeDeadlineSeconds: 43200/'
  -e 's/backoffLimit: 2/backoffLimit: 3/'
)

unsuspend() {
  echo ""
  echo "--- Unsuspending CronJobs ---"
  for cj in "${CRONJOBS[@]}"; do
    kubectl patch cronjob "$cj" -n "$NAMESPACE" -p '{"spec":{"suspend":false}}' 2>/dev/null || true
  done
}
trap unsuspend EXIT

echo "=== SPoHF Datalake Full Sync ==="

echo "--- Suspending CronJobs ---"
for cj in "${CRONJOBS[@]}"; do
  kubectl patch cronjob "$cj" -n "$NAMESPACE" -p '{"spec":{"suspend":true}}' 2>/dev/null || true
done

kubectl delete job "$JOB_NAME" -n "$NAMESPACE" --ignore-not-found

echo "--- Creating full sync job ---"
kubectl create job "$JOB_NAME" \
  --from=cronjob/wp6-data-sync \
  -n "$NAMESPACE" \
  --dry-run=client -o yaml | \
  sed "${SED_ARGS[@]}" | \
  kubectl apply -f -

echo ""
echo "Job created. Monitor with:"
echo "  kubectl logs -f job/$JOB_NAME -n $NAMESPACE"
echo ""
echo "CronJobs are suspended. They will unsuspend when this script exits (Ctrl+C is safe)."
echo "Waiting for job to complete..."

kubectl wait --for=condition=complete "job/$JOB_NAME" \
  -n "$NAMESPACE" --timeout=43200s

echo ""
echo "=== Done ==="
kubectl logs "job/$JOB_NAME" -n "$NAMESPACE" --tail=3
