# ADR-0003 — EventBridge + Lambda for orchestration

- **Status**: Accepted
- **Date**: 2026-05-08
- **Tags**: aws, orchestration, eventbridge, lambda, cost

## Context

The pipeline has a few well-defined steps that have to happen in order:

1. Download Olist data from Kaggle (manual or scheduled).
2. Upload to S3 raw layer.
3. Run Glue Crawler over raw to register the schema.
4. Run Glue Job(s) to transform raw → staging.
5. Run quality checks on staging.
6. Run Glue Job(s) to build curated star schema.
7. Run Glue Crawler over curated.
8. (Optional) Refresh Power BI dataset via the REST API.

The steps form a loose DAG: most are sequential; a few staging tables can be transformed in parallel before they fan in to curated.

We need an orchestrator that triggers each step when its predecessor finishes, retries on transient errors, alerts on hard failures, and **costs nothing when the pipeline is not running**. The pipeline runs maybe once a day during development, maybe weekly in steady state.

## Pre-decision review

- **Failure mode in 6 months**: a Lambda fails silently (e.g., its Glue Job invocation returns success while the underlying job actually failed), the pipeline marches on, and the dashboard shows stale curated data without anybody noticing. Mitigation: every Lambda has explicit failure handling and writes its run status to CloudWatch Logs with a structured "FAILED"/"OK" line; we add a CloudWatch Logs metric filter that triggers an SNS email on "FAILED".
- **Prior art and divergence**: most "AWS data engineer" portfolio projects either use Step Functions or skip orchestration. Production-scale shops use Airflow / Dagster / Prefect. Our choice (EventBridge + Lambda) is the cheapest, simplest tier — appropriate for this scale, but we acknowledge it as a deliberate Phase-1 simplification.
- **Cost of reversal**: days. Replacing this orchestration with Step Functions means writing a state machine definition (~100 lines of JSON), wiring the same Lambdas as task states, and rewriting the EventBridge rules as a single Step Functions trigger. The Lambdas themselves do not change.
- **Early warning signal**: any of these three smells. (a) A Lambda's reserved concurrency keeps maxing out. (b) The chain of triggers has more than 4–5 hops — beyond that, debugging cascade failures becomes painful. (c) We need to retry an entire pipeline run from a specific step — Lambda chains do not support that natively, Step Functions do.

## Decision

We will orchestrate the pipeline with **AWS EventBridge** as the scheduler and **AWS Lambda** functions as the task units, connected by **S3 event notifications** for step-to-step triggering.

Concrete structure:

- One **EventBridge scheduled rule** (`olist-daily-trigger`) firing the entry-point Lambda. Initially `ON_DEMAND`; promoted to a daily cron when the pipeline is stable.
- **Lambdas as orchestration glue, not as compute**. Each Lambda is a thin function (≤ 100 lines) that calls a downstream service (Glue API, Athena API) and returns. The actual compute work happens in the Glue Jobs.
- **S3 event notifications** on `olist-staging-mfern-xx` trigger the next-step Lambdas when a transformation completes its writes (using a marker file `_SUCCESS` written by the Glue Job).
- Lambdas have **reserved concurrency = 2** during development (limits blast radius if a recursive trigger ever happens).
- **Retries**: Lambda's default async retry policy (2 retries, exponential) for transient errors; permanent errors (validation, schema mismatch) raise immediately with no retry.
- **Failure surface**: every Lambda logs structured JSON; a CloudWatch Logs metric filter for `level=ERROR` feeds an SNS topic that emails Marianela.

## Consequences

### Positive

- **Zero idle cost.** EventBridge default rules and Lambda free tier mean the orchestration layer costs effectively $0 at portfolio volumes.
- **Simple Python.** Each Lambda is 50–100 lines of straightforward Python. No new tool to learn (no Airflow DSL, no Step Functions JSON).
- **Native AWS integration.** EventBridge knows about every AWS service event natively. Glue Job state transitions, S3 PUT events, Athena query completions all surface as EventBridge events without extra infra.
- **Easy local testing.** Each Lambda's handler is a regular Python function — `pytest tests/unit/orchestration/test_run_glue_job.py` with `moto` covers it.

