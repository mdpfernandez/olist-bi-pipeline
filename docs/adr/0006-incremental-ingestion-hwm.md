# ADR-0006 — Incremental ingestion with high-watermark pattern

- **Status**: Accepted
- **Date**: 2026-05-08
- **Tags**: ingestion, incremental, hwm, idempotency

## Context

ADR-0002 (medallion architecture) defined the storage layout but left the *refresh strategy* implicit. The original Phase 1 plan was **full reload** on every run: rebuild staging from raw, rebuild curated from staging. That works for a 100k-order dataset but it is **not** what a real production system does.

In production, pipelines process **only the new data** since the last successful run. This requires:

1. A mechanism to remember "where I left off" (a **high-watermark**, HWM).
2. A way to detect **late-arriving data** — rows whose business date is older than HWM but whose ingestion date is newer.
3. **Idempotent writes** — re-processing the same input must produce the same output.
4. **Backfill capability** — a manual operator action to reset HWM and reprocess a date range.

The Olist dataset is static (sep 2016 – aug 2018), so there is no real arrival of new data. We **simulate** incrementality by partitioning the dataset chronologically and ingesting one month at a time. This is the standard portfolio pattern for demonstrating incremental loads when the source is static.

The decision is to make incremental refresh **a first-class scope item**, not a deferred production delta. This raises the project's signal for senior data engineering / architecture roles, where "how do you handle incremental loads" is a near-universal interview question.

## Pre-decision review

- **Failure mode in 6 months**: the HWM state file is lost or corrupted, and on the next run the pipeline either re-processes everything (cost spike) or skips everything (data loss). Mitigation: HWM is **re-derivable** from existing partitions — if the state file is missing, we re-compute `max(ingestion_ts)` from the curated layer's partition metadata and resume from there.
- **Prior art and divergence**: every retail / e-commerce data team has solved this. Spotify, Airbnb, Uber, Shopify all published versions of the HWM pattern long before Iceberg / Delta / Hudi existed. We are NOT diverging — we are using the canonical pre-tabular-format approach as the Phase A baseline.
- **Cost of reversal**: low. The HWM state file is a single JSON. We can drop it, set it manually, or fall back to full-reload (which is the existing baseline) at any time without data loss.
- **Early warning signal**: row count divergence between staging input and curated output for the same date range. If staging has 1234 orders for March 2018 and curated has 1230, something was missed or duplicated.

## Decision

We adopt a **two-watermark high-watermark pattern** for incremental ingestion, applied at each layer transition (raw → staging, staging → curated).

### The two watermarks

| Watermark | Type | What it tracks | Where it lives |
|---|---|---|---|
| `ingestion_hwm` | timestamp (UTC) | The max `ingested_at` value processed by the current layer's last successful run | `s3://<bucket>/_metadata/processing_state.json` per layer |
| `business_hwm` | timestamp | The max `order_purchase_timestamp` (or equivalent business date) in the last processed batch — used to detect late-arriving data | same file |

**Why two and not one**: `ingestion_hwm` advances monotonically (you always ingested *after* you ingested last time). `business_hwm` may **not** advance if a late-arriving batch contains old dates. The gap between them is the late-arriving signal.

### The state file format

`s3://olist-staging-mfern-xx/_metadata/processing_state.json`:

```json
{
  "layer": "staging",
  "last_run": {
    "run_id": "2026-05-08T06:00:00Z-run42",
    "completed_at": "2026-05-08T06:14:32Z",
    "status": "success"
  },
  "watermarks": {
    "ingestion_hwm": "2026-05-08T06:00:00Z",
    "business_hwm": "2018-04-30T23:59:59Z"
  },
  "stats": {
    "rows_processed": 8421,
    "rows_late_arriving": 0,
    "partitions_touched": ["year=2018/month=04"]
  }
}
```

### Read logic

Each Glue Job reads:

```python
incoming = spark.read.parquet(staging_uri) \
    .where(F.col("ingested_at") > F.lit(ingestion_hwm))
```

That's the only filter. Note we **do NOT** filter by `purchase_timestamp` — that would skip late-arriving rows. We grab everything ingested since last run, regardless of how old the business date is.

### Write logic

Output is partitioned by business date (`year=YYYY/month=MM`). For each unique partition touched by the incoming batch:

1. **If the partition does NOT exist**: simple append (write new Parquet files into the new partition).
2. **If the partition DOES exist** (late-arriving case): **overwrite the entire partition** with `union(existing, new).dropDuplicates([primary_key])`.

