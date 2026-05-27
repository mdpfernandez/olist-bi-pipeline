#!/usr/bin/env bash
#
# create-staging-tables.sh -- register the staging-layer tables in the Glue
# Data Catalog so Athena (and Power BI through it) can query them.
#
# Why CREATE EXTERNAL TABLE and not a Crawler:
#   The staging Parquet files already carry an embedded, explicit schema
#   (written by the Glue Job). A Crawler would re-infer that schema -- extra
#   cost, an extra ON_DEMAND resource to manage, and a risk of surprises like
#   the `col0..col7` quirk we hit on the raw CSV layer. Declaring the table
#   here makes the schema the source of truth and costs $0. See
#   `docs/architecture.md` -> "Staging table registration".
#
# Why partition projection (TBLPROPERTIES 'projection.*'):
#   The table is partitioned by year/month. Without projection we would have
#   to run `MSCK REPAIR TABLE` (or ALTER TABLE ADD PARTITION) after every Glue
#   Job run to make new partitions visible. Projection instead tells Athena
#   the partition values up front (years 2016-2030, months 1-12) and the path
#   template, so Athena computes them on the fly -- zero maintenance.
#
# Idempotent: each table is DROP-then-CREATE. DROP TABLE removes only the
# Catalog metadata, never the S3 data, so re-running is safe and makes the
# DDL in this file the single source of truth for the table shape.
#
# Estimated cost: $0. DDL statements (CREATE/DROP/DESCRIBE) scan no data, so
# they fall outside Athena's $5/TB metering entirely.

set -euo pipefail

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Run this script from the project root." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

# ─── Athena query runner ─────────────────────────────────────────────────────
# Athena is asynchronous: start-query-execution returns an id, then we poll
# get-query-execution until the state is terminal. All queries run inside the
# olist-dev workgroup so the 1 GiB cap and result location are enforced.
run_athena_query() {
    local sql="$1"
    local label="$2"

    local query_id
    query_id=$(aws athena start-query-execution \
        --region "$AWS_REGION" \
        --work-group "$ATHENA_WORKGROUP" \
        --query-string "$sql" \
        --query "QueryExecutionId" \
        --output text)

    echo "  [run]    ${label} (query ${query_id})"

    while true; do
        local state
        state=$(aws athena get-query-execution \
            --region "$AWS_REGION" \
            --query-execution-id "$query_id" \
            --query "QueryExecution.Status.State" \
            --output text)

        case "$state" in
            SUCCEEDED)
                echo "  [ok]     ${label}"
                return 0
                ;;
            FAILED | CANCELLED)
                local reason
                reason=$(aws athena get-query-execution \
                    --region "$AWS_REGION" \
                    --query-execution-id "$query_id" \
                    --query "QueryExecution.Status.StateChangeReason" \
                    --output text)
                echo "  [FAIL]   ${label}: ${reason}" >&2
                return 1
                ;;
            *)
                # QUEUED | RUNNING -- DDL completes in ~1-3s; poll gently.
                sleep 2
                ;;
        esac
    done
}

# ─── staging_orders ──────────────────────────────────────────────────────────
# Schema mirrors what the Glue Job writes (src/olist_pipeline/transformation/
# staging_orders.py + infra/glue-jobs/staging_orders_glue.py):
#   - 8 columns from the Olist orders CSV, five of them cast to TIMESTAMP.
#   - `ingested_at` (STRING) carried over from the raw Hive partition.
#   - year/month are partition columns (live in the S3 path, not the file).
#
# NOTE on the partition-value format: Spark writes integer partition columns
# WITHOUT zero-padding (month=9, month=10 -- not month=09). The projection
# below therefore declares no `digits`, so Athena matches the bare integers.
# If a smoke-test SELECT returns 0 rows while S3 clearly has data, the cause
# is almost always a padding mismatch here -- check the actual S3 paths with
#   aws s3 ls s3://${S3_BUCKET_STAGING}/source=orders/
# and add 'projection.month.digits'='2' if the paths are zero-padded.
#
# The heredoc is unquoted so ${S3_BUCKET_STAGING} expands, but the projection
# placeholders \${year}/\${month} are escaped so they stay literal for Athena.
STAGING_ORDERS_DDL=$(cat <<EOF
CREATE EXTERNAL TABLE ${GLUE_DATABASE}.staging_orders (
    order_id                       STRING,
    customer_id                    STRING,
    order_status                   STRING,
    order_purchase_timestamp       TIMESTAMP,
    order_approved_at              TIMESTAMP,
    order_delivered_carrier_date   TIMESTAMP,
    order_delivered_customer_date  TIMESTAMP,
    order_estimated_delivery_date  TIMESTAMP,
    ingested_at                    STRING
)
PARTITIONED BY (
    year  INT,
    month INT
)
STORED AS PARQUET
LOCATION 's3://${S3_BUCKET_STAGING}/source=orders/'
TBLPROPERTIES (
    'parquet.compression'       = 'SNAPPY',
    'projection.enabled'        = 'true',
    'projection.year.type'      = 'integer',
    'projection.year.range'     = '2016,2030',
    'projection.month.type'     = 'integer',
    'projection.month.range'    = '1,12',
    'storage.location.template' = 's3://${S3_BUCKET_STAGING}/source=orders/year=\${year}/month=\${month}'
)
EOF
)

echo "Registering staging tables in ${GLUE_DATABASE} (workgroup: ${ATHENA_WORKGROUP})"

run_athena_query "DROP TABLE IF EXISTS ${GLUE_DATABASE}.staging_orders" "drop staging_orders"
run_athena_query "$STAGING_ORDERS_DDL" "create staging_orders"

echo "All staging tables registered."
echo "Smoke test:"
echo "  aws athena start-query-execution --work-group ${ATHENA_WORKGROUP} \\"
echo "    --query-string 'SELECT count(*) FROM ${GLUE_DATABASE}.staging_orders'"
