# `infra/` — AWS resource provisioning

Bash scripts and JSON policies that bring the AWS resources up and down. **Not** Infrastructure as Code in the Terraform/CDK sense (see `docs/architecture.md` "Production deltas" for that conversation) — just reproducible bash that any reader can run.

## Layout

```
infra/
├── budgets.sh                     ← create the $5/$20/$50 budget alerts
├── create-buckets.sh              ← create the 4 S3 buckets with tags + encryption
├── create-glue-database.sh        ← create the Glue Data Catalog database
├── create-glue-role.sh            ← IAM role for Glue Jobs
├── create-lambda-role.sh          ← IAM role for Lambda functions
├── create-athena-workgroup.sh     ← Athena workgroup with 1 GB scan limit
├── run-crawler.sh <crawler_name>  ← invoke a Glue Crawler on demand
├── run-glue-job.sh  <job_name>    ← invoke a Glue Job on demand
├── destroy-all.sh                 ← stop crawlers/jobs, disable rules, keep buckets
├── bring-up.sh                    ← idempotent: re-run create-* scripts
├── iam-policies/                  ← JSON policies attached to roles
├── glue-jobs/                     ← PySpark scripts deployed as Glue Jobs
└── athena-views/                  ← SQL DDL for views over curated tables
```

## How to use

All scripts assume the AWS CLI is configured with the `olist-portfolio` profile
(see `docs/setup/02-aws-account.md`). Set it for the session:

```powershell
$env:AWS_PROFILE = "olist-portfolio"
```

First-time bring-up, in order:

```bash
bash infra/budgets.sh
bash infra/create-buckets.sh
bash infra/create-glue-database.sh
bash infra/create-glue-role.sh
bash infra/create-lambda-role.sh
bash infra/create-athena-workgroup.sh
```

Day-to-day operation:

```bash
# After changing a Glue Job's PySpark script:
bash infra/deploy-glue-job.sh transform_staging_orders

# Trigger a manual run:
bash infra/run-glue-job.sh olist-staging-orders

# Friday teardown:
bash infra/destroy-all.sh

# Monday bring-up:
bash infra/bring-up.sh
```

## Conventions

- Every script reads `.env` (via `set -a; source .env; set +a` at the top) so values like region, account ID, bucket names are not hardcoded.
- Every `aws ... create-*` call passes the three mandatory tags (`project`, `env`, `owner`). The skill `.claude/skills/aws-cost-discipline/SKILL.md` is the source of truth for tag values.
- Scripts are **idempotent**: running twice does not break — the second run detects "already exists" and skips. Important for `bring-up.sh`.

## What is not in `infra/`

- **Terraform / CDK / SAM** — see `docs/architecture.md` for the production-delta conversation.
- **Lambda function code** — that lives in `src/olist_pipeline/orchestration/`. The `infra/` scripts only deploy the zipped artefacts.
- **Glue Job PySpark code itself** — under `infra/glue-jobs/` is the *deployment* layer; the actual transform logic lives in `src/olist_pipeline/transformation/` and gets bundled before deploy.

> The scripts themselves are written as the project progresses. This README documents the intended layout; not every script exists yet.
