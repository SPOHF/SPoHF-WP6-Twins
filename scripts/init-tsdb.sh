#!/bin/bash
# Provisions the wp6_red role + database alongside the default wp6_blue
# database, plus a dedicated pair for the e2e suite. Runs only on first volume
# initialisation (Postgres docker entrypoint convention); the e2e conftest
# creates the e2e pair itself if the volume predates them, so an existing
# container never needs `down -v`.
#
# Mirrors the production layout from issue 001: one TimescaleDB instance, two
# databases (wp6_blue, wp6_red), each owned by its own role.
#
# The e2e databases exist because the suite bootstraps and DROPS red's schema
# per test. Pointed at the dev database that deleted whatever you were looking
# at, which is the same reason the s3mock container has a separate wp6-e2e
# bucket (see docker-compose.tsdb.yml).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wp6_red') THEN
            CREATE ROLE wp6_red WITH LOGIN PASSWORD 'wp6dev';
        END IF;
    END
    \$\$;

    CREATE DATABASE wp6_red OWNER wp6_red;
    CREATE DATABASE wp6_blue_e2e OWNER "$POSTGRES_USER";
    CREATE DATABASE wp6_red_e2e OWNER wp6_red;
EOSQL

for db in wp6_red wp6_blue_e2e wp6_red_e2e; do
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<-EOSQL
        CREATE EXTENSION IF NOT EXISTS timescaledb;
EOSQL
done
