#!/usr/bin/env bash
#
# create-raw-crawler.sh -- create the Glue Crawler that registers the nine raw
# tables in the Glue Data Catalog.
#
# Layout:
#   - One Crawler `olist-raw-crawler`.
#   - Nine S3 targets, one per `source=<table>/` prefix on the raw bucket.
#     The Crawler treats `ingested_at=<date>/` below each target as a Hive
#     partition column, so each ingest day becomes a partition (not a table).
#   - TablePrefix=raw_ -- resulting tables: raw_source_orders, raw_source_..._
#     (Glue sanitises `=` to `_` when deriving table names from path segments).
#   - Schedule: ON_DEMAND. Mandatory per .claude/skills/aws-cost-discipline:
#     a scheduled Crawler is the #1 portfolio cost surprise.
#
# Idempotent: if the Crawler exists, its configuration is updated in place
# (update-crawler is itself idempotent); tags are re-asserted via a separate
# Glue tag-resource call.
#
# Estimated cost per run: ~$0.007 (1 DPU x ~1 minute). At ~30 runs/month in
# dev: ~$0.21/month. Never schedule.

set -euo pipefail

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Run this script from the project root." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

CRAWLER_NAME="olist-raw-crawler"
CRAWLER_ARN="arn:aws:glue:${AWS_REGION}:${AWS_ACCOUNT_ID}:crawler/${CRAWLER_NAME}"
ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${GLUE_ROLE_NAME}"
CLASSIFIER_NAME="olist-csv-with-header"

# Custom CSV classifier so the Crawler reads the first row as column names
# instead of treating it as data and naming columns col0, col1, ... The
# built-in CSV classifier is heuristic and frequently fails to detect
# headers in gzipped CSVs.
if aws glue get-classifier --region "$AWS_REGION" --name "$CLASSIFIER_NAME" >/dev/null 2>&1; then
    echo "  [exists] classifier ${CLASSIFIER_NAME}"
else
    echo "  [create] classifier ${CLASSIFIER_NAME}"
    aws glue create-classifier \
        --region "$AWS_REGION" \
        --csv-classifier "{
            \"Name\": \"${CLASSIFIER_NAME}\",
            \"Delimiter\": \",\",
            \"QuoteSymbol\": \"\\\"\",
            \"ContainsHeader\": \"PRESENT\",
            \"DisableValueTrimming\": false,
            \"AllowSingleColumn\": false
        }"
fi

TABLES=(
    orders
    order_items
    order_payments
    order_reviews
    customers
    sellers
    products
    geolocation
    product_category_name_translation
)

# Build the S3Targets array as JSON: one entry per source table.
target_items=()
for table in "${TABLES[@]}"; do
    target_items+=("{\"Path\":\"s3://${S3_BUCKET_RAW}/source=${table}/\"}")
done
# Join items with commas via IFS expansion of the array.
joined=$(IFS=,; echo "${target_items[*]}")
TARGETS_JSON="{\"S3Targets\":[${joined}]}"

if aws glue get-crawler --name "$CRAWLER_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "  [exists] crawler ${CRAWLER_NAME} -- updating in place"
    aws glue update-crawler \
        --region "$AWS_REGION" \
        --name "$CRAWLER_NAME" \
        --role "$ROLE_ARN" \
        --database-name "$GLUE_DATABASE" \
        --targets "$TARGETS_JSON" \
        --table-prefix "raw_" \
        --classifiers "$CLASSIFIER_NAME"
else
    echo "  [create] crawler ${CRAWLER_NAME} (ON_DEMAND)"
    # IAM eventual consistency: a freshly-created Glue role often takes
    # 5-30 seconds to become assumable by the Glue service. We retry on
    # the specific "unable to assume provided role" error and bubble up
    # any other failure unchanged.
    err_file=$(mktemp)
    trap 'rm -f "$err_file"' EXIT
    for attempt in $(seq 1 12); do
        if aws glue create-crawler \
                --region "$AWS_REGION" \
                --name "$CRAWLER_NAME" \
                --role "$ROLE_ARN" \
                --database-name "$GLUE_DATABASE" \
                --targets "$TARGETS_JSON" \
                --table-prefix "raw_" \
                --classifiers "$CLASSIFIER_NAME" \
                --tags "{\"project\":\"${PROJECT_TAG}\",\"env\":\"${ENVIRONMENT}\",\"owner\":\"${OWNER_TAG}\"}" \
                2>"$err_file"; then
            break
        fi
        if grep -q "unable to assume provided role" "$err_file"; then
            echo "  [wait]   IAM role not yet propagated (attempt ${attempt}/12); sleeping 5s"
            sleep 5
            continue
        fi
        cat "$err_file" >&2
        exit 1
    done
    if [[ "$attempt" -eq 12 ]] && grep -q "unable to assume provided role" "$err_file" 2>/dev/null; then
        echo "ERROR: gave up waiting for IAM role to propagate after 60s" >&2
        exit 1
    fi
fi

# Re-assert tags on every run (cheap idempotent call; covers the existing-crawler path).
aws glue tag-resource \
    --region "$AWS_REGION" \
    --resource-arn "$CRAWLER_ARN" \
    --tags-to-add "{\"project\":\"${PROJECT_TAG}\",\"env\":\"${ENVIRONMENT}\",\"owner\":\"${OWNER_TAG}\"}"

echo "  [done]   crawler ${CRAWLER_NAME}"
echo "           Run with: bash infra/run-crawler.sh ${CRAWLER_NAME}"
