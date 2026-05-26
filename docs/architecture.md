# Architecture overview

This document describes the architecture of olist-bi-pipeline: the data flow, the AWS resources involved, the import rules of the Python source layout, and the honest list of things this project does **differently** from how a production system would do them.

For the *why* behind any specific choice, see the corresponding ADR in [`docs/adr/`](adr/).

## High-level data flow

```
                           ┌────────────────────────────────────┐
                           │ Kaggle: brazilian-ecommerce        │
                           │ (9 CSV tables, ~150 MB)            │
                           └─────────────────┬──────────────────┘
                                             │
                                             │ kaggle CLI (one-off, manual)
                                             ▼
                  ┌──────────────────────────────────────────────────┐
                  │             src/olist_pipeline/ingestion/        │
                  │ Downloads zip, unpacks, uploads to S3 raw layer  │
                  │ Tags every object: project=olist-pipeline …      │
                  └─────────────────────────────┬────────────────────┘
                                                │ S3 PUT
                                                ▼
        ┌────────────────────────────────────────────────────────────────────┐
        │ S3 — raw/                                                          │
        │ olist-raw-mfern-xx                                                 │
        │ ├── source=orders/ingested_at=2026-05-08/orders.csv.gz             │
        │ ├── source=order_items/ingested_at=2026-05-08/order_items.csv.gz   │
        │ └── …  (9 tables, partitioned by source and ingest date, append-only) │
        └─────────────────────────────┬──────────────────────────────────────┘
                                      │
                                      │ Glue Crawler "olist-raw-crawler" (ON_DEMAND)
                                      ▼
                       ┌────────────────────────────────┐
                       │ AWS Glue Data Catalog          │
                       │ database: olist_dev            │
                       │ tables: raw_<source_name>      │
                       └─────────────────┬──────────────┘
                                         │
                                         │ Glue Job (PySpark): transform_to_staging
                                         │ (one job per source table, parallelisable)
                                         ▼
        ┌────────────────────────────────────────────────────────────────────┐
        │ S3 — staging/                                                      │
        │ olist-staging-mfern-xx                                             │
        │ ├── source=orders/ (Parquet+Snappy, typed, deduplicated)           │
        │ ├── source=order_items/                                            │
        │ └── …                                                              │
        │ + _SUCCESS marker file written by each job on completion           │
        └─────────────────────────────┬──────────────────────────────────────┘
                                      │
                                      │ S3 Event on _SUCCESS triggers Lambda
                                      ▼
                       ┌────────────────────────────────┐
                       │ Lambda: olist-quality-check    │
                       │ Validates staging against      │
                       │ explicit quality rules.        │
                       │ Writes report to               │
                       │ s3://...staging/_quality/      │
                       └─────────────────┬──────────────┘
                                         │
                                         │ if quality OK, invoke next Glue Job
                                         ▼
                  ┌──────────────────────────────────────────────────┐
                  │ Glue Job (PySpark): build_curated                │
                  │ Joins staging tables into:                       │
                  │  fact_orders, fact_order_items                   │
                  │  dim_customers, dim_products, dim_sellers,       │
                  │  dim_geolocation, dim_date, dim_currency         │
                  │ Enriches with FX rates from Frankfurter API      │
                  └─────────────────────────────┬────────────────────┘
                                                │
                                                ▼
        ┌────────────────────────────────────────────────────────────────────┐
        │ S3 — curated/                                                      │
        │ olist-curated-mfern-xx                                             │
        │ ├── fact_orders/year=2017/month=05/...parquet                       │
        │ ├── fact_order_items/year=2017/month=05/...parquet                  │
        │ ├── dim_customers/...parquet (unpartitioned, small)                 │
        │ └── …  (Parquet+Snappy, partitioned by year/month for facts)        │
        └─────────────────────────────┬──────────────────────────────────────┘
                                      │
                                      │ Glue Crawler "olist-curated-crawler" (ON_DEMAND)
                                      ▼
                       ┌────────────────────────────────┐
                       │ AWS Glue Data Catalog          │
                       │ tables: fact_*, dim_*          │
                       └─────────────────┬──────────────┘
                                         │
                                         ▼
                       ┌────────────────────────────────┐
                       │ AWS Athena                     │
                       │ workgroup: olist-dev           │
                       │ result location: olist-athena- │
                       │   results-mfern-xx (30-day TTL)│
                       └─────────────────┬──────────────┘
                                         │
                                         │ Simba Athena ODBC driver
                                         ▼
                       ┌────────────────────────────────┐
                       │ Power BI Desktop               │
                       │ olist_dashboard.pbix           │
                       │ (model authored via MCP from   │
                       │  Claude Code; visuals manual)  │
                       └─────────────────┬──────────────┘
                                         │
                                         │ Publish to web
                                         ▼
                       ┌────────────────────────────────┐
                       │ Power BI Service (free tier)   │
                       │ public dashboard URL           │
                       └────────────────────────────────┘

                ──────────────────────────────────────────────
                Orchestration overlay (EventBridge + Lambda)
                ──────────────────────────────────────────────

   EventBridge scheduled rule: olist-daily-trigger (ON_DEMAND initially)
              │
              ▼
   Lambda: olist-pipeline-start
              │ (calls Glue Crawler raw, then dispatches staging Jobs)
              ▼
   ── S3 events on _SUCCESS markers chain the rest ──
```