### Negative

- **No visual DAG.** Step Functions gives you a real-time visualisation of pipeline runs in the AWS Console. EventBridge + Lambda chains do not — you read CloudWatch Logs to follow execution. **For portfolio**, we mitigate this by keeping the chain short (≤ 5 steps) and documenting the flow as an ASCII diagram in `docs/architecture.md`.
- **Error handling is per-Lambda, not centralised.** Each Lambda has to log structured failures correctly; if one of them swallows an exception, the pipeline marches on silently. **Mitigation:** the structured-logging contract is enforced by `core/logging.py` and reviewed in code review.
- **Partial reruns are painful.** "Rerun from step 5" requires manually invoking the right Lambda with a hand-crafted input. Step Functions makes this a one-click operation. We accept this for portfolio; in production it is a reason to graduate.
- **Trigger graph is implicit.** The "Lambda A writes to S3, S3 triggers Lambda B" pattern means the topology lives partly in S3 bucket configuration, partly in EventBridge rules, partly in Lambda environment variables. **Mitigation:** `docs/architecture.md` has a diagram showing every trigger.

### Neutral / open questions

- If the pipeline grows beyond ~6 steps or starts needing parallel-fan-out / fan-in, the EventBridge + Lambda pattern stops paying its way. That is the explicit graduation trigger to Step Functions.
- We are not using Step Functions Express Workflows (cheaper, faster, but with the same cognitive overhead). Worth re-evaluating if the trigger above fires.

## Alternatives considered

### AWS Step Functions

Native AWS workflow engine. Visual DAG, automatic retries with declarative policies, partial reruns, integrates with every AWS service. **Rejected because** for ≤ 5 steps it is more ceremony than value, and the per-state-transition cost ($0.025/1000 transitions for Standard, ~free for Express) is non-zero. The real reason: Standard's billing pattern at portfolio volumes is comparable to Lambda, so the cost angle is weak; what tips it is the cognitive cost of the Amazon States Language for a 5-step pipeline that fits in a chat message.

If the project graduates beyond 5 Lambdas this is the immediate replacement. The Lambdas themselves don't change — they become Step Functions task states.

### Amazon MWAA (Managed Airflow)

Industry-grade. **Rejected immediately** because the minimum size mw1.small costs **~$400/month** even idle. That single line item exceeds the entire portfolio budget. MWAA is a Phase-3 tool for shops with multiple pipelines and engineers; not a portfolio fit.

### Self-hosted Airflow on EC2

Same DAG capability, much cheaper than MWAA — but the operational burden (running, upgrading, monitoring an Airflow instance) contradicts the single-engineer ground rule. Rejected.

### Prefect Cloud free tier

Prefect's free tier is generous (20k task runs/month) and the developer experience is excellent. **Rejected because** the project's premise is "demonstrate AWS-native architecture". Adding a non-AWS orchestrator dilutes that narrative. Prefect would be the right pick for a non-AWS portfolio piece.

### Glue Workflows

AWS Glue has its own orchestration mechanism (Workflows + Triggers) for chaining Glue Jobs and Crawlers. **Rejected because** it only orchestrates Glue resources — it cannot trigger Lambdas, run Athena queries, or call external APIs (e.g., Power BI refresh). EventBridge is strictly more powerful at the same cost.

### Cron on a personal machine

Marianela's laptop runs a cron that calls `aws glue start-job-run` etc. **Rejected because** it does not work when the laptop is off, does not demonstrate cloud-native orchestration to a recruiter, and provides zero observability.

## References

- [EventBridge pricing](https://aws.amazon.com/eventbridge/pricing/) — custom events $1/1M
- [Lambda pricing](https://aws.amazon.com/lambda/pricing/) — free tier 1M invocations/month forever
- [Step Functions Standard vs Express](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-standard-vs-express.html)
- [MWAA pricing](https://aws.amazon.com/managed-workflows-for-apache-airflow/pricing/) — for the "rejected" argument
- Related: ADR-0001 (Athena), ADR-0002 (medallion).
