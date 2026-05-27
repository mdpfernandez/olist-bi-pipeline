#!/usr/bin/env bash
#
# run-crawler.sh -- start a Glue Crawler on demand and block until it finishes.
#
# Usage: bash infra/run-crawler.sh <crawler-name>
#
# Polls the Crawler state every 10 seconds. When the state returns to READY,
# prints the LastCrawl summary (status, tables changed, runtime) and exits.
#
# Estimated cost per run depends on the Crawler -- for olist-raw-crawler it is
# ~$0.007. See .claude/skills/aws-cost-discipline for the cost shape.

set -euo pipefail

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Run this script from the project root." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

CRAWLER_NAME="${1:-}"
if [[ -z "$CRAWLER_NAME" ]]; then
    echo "Usage: bash infra/run-crawler.sh <crawler-name>" >&2
    exit 1
fi

echo "Starting crawler: ${CRAWLER_NAME}"
aws glue start-crawler --region "$AWS_REGION" --name "$CRAWLER_NAME"

echo "Waiting for crawler to finish (polling every 10s)..."
while true; do
    state=$(aws glue get-crawler \
        --region "$AWS_REGION" \
        --name "$CRAWLER_NAME" \
        --query 'Crawler.State' \
        --output text)
    echo "  state: ${state}"
    if [[ "$state" == "READY" ]]; then
        break
    fi
    sleep 10
done

echo
echo "Last crawl summary:"
aws glue get-crawler \
    --region "$AWS_REGION" \
    --name "$CRAWLER_NAME" \
    --query 'Crawler.LastCrawl' \
    --output table

echo
echo "Tables in database ${GLUE_DATABASE}:"
aws glue get-tables \
    --region "$AWS_REGION" \
    --database-name "$GLUE_DATABASE" \
    --query 'TableList[].Name' \
    --output table
