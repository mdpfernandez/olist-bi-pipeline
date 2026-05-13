# Incremental loads — operational guide

Operational guide for the incremental ingestion pattern. Companion to ADR-0006 (Phase A: HWM over plain Parquet) and ADR-0007 (Phase B: Apache Iceberg migration).

> **Audience**: anyone implementing, debugging, or operating the pipeline. This document is **the** source of truth for *how* the incremental flow works — the ADRs explain *why*.

## Table of contents

1. [The simulation strategy: "rejugar el tiempo"](#1-the-simulation-strategy-rejugar-el-tiempo)
2. [Phase A: HWM pattern](#2-phase-a-hwm-pattern)
   - 2.1 The two watermarks
   - 2.2 The state file
   - 2.3 The Glue Job structure
   - 2.4 Late-arriving handling
   - 2.5 Idempotency guarantees
3. [Late-arriving simulation](#3-late-arriving-simulation)
4. [Backfill procedure](#4-backfill-procedure)
5. [Phase B: Iceberg migration](#5-phase-b-iceberg-migration)
6. [Operational rituals](#6-operational-rituals)
7. [Testing the incremental flow](#7-testing-the-incremental-flow)
8. [Anti-patterns](#8-anti-patterns)
9. [Recovery procedures](#9-recovery-procedures)

---

## 1. The simulation strategy: "rejugar el tiempo"

The Olist dataset is **static** — all 100k orders are already there, spanning sep 2016 to aug 2018. To demonstrate incremental loads we **replay the time axis**: we pretend the data arrives in chronological batches, as it would in production.

### The schedule

```
Real time          │ Simulated business time   │ What we do
───────────────────┼───────────────────────────┼──────────────────────────────
Day 1 (initial)    │ "It is now 2018-01-01"    │ Ingest all orders with
                   │                           │ purchase_timestamp < 2018-01-01
                   │                           │ (16 months of history)
───────────────────┼───────────────────────────┼──────────────────────────────
Day 2 (incremental)│ "It is now 2018-02-01"    │ Ingest January 2018 orders
Day 3              │ "It is now 2018-03-01"    │ Ingest February 2018 orders
Day 4              │ "It is now 2018-04-01"    │ Ingest March 2018 orders
Day 5              │ "It is now 2018-05-01"    │ Ingest April 2018 orders + 
                   │                           │ ~50 LATE-ARRIVING from Oct 2017
Day 6              │ "It is now 2018-06-01"    │ Ingest May 2018 orders
Day 7              │ "It is now 2018-07-01"    │ Ingest June 2018 orders
Day 8              │ "It is now 2018-08-01"    │ Ingest July 2018 orders
Day 9 (last)       │ "It is now 2018-09-01"    │ Ingest August 2018 orders
```

### The `ingested_at` column

Every CSV we upload to `raw/` is tagged with the **wall-clock timestamp** of when we uploaded it, NOT with its business date. We add this as a column in the raw → staging transformation. So:

- Order `abc123` with `purchase_timestamp = 2017-10-15` ingested on day 1: `ingested_at = 2026-05-08T10:00:00Z`
- Order `xyz789` with `purchase_timestamp = 2018-04-15` ingested on day 5: `ingested_at = 2026-05-12T10:00:00Z`
- Order `def456` with `purchase_timestamp = 2017-10-20` (LATE-ARRIVING) ingested on day 5: `ingested_at = 2026-05-12T10:00:01Z`

The HWM tracks `ingested_at`, not `purchase_timestamp`. That is the key insight that makes late-arriving handling clean.

---

## 2. Phase A: HWM pattern

### 2.1 The two watermarks

| Watermark | Type | Advances monotonically? | What it tells us |
|---|---|---|---|
| `ingestion_hwm` | UTC timestamp | Yes, always | "I've processed everything ingested up to this moment" |
| `business_hwm` | UTC timestamp | Usually yes, but **can stall** on late-arriving | "The latest business date I've seen in my data" |

A late-arriving batch causes `ingestion_hwm` to advance (we ingested new data) but `business_hwm` to **NOT** advance (the dates are old). The gap is the signal that something is unusual.

### 2.2 The state file

Lives at `s3://<bucket>/_metadata/processing_state.json`, one per layer (staging and curated).

```json
{
  "layer": "staging",
  "schema_version": "1.0",
  "last_run": {
    "run_id": "2026-05-12T10:00:00Z-run45",
    "started_at": "2026-05-12T10:00:00Z",
    "completed_at": "2026-05-12T10:14:32Z",
    "status": "success"
  },
  "watermarks": {
    "ingestion_hwm": "2026-05-12T10:00:00Z",
    "business_hwm": "2018-04-30T23:59:59Z"
  },
  "stats": {
    "rows_processed": 8421,
    "rows_late_arriving": 47,
    "partitions_touched": [
      "year=2018/month=04",
      "year=2017/month=10"
    ],
    "partitions_rewritten": [
      "year=2017/month=10"
    ]
  }
}
```

Fields explained:
- `schema_version`: lets us evolve this file's schema later without breaking readers.
- `partitions_touched`: every partition that received writes (new or overwritten).
- `partitions_rewritten`: subset of `partitions_touched` that were OVERWRITTEN because they already existed (late-arriving). Tracking this separately is how we measure the trigger for ADR-0007.

### 2.3 The Glue Job structure

Pseudo-code of a staging Glue Job (`src/olist_pipeline/transformation/staging_orders.py`):

```python
def run_incremental_staging(table_name: str) -> dict:
    """Process the orders table incrementally.

    HWM lives in s3://<bucket>/_metadata/processing_state_<table>.json.
    Read everything in raw with ingested_at > ingestion_hwm.
    Write to staging, overwriting partitions that already exist (late-arriving case).
    Update state file atomically on success.
    """
    state = read_state_file(STATE_URI)
    ingestion_hwm = state["watermarks"]["ingestion_hwm"]

    # 1. Read incoming batch
    incoming = (
        spark.read.parquet(RAW_URI)
        .where(F.col("ingested_at") > F.lit(ingestion_hwm))
        .where(F.col("source") == table_name)
    )

    if incoming.count() == 0:
        logger.info("nothing_to_process", hwm=ingestion_hwm)
        return {"status": "no_op", "hwm": ingestion_hwm}

    # 2. Apply staging transformations (type cast, dedupe within batch, filter bad rows)
    transformed = apply_staging_transforms(incoming, table_name)

    # 3. Detect late-arriving rows
    new_business_hwm = transformed.agg(F.max("purchase_timestamp")).first()[0]
    late_arriving = transformed.filter(F.col("purchase_timestamp") <= F.lit(state["watermarks"]["business_hwm"]))
    late_count = late_arriving.count()

    if late_count > 0:
        logger.warning("late_arriving_detected", count=late_count)

    # 4. Identify partitions to touch
    partitions = transformed.select("year", "month").distinct().collect()

    partitions_touched = []
    partitions_rewritten = []

    for p in partitions:
        partition_uri = f"{STAGING_URI}/source={table_name}/year={p.year}/month={p.month}/"

        if path_exists(partition_uri):
            # LATE-ARRIVING CASE: partition exists, must merge-then-overwrite
            existing = spark.read.parquet(partition_uri)
            partition_data = transformed.filter(
                (F.col("year") == p.year) & (F.col("month") == p.month)
            )
            merged = (
                existing
                .unionByName(partition_data)
                .dropDuplicates(["order_id"])  # natural key for orders
            )
            merged.write.mode("overwrite").parquet(partition_uri)
            partitions_rewritten.append(f"year={p.year}/month={p.month}")
        else:
            # NORMAL CASE: new partition, simple write
            partition_data = transformed.filter(
                (F.col("year") == p.year) & (F.col("month") == p.month)
            )
            partition_data.write.mode("overwrite").parquet(partition_uri)

        partitions_touched.append(f"year={p.year}/month={p.month}")

    # 5. Write _SUCCESS marker
    write_success_marker(f"{STAGING_URI}/source={table_name}/_SUCCESS")

    # 6. Atomically update state file
    new_state = {
        "layer": "staging",
        "schema_version": "1.0",
        "last_run": {
            "run_id": current_run_id(),
            "started_at": run_start,
            "completed_at": utc_now(),
            "status": "success",
        },
        "watermarks": {
            "ingestion_hwm": transformed.agg(F.max("ingested_at")).first()[0],
            "business_hwm": max(state["watermarks"]["business_hwm"], new_business_hwm),
        },
        "stats": {
            "rows_processed": transformed.count(),
            "rows_late_arriving": late_count,
            "partitions_touched": partitions_touched,
            "partitions_rewritten": partitions_rewritten,
        },
    }
    write_state_atomically(STATE_URI, new_state, expected_etag=state["_etag"])

    return new_state
```

### 2.4 Late-arriving handling

Late-arriving = an incoming row whose `purchase_timestamp` is **<= business_hwm** but whose `ingested_at` is **> ingestion_hwm**.

```
Visual:
  ingestion_hwm  ─────────────────────────────────┐
                                                  │
                                                  ▼
  ingested_at: ───────────●─────●──────────────────────●─────────
                          ↑     ↑                    ↑
                          past  past                 NEW (this run)
  
  purchase_timestamp:                               ↑
                                       business_hwm─┘
                                                    
  ●─ purchase_ts > business_hwm  → NORMAL incremental
  ●─ purchase_ts <= business_hwm → LATE-ARRIVING (partition rewrite needed)
```

The detection is **purely metadata-based**: no row-by-row comparison, just `purchase_timestamp <= business_hwm` check on the batch's distinct partition keys.

The handling cost: O(partition_size). For Olist where each monthly partition is <10 MB, this is fast. For production-grade datasets it becomes a problem — which is exactly the trigger for ADR-0007.

### 2.5 Idempotency guarantees

The pattern guarantees: **for any sequence of runs, the final state of curated depends only on the union of raw files processed, not on the order or grouping of runs.**

Proof sketch:
- Each row has a natural key (`order_id` for orders, `(order_id, order_item_id)` for order_items, etc.).
- The dedup on partition overwrite removes any duplicate that appears in both the existing partition and the new batch.
- Re-running the same incremental load is a no-op: the state file's `ingestion_hwm` is already at the max, so the read returns 0 rows.
- Reverting `ingestion_hwm` and re-running causes the same partitions to be rewritten with the same dedup logic → same output.

If idempotency breaks, **the natural-key dedup is wrong**. Validate the dedup logic per table in unit tests.

---

## 3. Late-arriving simulation

To demonstrate the late-arriving capability, we manually inject ~50 orders with old `purchase_timestamp` into the raw layer on Day 5 (simulating April 2018 ingestion).

### The injection script

`scripts/inject_late_arriving.py`:

```python
"""
Inject ~50 simulated late-arriving orders into the raw layer.

The injected orders have purchase_timestamp in October 2017 (a partition that
was already processed in the initial load) but ingested_at = now (this very
moment in wall-clock time).

This forces the staging Glue Job to detect them as late-arriving and rewrite
the year=2017/month=10/ partition.
"""

import boto3
import pandas as pd
from datetime import datetime, timezone
from olist_pipeline.core.config import settings

INJECTION_COUNT = 50
TARGET_PURCHASE_MONTH = "2017-10"  # the "old" partition we will hit


def main():
    # 1. Read some recent orders to use as templates (avoid generating fake data)
    s3 = boto3.client("s3")
    obj = s3.get_object(
        Bucket=settings.s3_bucket_raw,
        Key=f"source=orders/ingested_at={initial_load_date}/orders.csv.gz",
    )
    orders = pd.read_csv(obj["Body"], compression="gzip")

    # 2. Take 50 orders, generate new IDs, set their purchase_timestamp to October 2017
    template = orders.head(INJECTION_COUNT).copy()
    template["order_id"] = [
        f"late_arr_{i:03d}_{datetime.now().strftime('%H%M%S')}"
        for i in range(INJECTION_COUNT)
    ]
    template["order_purchase_timestamp"] = pd.date_range(
        start=f"{TARGET_PURCHASE_MONTH}-01",
        end=f"{TARGET_PURCHASE_MONTH}-31",
        periods=INJECTION_COUNT,
    )

    # 3. Upload to raw with a NEW ingested_at partition (today)
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    out_key = f"source=orders/ingested_at={today}/late_arriving_batch.csv.gz"
    template.to_csv(f"/tmp/{out_key}", index=False, compression="gzip")

    s3.upload_file(
        Filename=f"/tmp/{out_key}",
        Bucket=settings.s3_bucket_raw,
        Key=out_key,
        ExtraArgs={
            "Tagging": "project=olist-pipeline&env=dev&owner=marianela&type=late-arriving-sim",
        },
    )

    print(f"Injected {INJECTION_COUNT} late-arriving orders to s3://{settings.s3_bucket_raw}/{out_key}")


if __name__ == "__main__":
    main()
```

### Expected pipeline behaviour after injection

When the next incremental run executes:

1. Reads `staging` raw partition for today → finds 50 new orders + whatever normal April-2018 data exists.
2. Detects 50 orders with `purchase_timestamp` in 2017-10 → late-arriving partition is `year=2017/month=10/`.
3. Reads existing `staging/source=orders/year=2017/month=10/` (with say 4,200 orders).
4. Unions with the 50 new ones → 4,250 rows.
5. Deduplicates on `order_id` (no duplicates because the injected IDs are new) → 4,250 rows.
6. Overwrites the partition with the 4,250 rows.
7. `stats.partitions_rewritten` includes `year=2017/month=10`.
8. Logs `late_arriving_detected count=50`.

### How to verify

```bash
# Before injection
aws s3 ls s3://olist-staging-mfern-xx/source=orders/year=2017/month=10/ \
    --recursive --summarize --human-readable | tail -3
# expected: ~4200 rows (1 file)

# Inject
uv run python scripts/inject_late_arriving.py

# Run the incremental pipeline
bash infra/run-pipeline.sh

# After
aws s3 ls s3://olist-staging-mfern-xx/source=orders/year=2017/month=10/ \
    --recursive --summarize --human-readable | tail -3
# expected: ~4250 rows (1 file, larger)

# Check the state file
aws s3 cp s3://olist-staging-mfern-xx/_metadata/processing_state_orders.json - | jq .stats
# expected: rows_late_arriving=50, partitions_rewritten=["year=2017/month=10"]
```

---

## 4. Backfill procedure

Sometimes you need to **reprocess** a date range — a bug was found, a transformation was wrong, etc. The HWM pattern supports this via a manual reset.

### Procedure

1. **Decide the cutoff.** What `ingestion_hwm` value should we roll back to?
   - To reprocess everything from May 1, 2026 onwards: set `ingestion_hwm = "2026-04-30T23:59:59Z"`.
   - To reprocess only one day: set `ingestion_hwm` to the timestamp just before that day's first ingestion.

2. **Run the reset script**:

   ```bash
   uv run python scripts/reset_hwm.py \
       --layer staging \
       --table orders \
       --new-ingestion-hwm "2026-04-30T23:59:59Z" \
       --reason "Bugfix in dedup logic (PR #123)"
   ```

   The script:
   - Reads the current state file.
   - Archives it to `_metadata/_archive/processing_state_orders_<timestamp>.json` (audit trail).
   - Writes a new state file with the lower HWM.
   - Logs the reason in `_metadata/backfill_log.jsonl` (append-only).

3. **Run the pipeline**. The next incremental run will see "lots of new data" (because HWM is artificially low) and reprocess it.

4. **Verify** with row counts before / after.

### Idempotency in backfills

Because every layer's writes are dedup-on-overwrite, a backfill never produces duplicates. The worst case is "we wrote the same data twice" — and the dedup catches it.

---

## 5. Phase B: Iceberg migration

Once ADR-0007 flips to `Accepted`, the changes are:

### Curated tables become Iceberg

`infra/athena-views/fact_orders.sql`:

```sql
CREATE TABLE olist_dev.fact_orders (
    order_id        STRING,
    customer_id     STRING,
    purchase_date_id INT,
    delivered_date_id INT,
    order_status    STRING,
    delivery_delay_days INT,
    is_late         BOOLEAN,
    year            INT,
    month           INT
)
PARTITIONED BY (year, month)
LOCATION 's3://olist-curated-mfern-xx/fact_orders/'
TBLPROPERTIES (
    'table_type' = 'ICEBERG',
    'format' = 'parquet',
    'write_compression' = 'snappy'
);
```

### Late-arriving handling becomes MERGE

Replaces the partition-rewrite logic with a single SQL statement:

```sql
MERGE INTO fact_orders AS target
USING (
    SELECT * FROM staging_fact_orders_delta
    WHERE ingested_at > '{ingestion_hwm}'
) AS source
ON target.order_id = source.order_id
WHEN MATCHED THEN UPDATE SET
    order_status         = source.order_status,
    delivered_date_id    = source.delivered_date_id,
    delivery_delay_days  = source.delivery_delay_days,
    is_late              = source.is_late
WHEN NOT MATCHED THEN INSERT (
    order_id, customer_id, purchase_date_id, delivered_date_id,
    order_status, delivery_delay_days, is_late, year, month
) VALUES (
    source.order_id, source.customer_id, source.purchase_date_id,
    source.delivered_date_id, source.order_status, source.delivery_delay_days,
    source.is_late, source.year, source.month
);
```

Single statement. Row-level. No partition rewrites.

### Time travel queries

```sql
-- "Show me the fact_orders state at midnight on 2026-05-08"
SELECT order_id, order_status
FROM fact_orders FOR TIMESTAMP AS OF TIMESTAMP '2026-05-08 00:00:00 UTC'
WHERE customer_id = 'abc123';

-- "How did this customer's order history evolve?"
SELECT
    snapshot_time,
    snapshot_id,
    order_status
FROM fact_orders.history
WHERE order_id = 'order_xyz789'
ORDER BY snapshot_time;
```

### Maintenance Lambda

Iceberg accumulates snapshots. We run a weekly maintenance Lambda:

```sql
-- Expire snapshots older than 7 days (keep last 5 in any case)
CALL system.expire_snapshots(
    table => 'fact_orders',
    older_than => TIMESTAMP '7 days ago',
    retain_last => 5
);

-- Remove orphan files (referenced by no snapshot)
CALL system.remove_orphan_files(table => 'fact_orders');
```

Scheduled via EventBridge, Sunday 03:00 UTC.

---

## 6. Operational rituals

### Daily during active development (Monday–Friday)

```bash
# Morning: bring up resources
bash infra/bring-up.sh

# Run yesterday's incremental
bash infra/run-pipeline.sh --simulated-date "$(date -d '1 day ago' +%Y-%m-%d)"

# Check the state file
aws s3 cp s3://olist-staging-mfern-xx/_metadata/processing_state_orders.json - | jq .
```

### Friday teardown (unchanged)

```bash
bash infra/destroy-all.sh
```

### Whenever a new month of simulated data lands

```bash
# Triggered manually during the simulation phase
bash infra/run-pipeline.sh --simulated-date 2018-03-01
```

### When a late-arriving simulation happens

```bash
# Inject some late-arriving orders
uv run python scripts/inject_late_arriving.py

# Run the pipeline normally (HWM detects the late-arriving rows)
bash infra/run-pipeline.sh
```

---

## 7. Testing the incremental flow

### Unit tests for the HWM logic

Under `tests/unit/orchestration/test_hwm.py`:

```python
def test_hwm_advances_monotonically_on_normal_batch():
    """Normal batch: both watermarks advance."""
    state_before = {"watermarks": {"ingestion_hwm": "2026-05-01T00:00:00Z", "business_hwm": "2018-03-31T23:59:59Z"}}
    batch = make_batch(ingested_at="2026-05-08T10:00:00Z", purchase_ts=["2018-04-01", "2018-04-15"])

    new_state = apply_batch(state_before, batch)

    assert new_state["watermarks"]["ingestion_hwm"] == "2026-05-08T10:00:00Z"
    assert new_state["watermarks"]["business_hwm"] == "2018-04-15T00:00:00Z"


def test_late_arriving_does_not_regress_business_hwm():
    """Late-arriving batch: ingestion_hwm advances, business_hwm stays."""
    state_before = {"watermarks": {"ingestion_hwm": "2026-05-01T00:00:00Z", "business_hwm": "2018-04-15T00:00:00Z"}}
    batch = make_batch(ingested_at="2026-05-08T10:00:00Z", purchase_ts=["2017-10-15"])

    new_state = apply_batch(state_before, batch)

    assert new_state["watermarks"]["ingestion_hwm"] == "2026-05-08T10:00:00Z"
    assert new_state["watermarks"]["business_hwm"] == "2018-04-15T00:00:00Z"  # unchanged
    assert new_state["stats"]["rows_late_arriving"] == 1
```

### Integration tests with moto

Under `tests/integration/test_incremental_load.py`:

```python
@mock_aws
def test_late_arriving_overwrites_existing_partition():
    """End-to-end: inject late-arriving, run pipeline, verify partition was rewritten."""
    setup_buckets()
    initial_load_with_october_2017_data()  # writes year=2017/month=10/ partition

    inject_late_arriving_batch(count=5, target_month="2017-10")
    run_incremental_pipeline()

    # The partition should have grown by 5 rows
    rows = read_partition("year=2017", "month=10")
    assert len(rows) == initial_count + 5

    # All original orders should still be present
    assert set(initial_order_ids).issubset(set(rows["order_id"]))

    # State file should record the late-arriving event
    state = read_state_file()
    assert state["stats"]["rows_late_arriving"] == 5
    assert "year=2017/month=10" in state["stats"]["partitions_rewritten"]
```

### Reconciliation test

Per-table reconciliation: `staging row count` == `curated row count` for the same partition range.

```sql
-- Run this after every incremental load
SELECT
    'staging' AS layer, year, month, COUNT(*) AS rows
FROM staging.orders
WHERE year = 2018 AND month = 4
GROUP BY year, month

UNION ALL

SELECT
    'curated' AS layer, year, month, COUNT(*) AS rows
FROM curated.fact_orders
WHERE year = 2018 AND month = 4
GROUP BY year, month;

-- The two rows must have the same COUNT.
```

If they diverge by >0, the incremental flow lost or duplicated data — STOP and investigate before next run.

---

## 8. Anti-patterns

| Anti-pattern | Why it's wrong | What to do instead |
|---|---|---|
| Filtering by `purchase_timestamp > hwm` instead of `ingested_at > hwm` | Skips late-arriving data silently | Always filter by `ingested_at`. The `purchase_timestamp` is for partitioning the write, not for selecting the read. |
| Storing HWM in code or env var instead of S3 | State is invisible, not versioned, not auditable | The state file lives in S3 with versioning enabled. |
| Overwriting the state file without atomic semantics | Two concurrent runs can corrupt state | Use S3 `If-Match` conditional PUT with ETag. |
| Backfill by editing the state file directly | No audit trail | Use `scripts/reset_hwm.py` which archives and logs. |
| Allowing late-arriving with no upper bound on age | A 10-year-old order can hammer an ancient partition | Document the SLA: "we accept late-arriving up to 90 days". Reject older with an alert. |
| Forgetting to dedupe on partition overwrite | Duplicate `order_id`s appear in curated | The dedup on natural key is the linchpin of idempotency. |
| Running incremental without `_SUCCESS` markers | Downstream Lambda can't tell if upstream finished | Always write `_SUCCESS` last, with the run's `state` JSON as its body. |
| Trusting `_SUCCESS` exists but not checking its content | If a run failed mid-write, marker may be stale | Use file age + content fingerprint: marker is "fresh" only if its timestamp matches state file's `completed_at`. |
| Skipping the reconciliation query after every run | Bugs are caught at end-of-month when impossible to fix | Reconcile per run, fail fast. |

---

## 9. Recovery procedures

### "The state file is corrupted"

1. Stop all pipeline runs.
2. List archived states: `aws s3 ls s3://<bucket>/_metadata/_archive/`.
3. Find the most recent known-good state (check the `completed_at`).
4. Copy it back to the live location: `aws s3 cp <archive> <live>`.
5. Run the pipeline; it picks up from the recovered HWM.

If no archive exists (worst case), reconstruct from data:

```python
# Re-derive HWM from existing curated partitions
import pyspark.sql.functions as F
curated = spark.read.parquet("s3://olist-curated-mfern-xx/fact_orders/")
new_hwm = curated.agg(F.max("ingested_at")).first()[0]
# Manually write a state file with this HWM
```

### "Curated has fewer rows than staging for a date range"

Indicates a curated build job failed silently or a partition was lost.

1. Find the discrepant partition: run the reconciliation query.
2. Use `scripts/reset_hwm.py` to roll back curated's HWM to before that partition.
3. Re-run the pipeline; the curated build job reprocesses.
4. Re-reconcile.

### "Late-arriving partition rewrite failed mid-way"

S3 `overwrite` is atomic at the FILE level but not the PARTITION level (multiple files per partition). If a Glue Job dies mid-write, the partition may be in an inconsistent state.

1. Detect: list files in the partition; if any have a `.crc` or `_temporary` suffix, it failed mid-write.
2. Clean up: delete all files in the partition.
3. Re-run the pipeline. The HWM detects the partition was touched but not committed (the state file was never updated atomically), so it re-attempts.

---

## Related documentation

- **`docs/adr/0006-incremental-ingestion-hwm.md`** — the decision for Phase A.
- **`docs/adr/0007-migration-to-iceberg.md`** — the decision for Phase B.
- **`docs/architecture.md`** §"Refresh strategy" — the high-level summary.
- **`docs/TECHNICAL_DESIGN.md`** §6 "Data flow: the medallion in detail" — the conceptual view.
