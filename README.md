# Olist BI Pipeline

End-to-end data pipeline on AWS for the Brazilian Olist e-commerce dataset (100k orders, 9 tables, 2016–2018), with a Power BI dashboard for business users.

> **Portfolio project** — Marianela Fernández, BI Lead / Data Scientist, Madrid.

[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![AWS](https://img.shields.io/badge/AWS-S3%20%7C%20Glue%20%7C%20Athena%20%7C%20Lambda-orange)](https://aws.amazon.com/)
[![Power BI](https://img.shields.io/badge/Power%20BI-Desktop-yellow)](https://powerbi.microsoft.com/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## 🎯 What this project demonstrates

- **Cloud data architecture** — medallion lakehouse on S3, schema discovery with Glue Crawler, serverless query engine with Athena.
- **ETL at scale** — distributed PySpark transformations on AWS Glue, idempotent and partitioned.
- **Incremental data loading** — high-watermark pattern with late-arriving simulation (Phase A) → Apache Iceberg MERGE (Phase B). Production-realistic refresh strategy on a static dataset.
- **Data quality** — explicit checks between layers (raw → staging → curated) with quarantine of bad rows.
- **Orchestration** — event-driven flow with EventBridge + Lambda, no always-on infrastructure.
- **Dimensional modelling** — star schema for analytics, optimised for Power BI consumption.
- **DAX & visualisation** — executive dashboard with cohort analysis, RFM segmentation, geographical breakdown.
- **Engineering discipline** — typed Python (`pyright`), linted (`ruff`), tested (`pytest`), reproducible from zero (`uv`).

## 📊 Live dashboard

👉 **[Open the dashboard (Publish to web)](#)** &nbsp;·&nbsp; *link added once published*

### Snapshots

| Executive Overview | Cohort Retention | Geographical Sales |
|---|---|---|
| ![Executive overview](docs/screenshots/01-executive-overview.png) | ![Cohort retention](docs/screenshots/02-cohort-retention.png) | ![Geographical sales](docs/screenshots/03-geographical-sales.png) |

## 🏗️ Architecture

```
┌──────────────┐
│ Kaggle Olist │
│  (9 CSVs)    │
└──────┬───────┘
       │ Python ingestion (manual or scheduled)
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                            AWS S3                                   │
│  ┌────────────┐    ┌────────────┐    ┌──────────────────────────┐   │
│  │   raw/     │ → │  staging/  │ →  │       curated/            │   │
│  │ (CSV, by   │   │ (Parquet,  │    │  (Parquet, star schema:   │   │
│  │  source &  │   │  cleaned,  │    │   fact_orders, dim_*,      │   │
│  │  ingest_dt)│   │  typed)    │    │   partitioned by year)    │   │
│  └────────────┘    └────────────┘    └──────────────────────────┘   │
└──────┬─────────────────┬─────────────────┬──────────────────────────┘
       │                 │                 │
       ▼                 ▼                 ▼
  Glue Crawler      Glue Job (PySpark)   Athena queries
       │              + quality checks      ▲
       │                                    │
       └────────────────────────────────────┘
                  │
                  ▼
          ┌───────────────┐
          │  EventBridge  │   ← scheduled rule fires the pipeline
          │   + Lambda    │   ← Lambda triggers the next step on S3 event
          └───────────────┘
                  │
                  ▼
          ┌───────────────┐
          │  Power BI     │  ← Athena ODBC connector, DirectQuery / Import
          └───────────────┘
```

See [`docs/architecture.md`](docs/architecture.md) for the detailed diagram and rationale, and [`docs/adr/`](docs/adr/) for the architectural decision records.

## 🧱 Tech stack

| Layer            | Technology                                    |
| ---------------- | --------------------------------------------- |
| Storage          | AWS S3 (medallion: raw / staging / curated)   |
| Schema discovery | AWS Glue Crawler                              |
| Transformation   | AWS Glue Jobs (PySpark)                       |
| Query engine     | AWS Athena (Trino-based, serverless)          |
| Orchestration    | AWS EventBridge + AWS Lambda                  |
| Visualisation    | Power BI Desktop + publish-to-web             |
| Model authoring  | Power BI Modeling MCP (Microsoft, public preview) — DAX & semantic model from Claude Code |
| Language         | Python 3.12                                   |
| Tooling          | uv · ruff · pyright · pytest · pre-commit     |
| Dataset          | [Brazilian Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) |

## 📁 Repository layout

```
.
├── .claude/             Claude Code configuration (hooks, commands, skills)
├── docs/                ADRs, architecture, setup guides, screenshots
├── src/olist_pipeline/  Python source — 5 layers (core, ingestion, transformation, quality, orchestration)
├── infra/               Bash scripts + JSON policies for AWS provisioning
├── notebooks/           Exploratory notebooks (not production)
├── powerbi/             .pbix file + star schema documentation
└── tests/               unit · integration · fixtures
```

## 🚀 Quick start

> Detailed step-by-step setup (including AWS account, CLI, and Power BI Desktop installation) lives in [`docs/setup/`](docs/setup/). Read those if anything below doesn't work.

```bash
# 1. Clone and install Python deps
git clone https://github.com/<you>/olist-bi-pipeline.git
cd olist-bi-pipeline
uv sync

# 2. Configure environment
cp .env.example .env
# fill in AWS profile, bucket names, Kaggle creds (see docs/setup/03-local-environment.md)

# 3. Provision AWS resources (one-off)
bash infra/budgets.sh                    # budget alerts at $5 / $20 / $50
bash infra/create-buckets.sh             # raw, staging, curated S3 buckets

# 4. Ingest the dataset
uv run python -m olist_pipeline.ingestion.kaggle_to_s3

# 5. Run the Glue Crawler and Job
bash infra/run-crawler.sh
bash infra/run-glue-job.sh transform_staging

# 6. Open Power BI Desktop, connect to Athena, refresh
```

## 💸 Cost

Running the pipeline intermittently and **destroying everything when not actively developing** costs roughly **$5–8/month** in AWS charges. Athena queries are billed per TB scanned (free tier: 1 TB/month for 12 months); S3 storage for the full medallion dataset is under 1 GB; Lambda and EventBridge are essentially free at portfolio volumes.

The `infra/destroy-all.sh` script tears down all billable resources. Run it on Friday before stopping; bring it up again on Monday with `infra/bring-up.sh`. Details in [`.claude/skills/aws-cost-discipline/SKILL.md`](.claude/skills/aws-cost-discipline/SKILL.md).

## 📚 Architectural decisions

The "why" behind every meaningful choice lives in [`docs/adr/`](docs/adr/):

- **[ADR-0001](docs/adr/0001-athena-over-redshift.md)** — Athena over Redshift as the query engine.
- **[ADR-0002](docs/adr/0002-medallion-architecture.md)** — Medallion architecture (raw / staging / curated) on S3.
- **[ADR-0003](docs/adr/0003-eventbridge-lambda-orchestration.md)** — EventBridge + Lambda for orchestration over Step Functions or MWAA.
- **[ADR-0004](docs/adr/0004-olist-dataset.md)** — Brazilian Olist as the primary dataset.
- **[ADR-0005](docs/adr/0005-power-bi-modeling-mcp.md)** — Power BI Modeling MCP for semantic model authoring from Claude Code.
- **[ADR-0006](docs/adr/0006-incremental-ingestion-hwm.md)** — Incremental ingestion with high-watermark pattern (Phase A).
- **[ADR-0007](docs/adr/0007-migration-to-iceberg.md)** — Migration to Apache Iceberg for row-level MERGE and time travel (Phase B, Proposed).

For the operational guide of the incremental ingestion pattern (state file format, late-arriving handling, backfill procedure, recovery), see [`docs/INCREMENTAL_LOADS.md`](docs/INCREMENTAL_LOADS.md).

## 🧪 Testing

```bash
uv run pytest                # all tests
uv run pytest -m unit        # fast unit tests, no AWS
uv run pytest -m integration # integration tests with mocked AWS (moto)
```

Real AWS calls live only in scripts under `infra/`, never in tests.

## 📖 What I'd do differently in production

This is a portfolio piece — some choices made for clarity would change in a production setting. See [`docs/architecture.md#production-deltas`](docs/architecture.md) for an honest list (Terraform/CDK instead of bash, Step Functions instead of Lambda chains, Great Expectations instead of custom quality checks, dedicated Glue Data Catalog database per environment, and so on).

## 📬 Contact

- **Author:** Marianela Fernández — [LinkedIn](https://linkedin.com/in/marianela-fernandez)
- **Email:** fernandezmarianeladp@gmail.com

## 📄 License

MIT — see [LICENSE](LICENSE). Olist dataset is published under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) on Kaggle; this project uses it for non-commercial portfolio purposes only.
