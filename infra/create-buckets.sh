#!/usr/bin/env bash
#
# create-buckets.sh -- provision the four S3 buckets of olist-bi-pipeline.
#
# Buckets (medallion layers + Athena query results):
#   - S3_BUCKET_RAW             append-only CSV+gzip   (ADR-0002)
#   - S3_BUCKET_STAGING         typed Parquet
#   - S3_BUCKET_CURATED         star-schema Parquet
#   - S3_BUCKET_ATHENA_RESULTS  Athena query result location (ADR-0001)
#
# Each bucket is created private (all public access blocked), encrypted at
# rest (SSE-S3 / AES256) and carries the three mandatory project tags.
# Versioning is left OFF on purpose: the raw layer uses date partitions as
# its version mechanism (ADR-0002), and versioning + overwrites grows cost
# silently (see the cost skill).
#
# Idempotent: an existing bucket is not re-created, but its configuration
# (public-access block, encryption, tags) is re-asserted on every run -- the
# put-* calls are themselves idempotent. Safe to call from bring-up.sh.
#
# Estimated monthly cost: negligible. The whole Olist dataset is < 1 GB
# across all layers; S3 Standard at ~$0.023/GB-month is a few cents.
# See .claude/skills/aws-cost-discipline/SKILL.md.
#
# Prerequisite: run infra/budgets.sh first so the $5/$20/$50 alert ladder
# is in place before any resource is provisioned.

set -euo pipefail

# Load region, bucket names and tag values from .env (never hardcoded).
if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Run this script from the project root." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

TAG_SET="TagSet=[{Key=project,Value=${PROJECT_TAG}},{Key=env,Value=${ENVIRONMENT}},{Key=owner,Value=${OWNER_TAG}}]"

create_bucket() {
    local bucket="$1"

    if aws s3api head-bucket --bucket "$bucket" 2>/dev/null; then
        echo "  [exists] ${bucket} -- re-asserting configuration"
    else
        echo "  [create] ${bucket}"
        if [[ "$AWS_REGION" == "us-east-1" ]]; then
            aws s3api create-bucket --bucket "$bucket" --region "$AWS_REGION" >/dev/null
        else
            aws s3api create-bucket --bucket "$bucket" --region "$AWS_REGION" \
                --create-bucket-configuration "LocationConstraint=${AWS_REGION}" >/dev/null
        fi
    fi

    # The three put-* calls below are idempotent -- re-applying them costs
    # nothing and self-heals a half-configured bucket.
    aws s3api put-public-access-block --bucket "$bucket" \
        --public-access-block-configuration \
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

    aws s3api put-bucket-encryption --bucket "$bucket" \
        --server-side-encryption-configuration \
        '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

    aws s3api put-bucket-tagging --bucket "$bucket" --tagging "$TAG_SET"

    echo "  [ready]  ${bucket} -- private, encrypted, tagged"
}

echo "Provisioning S3 buckets in ${AWS_REGION} (profile: ${AWS_PROFILE})"
create_bucket "$S3_BUCKET_RAW"
create_bucket "$S3_BUCKET_STAGING"
create_bucket "$S3_BUCKET_CURATED"
create_bucket "$S3_BUCKET_ATHENA_RESULTS"
echo "All four buckets ready."
