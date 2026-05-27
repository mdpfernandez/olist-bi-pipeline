#!/usr/bin/env bash
#
# budgets.sh -- create the three cost-alert budgets for olist-bi-pipeline.
#
# Three forecasted budgets, all filtered by tag `project=olist-pipeline`, so
# they react only to this project and not to the rest of your AWS usage:
#
#   olist-warning    $5/month forecasted  -> "something is running, check it"
#   olist-attention  $20/month forecasted -> "something is running too much"
#   olist-stop       $50/month forecasted -> "stop everything and triage"
#
# Each budget emails ${ALERT_EMAIL} when the FORECASTED monthly spend exceeds
# 100% of the threshold. See .claude/skills/aws-cost-discipline/SKILL.md.
#
# IMPORTANT pre-requisite, one-time, MANUAL step in the AWS console:
#   Billing -> "Cost allocation tags" -> activate the `project` user tag.
#   Without this activation, the tag filter silently matches nothing and the
#   budgets never fire. Newly-activated tags can take up to 24h to appear in
#   cost data.
#
# Idempotent: a budget that already exists is skipped. To change a threshold,
# delete the budget manually first (`aws budgets delete-budget`).
#
# Estimated monthly cost: < $1. AWS gives the first 2 budgets without
# actions for free; the 3rd is roughly $0.02/day.

set -euo pipefail

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Run this script from the project root." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -z "${ALERT_EMAIL:-}" || "$ALERT_EMAIL" == "your.email@example.com" ]]; then
    echo "ERROR: ALERT_EMAIL is not set (or still the placeholder) in .env." >&2
    echo "       Add a line like:  ALERT_EMAIL=you@example.com" >&2
    exit 1
fi

# AWS Budgets tag-filter format: `user:<TagKey>$<TagValue>` for user-defined
# (cost-allocation) tags. The `\$` keeps `$` literal in bash; ${PROJECT_TAG}
# still expands.
TAG_FILTER="user:project\$${PROJECT_TAG}"

create_budget() {
    local name="$1"
    local amount="$2"

    if aws budgets describe-budget --account-id "$AWS_ACCOUNT_ID" \
            --budget-name "$name" >/dev/null 2>&1; then
        echo "  [exists] ${name} -- skipping (delete manually to recreate)"
        return 0
    fi

    echo "  [create] ${name} (\$${amount}/month forecasted)"

    local budget_json notifications_json
    budget_json=$(cat <<EOF
{
    "BudgetName": "${name}",
    "BudgetLimit": {"Amount": "${amount}", "Unit": "USD"},
    "TimeUnit": "MONTHLY",
    "BudgetType": "COST",
    "CostFilters": {
        "TagKeyValue": ["${TAG_FILTER}"]
    }
}
EOF
)
    notifications_json=$(cat <<EOF
[
    {
        "Notification": {
            "NotificationType": "FORECASTED",
            "ComparisonOperator": "GREATER_THAN",
            "Threshold": 100,
            "ThresholdType": "PERCENTAGE",
            "NotificationState": "ALARM"
        },
        "Subscribers": [
            {"SubscriptionType": "EMAIL", "Address": "${ALERT_EMAIL}"}
        ]
    }
]
EOF
)

    aws budgets create-budget --account-id "$AWS_ACCOUNT_ID" \
        --budget "$budget_json" \
        --notifications-with-subscribers "$notifications_json" \
        --resource-tags \
            "Key=project,Value=${PROJECT_TAG}" \
            "Key=env,Value=${ENVIRONMENT}" \
            "Key=owner,Value=${OWNER_TAG}"

    echo "  [done]   ${name}"
}

echo "Creating budget alerts for project=${PROJECT_TAG} (account ${AWS_ACCOUNT_ID})"
echo "Reminder: activate the 'project' cost-allocation tag in the Billing console."
echo

create_budget "olist-warning"   "5"
create_budget "olist-attention" "20"
create_budget "olist-stop"      "50"

echo
echo "All three budgets ready. Alerts will arrive at ${ALERT_EMAIL}."