This second case is the "expensive" case. In Phase A (this ADR), we accept the cost: late-arriving forces a partition-level rewrite. In Phase B (ADR-0007), Iceberg `MERGE INTO` replaces this with row-level upsert.

### State update

After successful write, atomically update the state file:

```python
new_state = {
    "watermarks": {
        "ingestion_hwm": max_ingested_at_in_batch,
        "business_hwm": max(current_business_hwm, max_purchase_ts_in_batch),
    },
    "stats": { ... },
}
write_state_atomically(state_uri, new_state)
```

The atomic write uses S3's conditional PUT with an `If-Match` ETag — if two pipeline runs collide, only one wins, the other detects the conflict and fails fast.

## Consequences

### Positive

- **Production-realistic**: matches how every retail data team handles incremental loads.
- **Idempotent**: re-running the same delta on the same input produces the same output.
- **Late-arriving capable**: detects and processes rows whose business date is older than HWM.
- **Cheap**: only the new partitions are written. A staging job that previously took 2 minutes on 100k rows now takes 10 seconds on 8k rows.
- **Backfill-friendly**: a manual `reset_hwm.py` script can roll the HWM back to any timestamp and re-process from there. No state surgery in PySpark code.
- **Signal for senior interviews**: "How do you handle late-arriving data?" now has a concrete, demonstrable answer.

### Negative

- **Late-arriving still rewrites whole partitions** (lossy, not row-level). This is the explicit limitation that ADR-0007 (Iceberg migration) will solve.
- **State file is a single point of dependency**. If the JSON is corrupted, recovery requires re-deriving HWM from data. We mitigate with versioning on the `_metadata/` bucket prefix and an explicit recovery procedure documented in `docs/INCREMENTAL_LOADS.md`.
- **Two-watermark logic is subtle**. Engineers reading the code must understand WHY we filter by `ingested_at` and not by `purchase_timestamp`. We mitigate with a long inline docstring at the top of the staging Glue Job entry-point.
- **No time travel**. Cannot answer "what did `fact_orders` look like as of last Tuesday?" — Phase B (Iceberg) gives us that.

### Neutral / open questions

- Late-arriving threshold: how old can a "late-arriving" row be? In real production we'd reject rows older than 90 days as "too old". For portfolio we accept any age and document the operator decision.
- Concurrent runs: if two ingestion processes try to write the state file simultaneously, the second fails by design. We don't expect this for portfolio scale but document it for completeness.

## Alternatives considered

### Full reload (the previous baseline)

Rebuild staging and curated from scratch on every run. **Rejected because** (1) it scales linearly with corpus size — fine for 100k rows, terrible for 100M, (2) it does not demonstrate incremental-load engineering skill, (3) it cannot represent the "delta refresh" mental model that recruiters want to validate.

### AWS Glue Job Bookmarks

AWS's built-in incremental mechanism — Glue tracks "what files have I processed" and skips them on subsequent runs. **Rejected because**: (a) it's vendor-locked (no equivalent outside AWS Glue), (b) it tracks files, not rows — late-arriving data within the same file is not handled, (c) it's opaque (state lives inside Glue, not inspectable in S3), (d) "I used Glue Bookmarks" sounds less senior in an interview than "I implemented a HWM pattern".

### Apache Iceberg directly (skip Phase A)

Use Iceberg from day one. **Rejected because**: (a) Iceberg has a learning curve (~6-8 hours of focused work), (b) starting with full reload → HWM → Iceberg demonstrates **evolution of thinking**, which is exactly what senior interviews probe, (c) ADR-0007 documents the migration path as a separate decision with its own rationale.

### Delta Lake or Hudi

Functionally similar to Iceberg, but **rejected for portfolio** because Iceberg is AWS's primary supported format for Athena (since 2023). Adding a non-default format would require extra justification without adding portfolio signal.

### Append-only without HWM (treat each layer as a log)

Never overwrite, always append; the latest curated state is the "max-by-key" over the log. **Rejected because**: it inflates storage 10× over time, query cost rises, and late-arriving handling becomes "find the max by composite key" which is fragile.

## References

- [Spotify's TileDB and the HWM pattern (blog, 2021)](https://engineering.atspotify.com/) — illustrative
- [AWS Glue Job Bookmarks](https://docs.aws.amazon.com/glue/latest/dg/monitor-continuations.html) — the rejected alternative
- **Companion**: `docs/INCREMENTAL_LOADS.md` — the operational guide that implements this ADR.
- **Companion**: ADR-0007 (Iceberg migration) — the Phase B successor.
- **Related**: ADR-0002 (medallion architecture) — this ADR refines its refresh-strategy aspect without superseding it.
