#!/usr/bin/env bash
#
# create-athena-workgroup.sh -- provision the Athena workgroup for ad-hoc and
# Power-BI-driven queries against the staging/curated layers.
#
# What a workgroup is:
#   An Athena workgroup bundles together (a) where query results are written,
#   (b) a per-query bytes-scanned cap, (c) the encryption settings for those
#   results, and (d) the tag/cost attribution. Forcing every query through a
#   single named workgroup keeps cost predictable and queries auditable.
#
# Configuration applied:
#   - ResultConfiguration.OutputLocation: s3://${S3_BUCKET_ATHENA_RESULTS}/
#     Athena writes one CSV + one metadata file per query to this prefix.
#   - ResultConfiguration.EncryptionOption: SSE_S3
#     Matches the bucket-level default encryption (`create-buckets.sh`).
#   - BytesScannedCutoffPerQuery: 1 GiB (1073741824 bytes).
#     Any single query that would scan more than 1 GiB is cancelled. Cheap
#     guardrail against a `SELECT *` over a non-partitioned table.
#   - EnforceWorkGroupConfiguration: true
#     Clients (Power BI, the AWS console, the CLI) cannot override the cap
#     or the result location. Without this, a Power BI user could silently
#     redirect results to a different bucket.
#   - PublishCloudWatchMetricsEnabled: false
#     CloudWatch custom metrics cost $0.30/metric/month above the free tier.
#     Off for portfolio; flip to true if we need query observability later.
#
# Idempotent: detects the workgroup and runs update-work-group instead of
# create-work-group; tags are re-asserted on every run.
#
# Estimated monthly cost: $0. Athena workgroups themselves are free; the
# only Athena charge is $5/TB scanned by queries, and the first 1 TB/month
# is on the AWS free tier for the first 12 months. Result CSVs in
# olist-athena-results-* are a few KB per query -- negligible S3 storage.

set -euo pipefail

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Run this script from the project root." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

WORKGROUP_NAME="${ATHENA_WORKGROUP}"
WORKGROUP_ARN="arn:aws:athena:${AWS_REGION}:${AWS_ACCOUNT_ID}:workgroup/${WORKGROUP_NAME}"

# 1 GiB cap (binary, not decimal). Same convention Athena uses internally.
BYTES_SCANNED_CAP=1073741824

CONFIG_JSON=$(cat <<EOF
{
    "ResultConfiguration": {
        "OutputLocation": "s3://${S3_BUCKET_ATHENA_RESULTS}/",
        "EncryptionConfiguration": {
            "EncryptionOption": "SSE_S3"
        }
    },
    "EnforceWorkGroupConfiguration": true,
    "PublishCloudWatchMetricsEnabled": false,
    "BytesScannedCutoffPerQuery": ${BYTES_SCANNED_CAP},
    "RequesterPaysEnabled": false
}
EOF
)

# Update-time the API uses a slightly different shape -- ResultConfigurationUpdates
# instead of ResultConfiguration -- so we build a second JSON for that branch.
UPDATE_JSON=$(cat <<EOF
{
    "ResultConfigurationUpdates": {
        "OutputLocation": "s3://${S3_BUCKET_ATHENA_RESULTS}/",
        "EncryptionConfiguration": {
            "EncryptionOption": "SSE_S3"
        }
    },
    "EnforceWorkGroupConfiguration": true,
    "PublishCloudWatchMetricsEnabled": false,
    "BytesScannedCutoffPerQuery": ${BYTES_SCANNED_CAP},
    "RequesterPaysEnabled": false
}
EOF
)

if aws athena get-work-group --region "$AWS_REGION" --work-group "$WORKGROUP_NAME" >/dev/null 2>&1; then
    echo "  [exists] workgroup ${WORKGROUP_NAME} -- updating configuration in place"
    aws athena update-work-group \
        --region "$AWS_REGION" \
        --work-group "$WORKGROUP_NAME" \
        --description "olist-bi-pipeline -- ${ENVIRONMENT} ad-hoc + Power BI queries" \
        --configuration-updates "$UPDATE_JSON" \
        --state ENABLED \
        >/dev/null
else
    echo "  [create] workgroup ${WORKGROUP_NAME}"
    aws athena create-work-group \
        --region "$AWS_REGION" \
        --name "$WORKGROUP_NAME" \
        --description "olist-bi-pipeline -- ${ENVIRONMENT} ad-hoc + Power BI queries" \
        --configuration "$CONFIG_JSON" \
        --tags "Key=project,Value=${PROJECT_TAG}" "Key=env,Value=${ENVIRONMENT}" "Key=owner,Value=${OWNER_TAG}" \
        >/dev/null
fi

# Re-assert tags (covers both branches; idempotent).
aws athena tag-resource \
    --region "$AWS_REGION" \
    --resource-arn "$WORKGROUP_ARN" \
    --tags "Key=project,Value=${PROJECT_TAG}" "Key=env,Value=${ENVIRONMENT}" "Key=owner,Value=${OWNER_TAG}" \
    >/dev/null

echo "  [done]   workgroup ${WORKGROUP_NAME}"
echo "           Run queries with: aws athena start-query-execution --work-group ${WORKGROUP_NAME} ..."