## Source code layout (`src/olist_pipeline/`)

Five layers, each with a single concern, enforced by `pre_create_layout_check.sh`:

```
src/olist_pipeline/
├── core/             Cross-cutting: config, logging, AWS client factories, types
├── ingestion/        Kaggle download, raw upload to S3
├── transformation/   Glue Job entry points + PySpark transformations + Athena DDL
├── quality/          Validation rules, quarantine writers, quality report builders
└── orchestration/    Lambda handlers, EventBridge rule definitions
```

### Import rules (enforced by review, not hooks)

| Layer            | May import from                                |
| ---------------- | ---------------------------------------------- |
| `core/`          | stdlib + boto3 + pydantic + structlog only     |
| `ingestion/`     | `core/` only                                   |
| `transformation/`| `core/` only                                   |
| `quality/`       | `core/`, `transformation/` (read-only helpers) |
| `orchestration/` | anything (it is the glue layer)                |

These rules are not enforced by tooling for this project (they would be in production). They are reviewed by reading import statements before merging.

## Tagging convention

Every AWS resource that supports tagging carries:

| Tag       | Value                |
| --------- | -------------------- |
| `project` | `olist-pipeline`     |
| `env`     | `dev`                |
| `owner`   | `marianela`          |

This is enforced by the `core.aws.tag_dict()` helper, used by every provisioning helper. See `.claude/skills/aws-cost-discipline/SKILL.md` for rationale.

## Naming conventions (Tier B decision)

| Concern                      | Convention                          | Example                          |
| ---------------------------- | ----------------------------------- | -------------------------------- |
| S3 buckets                   | `olist-<purpose>-<initials>-<suffix>` | `olist-raw-mfern-01`           |
| Glue database                | `olist_<env>`                       | `olist_dev`                      |
| Glue jobs                    | `olist-<step>-<source>`             | `olist-staging-orders`           |
| Lambda functions             | `olist-<role>`                      | `olist-quality-check`            |
| EventBridge rules            | `olist-<trigger-purpose>`           | `olist-daily-trigger`            |
| IAM roles                    | `olist-<service>-role`              | `olist-glue-role`                |
| Athena workgroup             | `olist-<env>`                       | `olist-dev`                      |
| Curated tables               | `fact_*` / `dim_*`                  | `fact_orders`, `dim_customers`   |
| Staging tables               | `staging_<source>`                  | `staging_orders`                 |
| Raw tables (Glue Catalog)    | `raw_source_<source>`               | `raw_source_orders` (see note below) |

Snake_case for tables, kebab-case for AWS resource names (matches AWS ecosystem conventions).

**Note on raw Catalog tables.** Glue Crawler derives table names from the deepest non-partition path segment. Our raw layout uses `source=<table>/ingested_at=<date>/` (Hive-style partitioning), so the Crawler sees `source=<table>` as the table-level prefix and names the table `source_<table>` after sanitising the `=` sign. Combined with `--table-prefix raw_` we get `raw_source_orders` etc., not the cleaner `raw_orders` that an earlier draft of this doc anticipated. We accept the verbose names rather than pre-creating tables manually (see open question below).

