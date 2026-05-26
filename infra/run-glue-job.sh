#!/usr/bin/env bash
#
# run-glue-job.sh -- start a Glue Job on demand and block until it finishes.
#
# Usage: bash infra/run-glue-job.sh <job-name>
#
# Polls the Job state every 15 seconds. On any terminal state other than
# SUCCEEDED, prints the ErrorMessage from the run and exits non-zero so
# CI / chained scripts can detect failures.
#
# Estimated cost per run depends on the Job. For olist-staging-orders:
# ~$0.07 (2 DPUs x 1 min minimum). See `.claude/skills/aws-cost-discipline`.

set -euo pipefail

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Run this script from the project root." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

JOB_NAME="${1:-}"
if [[ -z "$JOB_NAME" ]]; then
    echo "Usage: bash infra/run-glue-job.sh <job-name>" >&2
    exit 1
fi

echo "Starting Glue Job: ${JOB_NAME}"
RUN_ID=$(aws glue start-job-run \
    --region "$AWS_REGION" \
    --job-name "$JOB_NAME" \
    --query 'JobRunId' \
    --output text)
echo "  run id: ${RUN_ID}"

echo "Waiting for completion (polling every 15s)..."
while true; do
    STATE=$(aws glue get-job-run \
        --region "$AWS_REGION" \
        --job-name "$JOB_NAME" \
        --run-id "$RUN_ID" \
        --query 'JobRun.JobRunState' \
        --output text)
    echo "  state: ${STATE}"
    case "$STATE" in
        SUCCEEDED)
            break
            ;;
        FAILED|STOPPED|TIMEOUT|ERROR)
            echo
            echo "Job ended in non-success state: ${STATE}" >&2
            echo "Error message:" >&2
            aws glue get-job-run \
                --region "$AWS_REGION" \
                --job-name "$JOB_NAME" \
                --run-id "$RUN_ID" \
                --query 'JobRun.ErrorMessage' \
                --output text >&2
            exit 1
            ;;
    esac
    sleep 15
done

echo
echo "Run summary:"
aws glue get-job-run \
    --region "$AWS_REGION" \
    --job-name "$JOB_NAME" \
    --run-id "$RUN_ID" \
    --query 'JobRun.{State:JobRunState,StartedOn:StartedOn,CompletedOn:CompletedOn,ExecutionTime:ExecutionTime,DPUSeconds:DPUSeconds}' \
    --output table
