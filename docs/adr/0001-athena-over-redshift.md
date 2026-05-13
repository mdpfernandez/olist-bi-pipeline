# ADR-0001 — Athena over Redshift

- **Status**: Accepted
- **Date**: 2026-05-08
- **Tags**: aws, query-engine, cost, lakehouse

## Context

This project needs a SQL query engine that sits between the curated layer of S3 and Power BI Desktop. The engine has to:

1. Run analytical SQL over Parquet files in S3 (`fact_orders`, `dim_customers`, etc.).
2. Cost zero — or close to zero — when nobody is querying. Portfolio runs intermittently; an always-on cluster wastes the budget.
3. Integrate with Power BI Desktop via ODBC.
4. Be a name that a Madrid recruiter recognises immediately.

The Olist dataset is small (~150 MB raw, ~50 MB Parquet curated). Query loads will be batches of dashboard refreshes during development, plus occasional ad-hoc exploration. There is no real-time component, no concurrent users beyond Marianela herself.

The choice of query engine commits the rest of the stack: it determines how the curated tables are partitioned, what file format wins, what driver Power BI uses, and what the cost shape of "running the dashboard" looks like.

## Pre-decision review

- **Failure mode in 6 months**: a single curated query exceeds Athena's 30-minute hard timeout. Most likely trigger: a poorly-written cross-join while debugging, or accidentally scanning the raw CSV layer instead of curated Parquet.
- **Prior art and divergence**: virtually every "AWS data lake portfolio" project uses Athena for exactly this shape. AWS Solutions Architect labs, freeCodeCamp tutorials, Pluralsight portfolio courses all converge on it. We are not diverging.
- **Cost of reversal**: days. The curated layer is Parquet on S3; replacing Athena with Redshift Serverless or Snowflake means re-pointing the Power BI connection and possibly adjusting partition layout, but the data does not move.
- **Early warning signal**: any single query that scans more than 1 GB or runs longer than 30 seconds. That is the first symptom that Athena is being misused or that the dataset has outgrown it.

## Decision

We will use **AWS Athena** as the query engine that serves the curated layer to Power BI Desktop and to ad-hoc SQL exploration. Athena is configured against the AWS Glue Data Catalog, where Glue Crawlers register the curated Parquet files as external tables.

Specifically:

- One Athena workgroup `olist-dev` with **query result caching enabled** (24-hour reuse) and **per-query data scan limit of 1 GB** as a guardrail.
- Athena query results land in `s3://olist-athena-results-mfern-xx/` with a 30-day lifecycle rule to expire them.
- Power BI connects via the official **Simba Athena ODBC driver**, in DirectQuery mode for live data and Import mode for the report's static dimension tables.

## Consequences

### Positive

- **Zero idle cost.** Athena bills per TB scanned. Nobody querying = $0.
- **Free tier-friendly.** First 1 TB scanned per month is free for 12 months. Realistic monthly usage on this dataset will not approach that limit.
- **Native Glue integration.** Glue Crawlers populate the catalog; Athena queries it. No manual schema management.
- **Standard SQL (Trino).** Recruiters and downstream consumers don't need to learn a proprietary dialect.
- **Recognised stack.** "Athena + Glue + S3" is what a job description for "AWS Data Engineer" in Madrid expects.

### Negative

- **30-minute hard query timeout.** Queries longer than this fail outright. Acceptable at portfolio scale; not for production over hundreds of GB of joins without careful partitioning.
- **No incremental indexes.** Athena does not have indexes the way Redshift or Postgres do. Performance is determined by partitioning, file format, and column projection. Curated tables MUST be partitioned (by year, then by month) and stored as Parquet — those are non-negotiable.
- **ODBC driver friction.** The Simba Athena driver works but has a Windows-installer setup, a workgroup name to specify, and an S3 results bucket to configure. This is documented in `docs/setup/04-power-bi-setup.md` but is the single fiddliest piece of the integration.
- **No materialised views in the way Redshift has them.** Athena has views (logical) but if expensive aggregations need pre-computation, we have to write them as physical curated tables. For this project, that's fine — the curated layer is exactly that.

### Neutral / open questions

- Athena's query result reuse cache is opt-in per query. Need to remember to enable it in the workgroup settings.
- Power BI's DirectQuery against Athena has a per-query latency overhead of 1–3 seconds (cold). For interactive dashboards this can feel slow. Mitigation: aggregated facts in Power BI's Import mode, with detail in DirectQuery — a common hybrid pattern.

## Alternatives considered

### Redshift Serverless

Redshift Serverless was the strongest contender. It is genuinely serverless (no cluster to manage) and gives you ANSI SQL, materialised views, and predictable performance. **Rejected because** the billing unit is RPU-hour ($0.36/RPU-hour, 8 RPU minimum), with a baseline charge of around $0.36/hour any time a query runs. Even with auto-pause after 60 seconds idle, the math at portfolio volumes works out to several dollars per development day, versus cents on Athena. The benefit (slightly better SQL ergonomics, materialised views) does not justify the cost shape.

### Redshift provisioned

Smallest dc2.large node is roughly $0.25/hour, $180/month if left running. Trivially over budget. Rejected.

### Snowflake

Free 30-day trial with $400 of credits is generous and the platform is excellent. **Rejected because** the trial expires; post-trial, pay-as-you-go starts at ~$2/credit and a single warehouse on standby costs credits. Also, the Madrid market for BI Lead skews "AWS shop" or "Azure shop" — Snowflake is more relevant in larger companies. We wanted a stack that maps directly to job descriptions, and Athena does. A short Snowflake-vs-Athena comparison in a follow-up README is on the optional list.

### Self-hosted Trino on EC2

Trino is the engine Athena is built on. **Rejected because** running it ourselves means managing an EC2 instance, the Trino coordinator, the worker nodes, and storage — the operational burden contradicts ground rule 4 ("single-engineer bias"). Athena gives us Trino without the ops.

### DuckDB

Tempting for raw simplicity. **Rejected because** the project's premise is "demonstrate AWS architecture". DuckDB does not produce that demonstration. It would be a great choice for a different portfolio piece focused on "modern lightweight analytics".

## References

- [Amazon Athena pricing](https://aws.amazon.com/athena/pricing/)
- [Amazon Redshift Serverless pricing](https://aws.amazon.com/redshift/pricing/)
- [Athena workgroups and query result caching](https://docs.aws.amazon.com/athena/latest/ug/workgroups.html)
- [Simba Athena JDBC/ODBC driver](https://docs.aws.amazon.com/athena/latest/ug/connect-with-odbc.html)
- Related: ADR-0002 (medallion architecture — defines what Athena queries), ADR-0003 (orchestration — Lambdas trigger Glue → Athena registers tables → Power BI consumes).
