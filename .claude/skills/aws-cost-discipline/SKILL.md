---
name: aws-cost-discipline
description: CONSULT THIS SKILL BEFORE provisioning any AWS resource (S3 bucket, Glue Crawler, Glue Job, Lambda function, EventBridge rule, Athena workgroup, IAM role, lifecycle rule). Required reading whenever the user asks "should I create X in AWS", whenever a script under infra/ is being written, whenever an aws CLI create-* / put-* / run-* command is about to be executed, or whenever the user mentions cost, budget, or "why is this so expensive". Defines the 3 mandatory tags, the budget alert ladder, the per-service cost shapes, and the Friday-teardown rule. Companion skill that prevents the most common portfolio cost spiral: the forgotten resource left running for a month.
---

# AWS Cost Discipline — olist-bi-pipeline

## Why this skill exists

The classic portfolio cost spiral: you provision a Glue Crawler on Tuesday for testing, forget it has a schedule, and on the 1st of next month you have a $40 surprise on the AWS invoice. Or worse: a Lambda with a misconfigured loop that fires itself, runs for a weekend, and clocks $200 before you notice.

This skill exists to make those mistakes **structurally hard to commit**. Not by hoping you remember — by enforcing a small set of rules every time you touch infra.

## The 3 mandatory tags

Every AWS resource that supports tagging carries these three. **No exceptions.**

| Tag       | Value                       | Why                                                |
| --------- | --------------------------- | -------------------------------------------------- |
| `project` | `olist-pipeline`            | Lets you filter cost reports to this project only  |
| `env`     | `dev`                       | (`dev` is the only env in portfolio; here for habit) |
| `owner`   | `marianela`                 | If anyone else uses your account, this is yours    |

Why these three and not the six XENAI uses: portfolio is single-tenant, single-engineer, single-environment. The XENAI tags discriminate across many sources, agents, and prompts. You discriminate across "is this mine and is it the portfolio project". Three tags is enough; six is ceremony.

### How to apply tags from the CLI

Most `aws ... create-*` commands accept `--tags`:

```bash
# S3 bucket
aws s3api put-bucket-tagging --bucket olist-raw-mfern \
    --tagging 'TagSet=[
        {Key=project,Value=olist-pipeline},
        {Key=env,Value=dev},
        {Key=owner,Value=marianela}
    ]'

# Glue Job
aws glue create-job \
    --name olist-staging-transform \
    --role arn:aws:iam::ACCOUNT:role/olist-glue-role \
    --command '{"Name":"glueetl","ScriptLocation":"s3://...","PythonVersion":"3"}' \
    --tags '{"project":"olist-pipeline","env":"dev","owner":"marianela"}'

# Lambda
aws lambda create-function \
    --function-name olist-trigger-staging \
    --runtime python3.12 \
    --role arn:aws:iam::ACCOUNT:role/olist-lambda-role \
    --handler index.handler \
    --zip-file fileb://function.zip \
    --tags 'project=olist-pipeline,env=dev,owner=marianela'
```

Note the inconsistency in tag formatting between services — that is AWS's fault, not yours. Glue takes JSON, Lambda takes `key=value,key=value`, S3 takes a `TagSet` structure. Build helpers in `src/olist_pipeline/core/aws.py` so you write the tags once and reuse.

## Budget alerts — the ladder

Set up budget alerts **before** provisioning anything else. A budget that fires at $5 catches mistakes when they are still cheap to fix.

```bash
# Run once, after the AWS account is set up:
bash infra/budgets.sh
```

The script (lives in `infra/budgets.sh`) creates **three** budgets:

| Budget   | Threshold              | What it tells you                                   |
| -------- | ---------------------- | --------------------------------------------------- |
| `olist-warning`   | $5/month forecasted    | "Something is running. Check it."                   |
| `olist-attention` | $20/month forecasted   | "Something is running too much. Check now."         |
| `olist-stop`      | $50/month forecasted   | "Stop everything until you understand the cause."   |

Each budget filters by `tag:project=olist-pipeline`, so they react only to this project, not to your overall AWS usage.

**Why three thresholds and not one:** different magnitudes mean different things. $5 is "you forgot to destroy a crawler". $50 is "something is wrong, something is looping, stop work and triage".

## Per-service cost shape — what scales how

You need to know the cost *shape* of each service so you can recognise the dangerous patterns.

