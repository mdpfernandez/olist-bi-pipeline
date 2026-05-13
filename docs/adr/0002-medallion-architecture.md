# ADR-0002 — Medallion architecture (raw / staging / curated)

- **Status**: Accepted
- **Date**: 2026-05-08
- **Tags**: aws, s3, data-lake, lakehouse, layout

## Context

Once Olist data lands in S3 it has to flow through transformations: raw CSV → cleaned Parquet → dimensional model. The project needs an explicit layer convention so that:

1. The raw upstream is preserved untouched — we can always reprocess from scratch.
2. Transformations are isolated in stages with clear inputs and outputs.
3. The dashboard only consumes a stable, well-modelled tier.
4. A reader of the repo can tell at a glance "where does query X read from".

The Databricks-popularised "medallion" naming (bronze / silver / gold) has become an industry default. There are also single-layer approaches (just `curated/`) and four-layer approaches (raw / bronze / silver / gold) common in larger lakehouses.

## Pre-decision review

- **Failure mode in 6 months**: a curated table is found wrong, the staging logic that produced it has changed twice, and the original raw is no longer reproducible because someone overwrote a partition. Mitigation: raw is **append-only with `ingested_at=YYYY-MM-DD` partitioning**, never overwritten.
- **Prior art and divergence**: every modern data platform — Databricks, Snowflake, AWS open data architectures — uses 3-tier or 4-tier lakehouse patterns. Naming varies; the structure does not. We are not diverging.
- **Cost of reversal**: hours. If we want to collapse to two layers, we drop the staging tables and re-point the curated jobs to read from raw directly. Data does not move.
- **Early warning signal**: the staging layer has more than one Glue Job writing to the same table. That is a smell that the layer's contract has fragmented.

## Decision

We will adopt a **3-tier medallion architecture** with the following names and contracts. We use the words `raw / staging / curated` rather than `bronze / silver / gold` because the literal names are clearer to a reader who has not spent a year inside Databricks marketing.

| Layer       | Bucket                       | Format    | Schema             | Partitioning              | Idempotency      |
| ----------- | ---------------------------- | --------- | ------------------ | ------------------------- | ---------------- |
| **raw**     | `olist-raw-mfern-xx`         | CSV (gz)  | source-as-is       | `source=<n>/ingested_at=<date>/` | append-only |
| **staging** | `olist-staging-mfern-xx`     | Parquet   | typed, deduped     | `source=<n>/`             | overwrite       |
| **curated** | `olist-curated-mfern-xx`     | Parquet   | star schema        | `year=YYYY/month=MM/` (facts only) | overwrite |

### Layer contracts

**raw/** is the immutable archive. Every Kaggle download is uploaded into a new `ingested_at=YYYY-MM-DD/` partition, never overwriting. Schema is whatever Olist publishes — quirks and all. **No transformations of any kind happen here.** Bucket has versioning OFF (we use partition-as-version) and a 90-day lifecycle rule to Glacier Instant Retrieval for cold storage.

**staging/** is the cleaned, typed, deduplicated representation of each source table. One Glue Job per source table reads from `raw/source=<n>/ingested_at=<latest>/` and writes to `staging/source=<n>/`. **Always full-overwrite of the staging partition** — staging is rebuildable from raw, so we don't preserve history here. Files are Parquet with Snappy compression, schema enforced via PySpark DataFrames.

**curated/** is the dimensional model the dashboard reads. Star schema: `fact_orders`, `fact_order_items`, `dim_customers`, `dim_products`, `dim_sellers`, `dim_geolocation`, `dim_date`. **Facts partitioned by `year`/`month`**; dimensions are unpartitioned (small enough). Built by a second set of Glue Jobs that read multiple staging tables and produce the dimensional outputs. Athena reads from here; Power BI reads from here.

### Why 3 buckets and not 1 with prefixes

Three separate buckets cost the same as one bucket with three prefixes. The reason to separate them: **independent lifecycle policies, independent IAM scoping, independent cost-reporting tags**, and obvious blast-radius separation. If a misconfigured Glue Job ever does a `DELETE /*` it can only kill one layer.

## Consequences

### Positive

- **Provenance.** Every curated row is traceable back to a specific raw partition.
- **Reprocessability.** "We changed the staging logic, rebuild" is one Glue Job invocation per table, not a multi-day re-ingestion from Kaggle.
- **Clear narrative for the recruiter.** The README diagram literally shows "raw → staging → curated"; the data flow matches the diagram.
- **Layer-appropriate optimisations.** Raw is CSV+gzip (cheap to store, slow to query but never queried); staging is Parquet+Snappy (fast read for transforms); curated is Parquet+Snappy with partitions (fast read for dashboards).

### Negative

- **3× storage.** We pay for raw, staging, and curated copies of the same data. At ~150 MB per layer this is negligible (cents/month). At a hundred GB it would matter. **Honest production delta**: in production, staging is often ephemeral (recreated on demand and deleted on schedule). For portfolio we keep all three persistent because seeing them on `aws s3 ls` tells the story.
- **3 buckets to provision and tag.** A small operational tax. Mitigated by `infra/create-buckets.sh`.
- **Lineage is implicit, not enforced.** Nothing in the code prevents a Glue Job from reading curated and writing to staging. We rely on naming conventions and the layer contracts above. **Honest production delta**: in production, IAM policies would prevent cross-layer writes the wrong way; here, that is a 4-hour IAM exercise we skipped.

### Neutral / open questions

- We may want a `quarantine/` bucket for rows that fail quality checks. Deferred — when the first quality check rule starts producing rejects, that's the trigger to add it.
- "Append vs overwrite" in staging may need to change if we ever switch from full reloads to incremental. Deferred — the Olist dataset is static, the reload pattern is fine.

## Alternatives considered

### Single curated layer

Skip raw and staging entirely. Glue Job reads CSV from Kaggle directly into curated Parquet. **Rejected because** the project loses its reprocessability story. If a transformation has a bug, we cannot rebuild from raw — we have to re-download from Kaggle. Worse, we lose the demonstration value: a recruiter looking at the repo cannot tell "this person knows how to design a data lake" from a single-layer project.

### Four layers (raw / bronze / silver / gold)

The full Databricks pattern. **Rejected because** with Olist's volume (100k orders, ~150 MB), the difference between bronze (raw-cleaned) and silver (business-modelled) collapses — there is no business logic complex enough to deserve its own intermediate layer. Adding a fourth tier would be ceremony.

### One bucket with prefixes (`/raw/`, `/staging/`, `/curated/`)

Same data, fewer buckets. **Rejected because** the operational cost of separate buckets is tiny (a one-time `infra/create-buckets.sh`) and the benefits — independent lifecycle, IAM, blast radius, cost tags — are real. In a production setting with >1 TB this would also affect cross-region replication topology, which prefix-only layouts cannot do per-tier.

### Apache Iceberg / Delta Lake table format on top of S3

Modern table formats give you ACID transactions, schema evolution, time travel. **Rejected because** Athena's Iceberg support exists but adds operational complexity (compaction, metadata cleanup) that we don't need at this scale. **Honest production delta**: if curated were >100 GB and updated incrementally, Iceberg would earn its place. For 50 MB, plain Parquet is the right answer.

## References

- [Databricks medallion architecture](https://www.databricks.com/glossary/medallion-architecture)
- [AWS Lake Formation reference architectures](https://docs.aws.amazon.com/lake-formation/)
- [Apache Iceberg on Athena](https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg.html) — for the production delta
- Related: ADR-0001 (Athena reads curated), ADR-0003 (orchestration drives the layer transitions).
