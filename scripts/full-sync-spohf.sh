#!/usr/bin/env bash
# Full sync from SPoHF datalake API → TimescaleDB
# Suspends the sync CronJob to avoid deadlocks, unsuspends on exit
#
# Optional env:
#   SYNC_START=YYYY-MM-DD   scope the sync to [SYNC_START, tomorrow) instead of
#                           the whole history (e.g. catching up late-relayed data)
#   KUBE_CONTEXT=<context>  kube context to use (default: current context)
set -euo pipefail

NAMESPACE="${NAMESPACE:-spohf-system}"
SYNC_START="${SYNC_START:-}"
JOB_NAME="wp6-data-sync-full"
CRONJOBS=("wp6-data-sync")

KUBECTL=(kubectl)
if [[ -n "${KUBE_CONTEXT:-}" ]]; then
  KUBECTL+=(--context "$KUBE_CONTEXT")
fi
KUBECTL+=(-n "$NAMESPACE")

if [[ -n "$SYNC_START" && ! "$SYNC_START" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "SYNC_START must be YYYY-MM-DD, got: $SYNC_START" >&2
  exit 1
fi

SED_ARGS=(
  -e 's/value: "\{0,1\}incremental"\{0,1\}/value: full/'
  -e 's/activeDeadlineSeconds: 900/activeDeadlineSeconds: 43200/'
  -e 's/backoffLimit: 2/backoffLimit: 3/'
)

# Insert WP6_SYNC_START right after the WP6_SYNC_MODE entry, at its indentation.
add_sync_start() {
  if [[ -z "$SYNC_START" ]]; then
    cat
    return
  fi
  awk -v start="$SYNC_START" '
    { print }
    /- name: WP6_SYNC_MODE$/ { indent = substr($0, 1, index($0, "-") - 1); pending = 1; next }
    pending && /value:/ {
      print indent "- name: WP6_SYNC_START"
      print indent "  value: \"" start "\""
      pending = 0; inserted = 1
    }
    END { if (!inserted) { print "WP6_SYNC_MODE env entry not found" > "/dev/stderr"; exit 1 } }
  '
}

unsuspend() {
  echo ""
  echo "--- Unsuspending CronJobs ---"
  for cj in "${CRONJOBS[@]}"; do
    "${KUBECTL[@]}" patch cronjob "$cj" -p '{"spec":{"suspend":false}}' 2>/dev/null || true
  done
}
trap unsuspend EXIT

echo "=== SPoHF Datalake Full Sync (from ${SYNC_START:-sync_start default}) ==="

echo "--- Suspending CronJobs ---"
for cj in "${CRONJOBS[@]}"; do
  "${KUBECTL[@]}" patch cronjob "$cj" -p '{"spec":{"suspend":true}}' 2>/dev/null || true
done

"${KUBECTL[@]}" delete job "$JOB_NAME" --ignore-not-found

echo "--- Creating full sync job ---"
"${KUBECTL[@]}" create job "$JOB_NAME" \
  --from=cronjob/wp6-data-sync \
  --dry-run=client -o yaml | \
  sed "${SED_ARGS[@]}" | \
  add_sync_start | \
  "${KUBECTL[@]}" apply -f -

echo ""
echo "Job created. Monitor with:"
echo "  ${KUBECTL[*]} logs -f job/$JOB_NAME"
echo ""
echo "CronJobs are suspended. They will unsuspend when this script exits (Ctrl+C is safe)."
echo "Waiting for job to complete..."

"${KUBECTL[@]}" wait --for=condition=complete "job/$JOB_NAME" --timeout=43200s

echo ""
echo "=== Done ==="
"${KUBECTL[@]}" logs "job/$JOB_NAME" --tail=3
