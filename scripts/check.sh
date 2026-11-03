#!/usr/bin/env bash
# The validation gate: lint, unit tests, then e2e against the local containers.
#
# A script rather than a sequence to remember, because the half most easily
# forgotten is the half that matters most. CI's `build` job has `needs: check`
# and `check` runs e2e, so an e2e failure blocks the image push outright --
# leaving it out locally trades ~50s for a blocked push and a round trip to
# find out why.
#
# Running e2e used to cost more than that: it shared the dashboards' databases
# and dropped red's schema per test, so it destroyed local dev data. It no
# longer does -- the suite has its own wp6_blue_e2e / wp6_red_e2e, created on
# first run -- so there is nothing left to weigh up, and nothing to stop first.
#
# Starting the backing services is part of the gate on purpose. scripts/dev.sh
# deliberately does not start them, because it has to work against a remote
# database too; this script only ever runs against the local containers, so
# there is no such ambiguity here.
#
#   scripts/check.sh           the gate -- run this before any push
#   scripts/check.sh --fast    stop after the unit tests (inner loop)

set -euo pipefail

cd "$(dirname "$0")/.."

uv sync --extra dev
uv run ruff check src/ tests/ --fix
uv run pytest

if [[ "${1:-}" == "--fast" ]]; then
    echo
    echo "check: e2e skipped (--fast). Fine while iterating, not enough to push on."
    exit 0
fi

docker compose -f docker-compose.tsdb.yml up -d --wait
uv run pytest tests/e2e/

echo
echo "check: lint, unit and e2e all green."
