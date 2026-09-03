#!/bin/bash
# Dump the Cinderhaven Data Platform's Postgres database from Fly.io
# to a local SQL file for use with docker-compose.
#
# Prerequisites:
#   - flyctl installed and authenticated
#   - pg_dump available locally (via Postgres client tools)
#
# Usage:
#   ./scripts/dump_flyio.sh
#
# The script proxies the Fly.io Postgres through a local port, runs
# pg_dump, and writes the output to data/cinderhaven_dump.sql.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DUMP_FILE="$REPO_ROOT/data/cinderhaven_dump.sql"
FLY_APP="cinderhaven-data-platform-db"
LOCAL_PORT=15432

echo "Starting Fly.io proxy on port $LOCAL_PORT ..."
flyctl proxy "$LOCAL_PORT:5432" -a "$FLY_APP" &
PROXY_PID=$!

cleanup() {
    echo "Stopping proxy (PID $PROXY_PID) ..."
    kill "$PROXY_PID" 2>/dev/null || true
}
trap cleanup EXIT

sleep 3

echo "Running pg_dump ..."
# Dump all schemas EXCEPT truth — dbt creates public_staging, public_intermediate,
# public_marts (default schema naming with target schema = public).
# Raw source tables live in the raw schema.
#
# truth is excluded deliberately and must stay excluded. It holds the planted
# ground truth (injection_ledger, corruption_ledger, promo_events,
# outage_episodes, defect_ledger) that estimation-path code must provably
# never read. A dump is the widest egress path ON THE ESTIMATION PATH: this
# file feeds docker-compose through init-db.sh, which restores as superuser,
# so without this exclusion every local dev environment would hold the answer
# key in the clear -- and the dump file on disk would be a second copy of it.
#
# The qualifier matters and the earlier unqualified superlative was wrong.
# Fly.io's automatic volume snapshots copy the whole disk and no
# --exclude-schema exists at that layer, so they are strictly wider. They are
# also OUT OF MODEL by design: the quarantine makes accuracy claims provable,
# it is not DRM. A person with Fly org access restoring a snapshot to look is
# the same actor as one who opens the truth parquet, and the guarantee was
# never aimed at them. In-scope egress is anything on the estimation path or
# in a consuming repo -- which this dump is, which is why this flag exists.
#
# Note --no-privileges below: the dump strips GRANTs, so a restored copy
# carries no role protection even if truth had it in production. Excluding
# the schema is therefore the only control on this path, not one of two.
#
# Added 2026-09-02, before the truth schema exists, so it cannot be forgotten
# once it does. It matches nothing today. That is intended, not dead config.
pg_dump \
    --host=localhost \
    --port="$LOCAL_PORT" \
    --username=postgres \
    --dbname=cinderhaven \
    --no-owner \
    --no-privileges \
    --if-exists \
    --clean \
    --exclude-schema=information_schema \
    --exclude-schema=truth \
    --exclude-schema='pg_*' \
    > "$DUMP_FILE"

echo "Dump written to $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"
echo ""
echo "Next: run 'docker compose up' to start local Postgres with this data."
