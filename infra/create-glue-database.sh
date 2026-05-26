#!/usr/bin/env bash
#
# create-glue-database.sh -- create the Glue Data Catalog database for olist-bi-pipeline.
#
# The database is a logical container for the tables that Crawlers and Jobs
# will register (raw_*, staging_*, fact_*, dim_*). It holds metadata only;
# the actual data stays in S3.
#
# Idempotent: re-asserts the three mandatory tags on every run; skips
# create-database if the database already exists.
#
# Estimated monthly cost: $0. Glue Data Catalog storage is free for the first
# 1M objects per month; we will have tens, not millions.

set -euo pipefail

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Run this script from the project root." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

DATABASE_NAME="${GLUE_DATABASE}"
DATABASE_ARN="arn:aws:glue:${AWS_REGION}:${AWS_ACCOUNT_ID}:database/${DATABASE_NAME}"

if aws glue get-database --name "$DATABASE_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "  [exists] database ${DATABASE_NAME} -- re-asserting tags"
else
    echo "  [create] database ${DATABASE_NAME}"
    aws glue create-database \
        --region "$AWS_REGION" \
        --database-input "{\"Name\":\"${DATABASE_NAME}\",\"Description\":\"olist-bi-pipeline -- ${ENVIRONMENT} environment\"}" \
        >/dev/null
fi

# Glue resource tags are applied via a separate API call (Glue databases do
# not accept --tags on create-database).
aws glue tag-resource \
    --region "$AWS_REGION" \
    --resource-arn "$DATABASE_ARN" \
    --tags-to-add "{\"project\":\"${PROJECT_TAG}\",\"env\":\"${ENVIRONMENT}\",\"owner\":\"${OWNER_TAG}\"}"

echo "  [done]   database ${DATABASE_NAME}"
