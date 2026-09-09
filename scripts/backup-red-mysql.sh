#!/usr/bin/env bash
# Logical backup of red's upstream MariaDB (spohf2) → backups/*.sql.gz
#
# There is no mysql client on the dev machines, so the dump runs from a
# throwaway container whose client major version matches the server. The
# read-only account we use holds SELECT/SHOW VIEW and nothing else, which
# rules out --lock-tables, --routines and --events; every table is plain
# InnoDB, so --single-transaction gives a consistent snapshot without them.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backups}"
# Match the server's major version (MariaDB 10.11); a mismatched client can
# emit SET statements the server rejects on restore.
CLIENT_IMAGE="${CLIENT_IMAGE:-mariadb:10.11}"
# Raw LoRaWAN uplink log: ~3/4 of the volume and read by no application code.
BULK_TABLE="uplinks"

SKIP_BULK=""
for arg in "$@"; do
  case "$arg" in
    --no-uplinks) SKIP_BULK="1" ;;
    -h|--help)
      cat <<USAGE
Usage: ${BASH_SOURCE[0]##*/} [--no-uplinks]

  --no-uplinks   Skip the $BULK_TABLE rows (its schema is still included).
                 Much smaller and faster; no application code reads it.

Environment overrides: ENV_FILE, BACKUP_DIR, CLIENT_IMAGE
USAGE
      exit 0 ;;
    *) echo "unknown argument: $arg (try --help)" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null || { echo "docker is required but not on PATH" >&2; exit 1; }
[[ -r "$ENV_FILE" ]] || { echo "cannot read $ENV_FILE" >&2; exit 1; }

DB_NAME="$(sed -n 's/^WP6_RED_DB_NAME=//p' "$ENV_FILE" | tr -d '\r' | head -1)"
[[ -n "$DB_NAME" ]] || { echo "no WP6_RED_DB_NAME in $ENV_FILE" >&2; exit 1; }

# Credentials go to a 0600 file rather than argv, so they never reach shell
# history or `ps`. MYSQL_PWD is the same password under the name the client
# reads it from.
CREDS="$(mktemp)"
cleanup() { rm -f "$CREDS"; }
trap cleanup EXIT
{
  grep -E '^WP6_RED_DB_(HOST|PORT|NAME|USER|PASSWORD)=' "$ENV_FILE"
  sed -n 's/^WP6_RED_DB_PASSWORD=/MYSQL_PWD=/p' "$ENV_FILE"
} > "$CREDS"
grep -q '^MYSQL_PWD=' "$CREDS" || { echo "no WP6_RED_DB_PASSWORD in $ENV_FILE" >&2; exit 1; }

mkdir -p "$BACKUP_DIR"
SUFFIX=""
[[ -n "$SKIP_BULK" ]] && SUFFIX="-no-$BULK_TABLE"
TARGET="$BACKUP_DIR/$DB_NAME-$(date +%Y%m%d-%H%M)$SUFFIX.sql.gz"
# Write to .part first: an interrupted dump must never be left behind under a
# name that looks like a usable backup.
PARTIAL="$TARGET.part"
trap 'cleanup; rm -f "$PARTIAL"' EXIT

# Extra flags reach the container as positional args, so nothing is re-parsed
# by an intermediate shell.
dump() {
  docker run --rm -i --env-file "$CREDS" "$CLIENT_IMAGE" sh -c '
      exec mariadb-dump -h"$WP6_RED_DB_HOST" -P"$WP6_RED_DB_PORT" -u"$WP6_RED_DB_USER" \
        --single-transaction --quick --skip-lock-tables --skip-triggers \
        --default-character-set=utf8mb4 "$@" "$WP6_RED_DB_NAME"
    ' _ "$@"
}

DATA_ARGS=(--no-create-info)
[[ -n "$SKIP_BULK" ]] && DATA_ARGS+=(--ignore-table="$DB_NAME.$BULK_TABLE")

echo "=== Red MySQL backup ($DB_NAME) ==="
echo "--- Dumping → $(basename "$TARGET") ---"
# Two passes so --ignore-table drops only the rows: the structure pass carries
# every CREATE TABLE, plus the USE that the data pass then inherits.
{ dump --no-data --databases; dump "${DATA_ARGS[@]}"; } | gzip -6 > "$PARTIAL"

echo "--- Verifying archive ---"
gzip -t "$PARTIAL"
gzip -dc "$PARTIAL" | tail -5 | grep -q '^-- Dump completed' \
  || { echo "dump is truncated: no completion marker" >&2; exit 1; }
TABLES="$(gzip -dc "$PARTIAL" | grep -c '^CREATE TABLE')"

mv "$PARTIAL" "$TARGET"
trap cleanup EXIT
echo ""
echo "=== Done: $TABLES tables, $(du -h "$TARGET" | cut -f1) ==="
echo "$TARGET"
echo ""
echo "Restore into a scratch container with:"
echo "  gzip -dc '$TARGET' | mariadb -uroot -p"
