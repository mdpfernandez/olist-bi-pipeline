#!/usr/bin/env bash
#
# create-glue-role.sh -- create the IAM role that Glue services assume to read
# the raw S3 bucket and write to the Glue Data Catalog.
#
# Composition:
#   - Trust policy        : glue.amazonaws.com is allowed to assume the role.
#   - AWSGlueServiceRole  : AWS-managed policy with the baseline Catalog +
#                           CloudWatch logs permissions every Glue job needs.
#   - olist-glue-s3-read-raw (inline): read-only access scoped to the raw
#                           bucket only (least privilege -- no staging, no
#                           curated, no other buckets).
#
# Idempotent: the create-role step is skipped if the role already exists, but
# the policy attachments and inline policy are re-asserted on every run (the
# AWS calls themselves are idempotent).
#
# Estimated monthly cost: $0. IAM is always free.
#
# Requires `envsubst` on PATH (ships with Git for Windows / msys / coreutils).

set -euo pipefail

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Run this script from the project root." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

if ! command -v envsubst >/dev/null 2>&1; then
    echo "ERROR: envsubst is required but not on PATH." >&2
    echo "       On Windows it ships with Git for Windows (in /usr/bin)." >&2
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROLE_NAME="${GLUE_ROLE_NAME}"
TRUST_POLICY_FILE="${SCRIPT_DIR}/iam-policies/glue-trust-policy.json"
RAW_POLICY_TEMPLATE="${SCRIPT_DIR}/iam-policies/glue-s3-read-raw.json"
STAGING_POLICY_TEMPLATE="${SCRIPT_DIR}/iam-policies/glue-s3-staging.json"

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    echo "  [exists] role ${ROLE_NAME} -- re-asserting policies"
else
    echo "  [create] role ${ROLE_NAME}"
    # Read the JSON into a variable instead of using `file://` -- the AWS CLI
    # on Windows + Git Bash fails to parse the mixed POSIX/native path that
    # `${SCRIPT_DIR}` produces. Passing the JSON as a string sidesteps the
    # whole path-translation problem.
    TRUST_POLICY_DOCUMENT=$(cat "$TRUST_POLICY_FILE")
    aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY_DOCUMENT" \
        --description "Role assumed by AWS Glue for olist-bi-pipeline" \
        --tags \
            "Key=project,Value=${PROJECT_TAG}" \
            "Key=env,Value=${ENVIRONMENT}" \
            "Key=owner,Value=${OWNER_TAG}" \
        >/dev/null
fi

# AWS-managed baseline policy. attach-role-policy is idempotent -- attaching
# an already-attached policy is a no-op.
aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"

# Custom inline policy #1: read-only on the raw bucket. We render the
# template with envsubst, restricting substitution to S3_BUCKET_RAW so any
# other `${...}` in the JSON would survive untouched.
RAW_POLICY_DOCUMENT=$(envsubst '${S3_BUCKET_RAW}' < "$RAW_POLICY_TEMPLATE")
aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "olist-glue-s3-read-raw" \
    --policy-document "$RAW_POLICY_DOCUMENT"

# Custom inline policy #2: read+write+delete on the staging bucket. Needed
# by the staging Glue Jobs (write Parquet, overwrite partitions, manage the
# HWM state file) and to read the Job script bundle uploaded under
# `_glue-jobs/`. Still least-privilege -- no access to raw write, curated,
# or any other bucket.
STAGING_POLICY_DOCUMENT=$(envsubst '${S3_BUCKET_STAGING}' < "$STAGING_POLICY_TEMPLATE")
aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "olist-glue-s3-staging" \
    --policy-document "$STAGING_POLICY_DOCUMENT"

echo "  [done]   role ${ROLE_NAME}"