**Note on raw Catalog columns.** Glue's auto-classifier (built-in and custom CSV with `ContainsHeader=PRESENT`) does not reliably detect the header row on the Olist gzipped CSVs (mixed-quote rows defeat the matcher), so raw Catalog tables show columns as `col0, col1, ...`. This is acceptable because the staging Glue Job reads raw via `spark.read.csv(header=True)` directly and does NOT rely on Catalog column metadata — it only uses the Catalog for partition discovery, which the Crawler does correctly (`ingested_at` is the partition key). If ad-hoc Athena queries over raw ever become useful, the fix is to pre-create the nine raw tables with explicit `aws glue create-table` calls and configure the Crawler to update partitions only.

## Athena workgroup configuration (Tier B decision)

ADR-0001 decides *that* we use Athena over Redshift. This section records *how* the workgroup is configured — operational settings, not a reversible-with-effort architectural commitment, so Tier B rather than a new ADR. Provisioned by [`infra/create-athena-workgroup.sh`](../infra/create-athena-workgroup.sh).

| Setting                          | Value                                   | Why                                                                 |
| -------------------------------- | --------------------------------------- | ------------------------------------------------------------------- |
| Workgroup name                   | `olist-dev`                             | Matches the `olist-<env>` naming convention above.                  |
| Result location                  | `s3://olist-athena-results-*/`          | Dedicated bucket; one CSV + metadata file per query.                |
| Result encryption                | `SSE_S3`                                | Matches bucket-level default encryption.                            |
| `BytesScannedCutoffPerQuery`     | 1 GiB (1073741824 bytes)                | Hard guardrail: any query scanning more is cancelled before billing. A `SELECT *` over an unpartitioned table is the failure mode this prevents. |
| `EnforceWorkGroupConfiguration`  | `true`                                  | Clients (Power BI, console, CLI) cannot override the cap or redirect results to another bucket. |
| `PublishCloudWatchMetricsEnabled`| `false`                                 | CloudWatch custom metrics cost ~$0.30/metric/month above free tier. Off for portfolio; flip on if query observability is needed. |

Cost: $0/month for the workgroup itself. Query cost is $5/TB scanned, first 1 TB/month on the free tier. Result CSVs are a few KB each — negligible storage.

## Staging table registration (Tier B decision)

Staging (and later curated) tables are registered with explicit `CREATE EXTERNAL TABLE` DDL run through Athena — **not** discovered by a Glue Crawler. Provisioned by [`infra/create-staging-tables.sh`](../infra/create-staging-tables.sh).

**Why not a Crawler here.** Crawlers earn their keep on the raw layer, where schema-on-read CSVs need inference. Staging is the opposite: the Glue Job writes typed Parquet with an embedded schema, so there is nothing to *infer* — only to *declare*. Declaring it explicitly is $0 (no ON_DEMAND resource to run and remember), makes the DDL the single source of truth for the table shape, and removes the `col0..col7`-style surprises the raw Crawler produced.