### S3 — billed per GB-month + per request

- Storage: ~$0.023/GB-month for Standard. Olist dataset is < 1 GB compressed. **Negligible.**
- Requests: PUT $0.005/1k, GET $0.0004/1k. **Negligible at portfolio volumes.**
- Lifecycle rules to Glacier are NOT worth setting up for portfolio (under 1 GB the cost of the transition exceeds the savings).

**Watch out for:** versioning + frequent overwrites = cost grows silently. Disable versioning on the `raw/` and `staging/` buckets unless you have a reason.

### Athena — billed per TB scanned

- $5 per TB scanned. **First 1 TB/month is free** for 12 months on the AWS free tier.
- A typical curated query on 100 MB of partitioned Parquet scans ~10 MB. That is 0.00001 TB = $0.00005. **Effectively free.**
- A `SELECT *` on the raw CSV layer of Olist (~150 MB) scans 150 MB. Ten times. That is 0.0015 TB. Still cents.

**Watch out for:**
- `SELECT *` on a non-partitioned table forces a full table scan every time. Always partition curated tables and always select specific columns.
- `WHERE` predicates on non-partition columns don't help bytes-scanned. Predicates on partition columns DO.
- Repeated identical queries: enable result caching via Athena workgroup configuration; same query in the next 24h returns from cache for $0.

### Glue Crawler — billed per DPU-hour

- $0.44/DPU-hour, minimum 10 minutes, billed in 1-second increments.
- A crawler over 9 small CSVs takes ~1 minute on 1 DPU. That is $0.007 per run. Negligible.

**Watch out for:**
- **A crawler with a recurring schedule.** If you set `--schedule "cron(0 * * * ? *)"` to test, and forget, that is 24 runs/day × $0.007 = $0.17/day = **$5/month**. You will hit the warning budget.
- Always create crawlers with `--schedule` empty or `ON_DEMAND`. Run them manually with `aws glue start-crawler` when you need them.

### Glue Job (PySpark) — billed per DPU-hour

- $0.44/DPU-hour, minimum 1 minute, billed per second.
- A small PySpark job processing the Olist dataset on 2 DPUs (the minimum for `glueetl`) for 5 minutes is $0.073. Per run. **Cheap if you run it occasionally.**

**Watch out for:**
- **Job triggers fired by a high-frequency event.** If a Glue Job triggers on every S3 PUT to `raw/`, and you upload 100 files in a loop while debugging, that is 100 jobs × $0.073 = **$7.30**. Always test triggers with single uploads first.
- **`MaxCapacity > 2` without a reason.** Olist is 1 GB. 2 DPUs is plenty. 10 DPUs is 5× the cost for the same work.
- **Jobs that retry automatically on failure.** Default `--max-retries 0`. Otherwise a buggy job retries 3× at full cost.

### Lambda — billed per invocation + per GB-second

- $0.20/1M requests + $0.0000167/GB-second.
- A 128MB Lambda running for 1 second per invocation costs $0.0000021 per call. **You'd need 100,000 invocations to spend $0.21.**

**Watch out for:**
- **The recursive trigger.** Lambda writes to S3 → S3 event triggers same Lambda → Lambda writes to S3 → ... This has cost the internet a lot of money. **Always test the trigger graph on paper before wiring it live.** AWS gives you a default account-level concurrency limit of 1000 — set the Lambda's reserved concurrency to **2** or **5** during development to bound the blast radius.
- **A misconfigured EventBridge rule firing every minute.** `cron(* * * * ? *)` = 1440 invocations/day. Cheap with Lambda alone, but if the Lambda calls Athena which scans 100 MB each time, you get a *secondary* cost spiral. Always cron with the lowest frequency that works.

### EventBridge — practically free

- $1.00/million custom events. Default rules are free. **Negligible.**

### IAM, CloudWatch Logs — practically free

- IAM is free. CloudWatch Logs storage is $0.50/GB ingested + $0.03/GB-month stored. Set log retention on every Lambda log group to **7 days** or **14 days** unless debugging:

```bash
aws logs put-retention-policy \
    --log-group-name /aws/lambda/olist-trigger-staging \
    --retention-in-days 7
```

Without retention, logs accumulate forever and silently grow.

## Anti-patterns with $ estimates

