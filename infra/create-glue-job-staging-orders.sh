#!/usr/bin/env bash
#
# create-glue-job-staging-orders.sh -- provision the Glue Job that transforms
# raw orders CSV into staging orders Parquet.
#
# Steps performed:
#   1. Zip src/olist_pipeline/ as the project library bundle.
#   2. Upload the bundle and the wrapper script to s3://${S3_BUCKET_STAGING}/_glue-jobs/.
#   3. Create the Glue Job (or update it in place if it already exists).
#
# Job configuration:
#   - Role: olist-glue-role (needs both glue-s3-read-raw and glue-s3-staging
#           inline policies -- attached by create-glue-role.sh).
#   - Glue version: 5.0 (Python 3.11, Spark 3.5).
#   - Worker type: G.1X x 2 -- minimum for glueetl, plenty for Olist scale.
#   - MaxRetries: 0 -- a buggy job retrying 3x at full cost is the anti-pattern.
#   - Job bookmarks: DISABLED -- we own the HWM via _metadata/*.json.
#
# Idempotent: re-upload always; create-job becomes update-job if it exists.
#
# Estimated cost per run: ~$0.07 (2 DPUs x 1 min minimum, billed per second
# after that). ON_DEMAND only -- never schedule.

set -euo pipefail

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Run this script from the project root." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

JOB_NAME="${GLUE_JOB_STAGING_PREFIX}-orders"
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)

GLUE_PREFIX="_glue-jobs"
WRAPPER_LOCAL="${SCRIPT_DIR}/glue-jobs/staging_orders_glue.py"
WRAPPER_S3_URI="s3://${S3_BUCKET_STAGING}/${GLUE_PREFIX}/staging_orders_glue.py"
LIBRARY_S3_URI="s3://${S3_BUCKET_STAGING}/${GLUE_PREFIX}/olist_pipeline.zip"

ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${GLUE_ROLE_NAME}"
JOB_ARN="arn:aws:glue:${AWS_REGION}:${AWS_ACCOUNT_ID}:job/${JOB_NAME}"

# ─── 1. Build the project library zip ───────────────────────────────────────
# Use Python stdlib instead of the `zip` CLI -- the latter is not on PATH in
# Git Bash on Windows.
TMP_ZIP=$(mktemp -t olist_pipeline_XXXXXX.zip)
trap 'rm -f "$TMP_ZIP"' EXIT
echo "  [build]  ${TMP_ZIP}"
python3 - "$TMP_ZIP" "${PROJECT_ROOT}/src" <<'PY'
import os
import sys
import zipfile

out_path, src_root = sys.argv[1], sys.argv[2]
package_dir = os.path.join(src_root, "olist_pipeline")
with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, _dirs, files in os.walk(package_dir):
        if "__pycache__" in root:
            continue
        for filename in files:
            if filename.endswith((".pyc", ".pyo")):
                continue
            abs_path = os.path.join(root, filename)
            arcname = os.path.relpath(abs_path, src_root)
            zf.write(abs_path, arcname.replace(os.sep, "/"))
PY

# ─── 2. Upload wrapper + library to S3 ──────────────────────────────────────
echo "  [upload] ${WRAPPER_S3_URI}"
aws s3 cp --region "$AWS_REGION" --quiet "$WRAPPER_LOCAL" "$WRAPPER_S3_URI"

echo "  [upload] ${LIBRARY_S3_URI}"
aws s3 cp --region "$AWS_REGION" --quiet "$TMP_ZIP" "$LIBRARY_S3_URI"

# ─── 3. Build the Job configuration JSON ────────────────────────────────────
COMMAND_JSON=$(cat <<EOF
{
    "Name": "glueetl",
    "ScriptLocation": "${WRAPPER_S3_URI}",
    "PythonVersion": "3"
}
EOF
)

DEFAULT_ARGS_JSON=$(cat <<EOF
{
    "--job-language": "python",
    "--job-bookmark-option": "job-bookmark-disable",
    "--enable-metrics": "true",
    "--extra-py-files": "${LIBRARY_S3_URI}",
    "--additional-python-modules": "boto3>=1.36.0,botocore>=1.36.0",
    "--TempDir": "s3://${S3_BUCKET_STAGING}/_glue-temp/",
    "--S3_BUCKET_RAW": "${S3_BUCKET_RAW}",
    "--S3_BUCKET_STAGING": "${S3_BUCKET_STAGING}"
}
EOF
)

# ─── 4. Create or update the Glue Job ───────────────────────────────────────
if aws glue get-job --region "$AWS_REGION" --job-name "$JOB_NAME" >/dev/null 2>&1; then
    echo "  [exists] job ${JOB_NAME} -- updating in place"
    JOB_UPDATE_JSON=$(cat <<EOF
{
    "Role": "${ROLE_ARN}",
    "Command": ${COMMAND_JSON},
    "DefaultArguments": ${DEFAULT_ARGS_JSON},
    "MaxRetries": 0,
    "GlueVersion": "5.0",
    "NumberOfWorkers": 2,
    "WorkerType": "G.1X"
}
EOF
)
    aws glue update-job \
        --region "$AWS_REGION" \
        --job-name "$JOB_NAME" \
        --job-update "$JOB_UPDATE_JSON" \
        >/dev/null
else
    echo "  [create] job ${JOB_NAME}"
    aws glue create-job \
        --region "$AWS_REGION" \
        --name "$JOB_NAME" \
        --role "$ROLE_ARN" \
        --command "$COMMAND_JSON" \
        --default-arguments "$DEFAULT_ARGS_JSON" \
        --max-retries 0 \
        --glue-version "5.0" \
        --number-of-workers 2 \
        --worker-type "G.1X" \
        --tags "{\"project\":\"${PROJECT_TAG}\",\"env\":\"${ENVIRONMENT}\",\"owner\":\"${OWNER_TAG}\"}" \
        >/dev/null
fi

# Re-assert tags via tag-resource (covers both branches; idempotent).
aws glue tag-resource \
    --region "$AWS_REGION" \
    --resource-arn "$JOB_ARN" \
    --tags-to-add "{\"project\":\"${PROJECT_TAG}\",\"env\":\"${ENVIRONMENT}\",\"owner\":\"${OWNER_TAG}\"}"

echo "  [done]   job ${JOB_NAME}"
echo "           Run with: bash infra/run-glue-job.sh ${JOB_NAME}"
