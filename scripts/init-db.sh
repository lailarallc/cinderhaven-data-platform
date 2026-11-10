#!/bin/bash
# Restore the Cinderhaven Data Platform dump into the local Postgres.
# Runs automatically on first `docker compose up` via the entrypoint.

DUMP_FILE="${DUMP_FILE:-/data/cinderhaven_dump.sql}"

if [ ! -f "$DUMP_FILE" ]; then
    echo "==================================================="
    echo "WARNING: $DUMP_FILE not found."
    echo ""
    echo "Run scripts/dump_flyio.sh to generate the dump file,"
    echo "then restart the container:"
    echo "  docker compose down && docker compose up"
    echo "==================================================="
    exit 0
fi

# Refuse a dump that creates the truth schema (plan U4, egress path 1). The dump
# strips GRANTs, so on the restore side exclusion is the only control.
if grep -Eiq '^CREATE SCHEMA (IF NOT EXISTS )?"?truth"?;' "$DUMP_FILE"; then
    echo "REFUSED: $DUMP_FILE creates the truth schema. Re-dump with scripts/dump_flyio.sh." >&2
    exit 1
fi

echo "Restoring Cinderhaven data from $DUMP_FILE ..."
psql -U postgres -d cinderhaven -f "$DUMP_FILE"

# Set default search_path so downstream projects can query mart and
# staging tables without schema-qualifying every name.
# dbt creates: public_marts, public_staging, public_intermediate.
# Raw source tables live in the raw schema.
psql -U postgres -d cinderhaven -c \
    "ALTER DATABASE cinderhaven SET search_path TO public_marts, public_staging, public_intermediate, raw, public;"

# Supplemental seeds not in the Fly.io dump (dbt seeds that haven't
# been deployed yet).
SEED_DIR="/data/seeds"
if [ -d "$SEED_DIR" ]; then
    for f in "$SEED_DIR"/*.sql; do
        [ -f "$f" ] || continue
        echo "Running supplemental seed: $(basename "$f")"
        psql -U postgres -d cinderhaven -f "$f"
    done
fi

echo "Seed complete."