**Partition discovery via projection, not `MSCK REPAIR`.** Staging tables are partitioned by `year`/`month`. Rather than re-registering partitions after every Glue Job run (`MSCK REPAIR TABLE` or `ALTER TABLE ADD PARTITION`), the tables use [partition projection](https://docs.aws.amazon.com/athena/latest/ug/partition-projection.html): the DDL declares the partition ranges (`year` 2016–2030, `month` 1–12) and a `storage.location.template`, and Athena computes the partition paths on the fly. Zero maintenance, no post-run step that can be forgotten.

**Partition-value format gotcha.** Spark writes integer partition columns *without* zero-padding (`month=9`, `month=10` — not `month=09`). The projection declares no `digits` property so Athena matches the bare integers. If a query returns 0 rows while S3 clearly holds data, suspect a padding mismatch first: check the real paths with `aws s3 ls s3://<staging-bucket>/source=orders/` and add `'projection.month.digits'='2'` if they turn out to be padded.

## Production deltas — what this project does differently from a real system

This project is portfolio. Several decisions trade rigour for clarity and cost. The honest list:

### Infrastructure as Code

**This project**: bash scripts under `infra/` + JSON files for IAM policies. One-off, reproducible-ish.
**Production**: Terraform or AWS CDK. Every resource defined in code, applied via CI/CD, drift detection enabled. Provides exact reproducibility, audit trail, environment promotion.
**Why we skip**: Terraform adds 4–6 hours of setup that doesn't show up in the dashboard. Bash is good enough for a single-engineer single-env portfolio. **An ADR could be written if the project grows past three environments.**

### IAM scoping

**This project**: AWS-managed broad policies (`AmazonS3FullAccess`, etc.) attached to one IAM user.
**Production**: custom policies that allow only specific actions on resources tagged `project=olist-pipeline`, with explicit `Deny` statements blocking everything else; separate roles per service (Glue, Lambda) with minimum-necessary permissions; access reviews quarterly.
**Why we skip**: blast radius is the dev's own account, not company prod. Disclaimer is in `docs/setup/02-aws-account.md`.

### Orchestration

**This project**: EventBridge cron + Lambdas + S3 events. See ADR-0003.
**Production**: Step Functions for ≤ 30 steps, MWAA / Airflow for larger DAGs. Visual run history, retries-from-failed-step, parallel fan-out / fan-in.
**Why we skip**: 5 steps fit on EventBridge fine. ADR-0003 names Step Functions as the explicit graduation path.

### Data quality

**This project**: custom Python validators in `src/olist_pipeline/quality/`. Specific rules per table, hand-written.
**Production**: **Great Expectations** or **Soda Core** with declarative expectation suites; quality results stored in a results store with history; alerting integrated into the orchestrator.
**Why we skip**: 5 quality rules are easier to read as Python; introducing Great Expectations adds a 200-page learning curve. **Open question**: revisit once we have ≥ 15 quality rules.

### Lakehouse table format

**This project**: plain Parquet. No ACID, no time travel.
**Production at this scale (>100 GB)**: Apache Iceberg or Delta Lake on top of S3, with Athena Iceberg support enabled. Schema evolution, snapshot isolation, branching for experiments.
**Why we skip**: <50 MB curated, no concurrent writers, no schema evolution scenarios.

### Refresh strategy

**This project**: incremental with high-watermark pattern (Phase A, ADR-0006), evolving to Iceberg MERGE (Phase B, ADR-0007).
**Production**: same approach at larger scale; the migration to Iceberg is exactly what production warehouses are doing in 2026.
**Note**: this was originally listed as a "Production delta" in the early drafts of this document. It was promoted to in-scope because demonstrating incremental loads is one of the strongest signals for senior data roles and the cost of implementation is moderate. See `docs/INCREMENTAL_LOADS.md` for the operational guide.

### Power BI deployment

**This project**: Power BI Desktop authoring + "Publish to web" (free tier). Public URL.
**Production**: Power BI Service Pro/Premium with row-level security, scheduled refresh against the gateway, version-controlled `.pbip` deployed via Power BI deployment pipelines.
**Why we skip**: free tier is enough to demonstrate the dashboard publicly; Pro starts at ~$10/user/month.

### Observability

**This project**: structured CloudWatch logs, manual eyeballing.
**Production**: distributed tracing (X-Ray), centralised log aggregation (CloudWatch Logs Insights or Datadog), per-pipeline-run metrics (rows in/out, error counts, processing time), alerting on SLO violations.
**Why we skip**: scope creep for portfolio. We use structured logs in JSON so a future graduation to a real observability stack is a matter of pointing a forwarder at the log group.

### Secret management

**This project**: secrets in `.env` (gitignored), loaded with `python-dotenv`.
**Production**: AWS Secrets Manager or Parameter Store SecureString, rotated automatically, accessed by IAM role rather than long-lived access keys.
**Why we skip**: `.env` is fine for a single-developer setup. The `.env.example` documents what would otherwise live in Secrets Manager.

## Open architectural questions

Things we know we don't know yet. Promoted to here when first encountered.

- ~~**When does an incremental refresh strategy become necessary?**~~ — **Resolved 2026-05-08**: incremental is in-scope from week 5. See ADR-0006 and `docs/INCREMENTAL_LOADS.md`.
- **Should we add a `quarantine/` bucket for rejected rows?** Currently rejects are logged and dropped. Trigger: first time a quality rule rejects more than 1% of input.
- **Should we generate the dashboard refresh as part of the pipeline?** Currently manual via Power BI Desktop's Refresh button, optionally via the Power BI REST API from a Lambda. Trigger: when the pipeline becomes daily and manual refresh becomes annoying.
- **Late-arriving SLA**: how old can a "late-arriving" row be before we reject it? Currently no limit. Trigger: first time we see a row older than 1 year arriving.

These are not blocking — they are flagged so we recognise them when they bite.
