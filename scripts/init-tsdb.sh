#!/bin/bash
# Provisions the wp6_red role + database alongside the default wp6_blue
# database. Runs only on first volume initialisation (Postgres docker
# entrypoint convention). Mirrors the production layout from issue 001:
# one TimescaleDB instance, two databases (wp6_blue, wp6_red), each
# owned by its own role.
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
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "wp6_red" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS timescaledb;
EOSQL
