#!/bin/bash
# Dump the Cinderhaven Data Platform's Postgres database from Fly.io
# to a local SQL file for use with docker-compose.
#
# Prerequisites:
#   - flyctl installed and authenticated
#   - pg_dump available locally (via Postgres client tools)
#
# Usage:
#   DUMP_USER=<a cinderhaven_reader login> ./scripts/dump_flyio.sh
#
# The script proxies the Fly.io Postgres through a local port, runs
# pg_dump as a READER login over a named list of the platform's own schemas,
# and writes the output to data/cinderhaven_dump.sql.
#
# Overrides (plan U4, egress path 1), so the script can be pointed at a local
# instance for its own test:
#   DUMP_HOST, DUMP_PORT   target (default localhost:15432, the proxy)
#   SKIP_PROXY=1           do not start flyctl proxy
#   DUMP_SCHEMAS           space-separated schema list (default below)
#   DUMP_FILE              output path
# The password comes from PGPASSWORD or ~/.pgpass; this script never holds one.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DUMP_FILE="${DUMP_FILE:-$REPO_ROOT/data/cinderhaven_dump.sql}"
FLY_APP="${FLY_APP:-cinderhaven-db}"
DUMP_HOST="${DUMP_HOST:-localhost}"
DUMP_PORT="${DUMP_PORT:-15432}"
DUMP_USER="${DUMP_USER:?set DUMP_USER to a cinderhaven_reader login; the dump never runs as a superuser}"
# The platform's own schemas. A consumer's schema is not the platform's to dump.
# A schema the reader cannot read, truth included, fails on permission here
# instead of shipping.
DUMP_SCHEMAS="${DUMP_SCHEMAS:-raw costing copack voidfinder public_staging public_intermediate public_marts}"
# production-demand-forecast's derived snapshot tables in copack: that repo's data.
EXCLUDE_TABLES="copack.forecast_snapshot copack.forecast_week_snapshot copack.doom_loop_snapshot copack.snapshot_meta"

if [ "${SKIP_PROXY:-0}" != "1" ]; then
    echo "Starting Fly.io proxy on port $DUMP_PORT ..."
    flyctl proxy "$DUMP_PORT:5432" -a "$FLY_APP" &
    PROXY_PID=$!
    cleanup() {
        echo "Stopping proxy (PID $PROXY_PID) ..."
        kill "$PROXY_PID" 2>/dev/null || true
    }
    trap cleanup EXIT
    sleep 3
fi

SCHEMA_ARGS=()
for s in $DUMP_SCHEMAS; do SCHEMA_ARGS+=("--schema=$s"); done
for t in $EXCLUDE_TABLES; do SCHEMA_ARGS+=("--exclude-table=$t"); done

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
# Added 2026-09-02, before the truth schema existed, so it could not be
# forgotten once it did. Since U4 the dump also names its schemas and runs as
# a reader login, so truth is out three ways: not listed, excluded, unreadable.
pg_dump \
    --host="$DUMP_HOST" \
    --port="$DUMP_PORT" \
    --username="$DUMP_USER" \
    --dbname=cinderhaven \
    "${SCHEMA_ARGS[@]}" \
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