| Anti-pattern                                                              | Estimated cost if undetected for 30 days |
| ------------------------------------------------------------------------- | ---------------------------------------- |
| Glue Crawler scheduled hourly, forgotten                                  | $5–8                                     |
| Glue Job firing on every S3 PUT in a debug loop (100 PUTs)                | $7 (one-shot)                            |
| Lambda recursively triggering itself for a weekend                        | $30–200 depending on payload             |
| Athena `SELECT *` from raw CSVs in a tight loop while debugging Power BI  | $5–15                                    |
| EC2 instance left running because "I'll come back to it tomorrow"         | $20–60 (t3.medium, 24×30)                |
| Redshift cluster left up over weekend                                     | $180+ (dc2.large minimum)                |
| Sagemaker endpoint forgotten                                              | $50–500                                  |
| CloudWatch logs without retention                                          | $1–5/month, growing                      |

**The bottom four are why `settings.json` denies the corresponding `aws ... run-instances`, `redshift create-cluster`, `rds create-db-instance`, and `sagemaker create-endpoint` commands.** If you genuinely need them, enable in `settings.local.json` for that session only.

## The Friday teardown rule

**Every Friday before stopping: run `bash infra/destroy-all.sh`.**

The script lives in `infra/destroy-all.sh` and does, in this order:
1. Stops any running Glue Crawler / Job (just in case).
2. Disables EventBridge rules (sets state to DISABLED).
3. Optionally: deletes Lambda functions (safe — they're recreated from code).
4. **Does NOT delete S3 buckets** — data is cheap to keep, expensive to lose.
5. **Does NOT delete IAM roles** — they're free.

On Monday, `bash infra/bring-up.sh` brings everything back from JSON definitions and Lambda zip files committed to the repo. The whole "down on Friday, up on Monday" cycle costs you ~5 minutes and saves you from forgotten-resource bills.

**Why not just let it run:** at portfolio volumes the *idle* cost is genuinely small ($1–3/month for everything sitting). The danger is not the idle cost — it's the *accident* cost. A misconfiguration that fires while you're not looking is what produces the surprise. Tearing down on Friday eliminates that window.

## The pre-flight checklist

Before running an `aws ... create-*` or `aws ... put-*` command, walk this list:

- [ ] Is the resource tagged `project=olist-pipeline`, `env=dev`, `owner=marianela`?
- [ ] If it has a schedule, is the schedule `ON_DEMAND` or empty? (Promote to scheduled only when you have a reason.)
- [ ] If it has a trigger, did you draw the trigger graph on paper? Is there a cycle?
- [ ] If it's a Glue Job, is `--max-retries` set to 0 or 1?
- [ ] If it's a Glue Job, is `MaxCapacity` set to the minimum (2 DPUs)?
- [ ] If it's a Lambda, is the reserved concurrency capped (2 or 5 during dev)?
- [ ] If it produces CloudWatch logs, did you set a retention policy?
- [ ] Does the budget alert ladder ($5 / $20 / $50) already exist? If not, run `infra/budgets.sh` first.
- [ ] Is the resource definition committed to the repo (in `infra/`)? If not, you can't reproduce it on Monday.

If any box is unchecked, fix it before running the command. Estimating "this'll be fine" once is what creates a $40 surprise.

## How to check what you spent

Daily check during active development:

```bash
# Cost for the current month, broken down by service, filtered to this project's tag.
aws ce get-cost-and-usage \
    --time-period "Start=$(date -u +%Y-%m-01),End=$(date -u +%Y-%m-%d)" \
    --granularity MONTHLY \
    --metrics UnblendedCost \
    --filter '{"Tags":{"Key":"project","Values":["olist-pipeline"]}}' \
    --group-by Type=DIMENSION,Key=SERVICE
```

If a service shows up that you don't recognise — investigate immediately. That is the first symptom of a cost spiral.

## The escape hatch

If the budget alert at $20 fires and you don't immediately know why:

1. **Stop work.** Don't provision more.
2. Run `bash infra/destroy-all.sh` to halt the bleed.
3. Run the cost check above to see which service is the culprit.
4. Check `aws ce get-cost-and-usage --granularity DAILY` for the same range to find when it started.
5. Cross-reference with your git log — the commit that introduced the resource is usually the answer.
6. Document the lesson in a short note under `docs/postmortems/` (create the folder when needed). One written postmortem prevents three repetitions.
