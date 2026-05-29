# ADR-0008 — Parametrized staging job with per-table registry

- **Status**: Accepted
- **Date**: 2026-05-29
- **Tags**: glue, transformation, staging, parametrization, operational-model

## Context

ADR-0006 fixed the **high-watermark (HWM) pattern** for incremental loads, and the first transformation that implements it — `staging_orders` — is live in AWS (workgroup `olist-dev`, table `olist_dev.staging_orders`, 99,441 rows across 25 partitions). That work proved the *per-table* pattern: read raw with `spark.read.csv(header=True)`, filter by `ingested_at > hwm`, cast timestamps, dedup by primary key keeping the latest by `ingested_at`, write Parquet+Snappy.

Eight tables remain to be brought from raw to staging: `customers`, `sellers`, `products`, `product_category_name_translation`, `order_items`, `order_payments`, `order_reviews`, `geolocation`. Their schemas were inspected directly in raw S3 (not assumed). The mapping shows the eight are **not homogeneous** with `orders`:

| Concern | Reality across the 8 |
|---|---|
| Primary key | 5 tables have a single-column PK, 2 have a composite PK (`order_items`, `order_payments`), 1 has **no unique key** (`geolocation`). |
| Timestamps to cast | Most have none. `order_items` has `shipping_limit_date`; `order_reviews` has `review_creation_date` + `review_answer_timestamp`. |
| Partitioning candidate | None has a clean business date analogous to `order_purchase_timestamp`. |
| Encoding edge case | `product_category_name_translation` ships with a BOM (`utf-8-sig`). |
| Size | From 71 rows (`product_category_name_translation`) to ~1M (`geolocation`). |

The operational question is therefore: **one parametrized Glue Job that handles all eight by configuration, or eight separate jobs**. The choice commits the project to an operational model — adding a 9th table later means either editing config in one place or shipping a new script — so this ADR is required before any code is written.

## Pre-decision review

- **Failure mode in 6 months**: a new table is added to the pipeline whose transformation does not fit the registry (e.g. needs a join with another table before the cast/dedup step, or an `explode` from a list-valued column). To preserve the pattern it is added as a special case inside the common job. The common job accretes `if source == X: ...` branches until it is more tangled than eight separate scripts would have been. Two such branches already exist on day one (`geolocation` dedup, `utf-8-sig` for translation); the count is the early-warning signal — see below.
- **Prior art and divergence**: this is the canonical choice of the modern data engineering ecosystem. dbt models with macros, Airflow `TaskGroup` over parametrized operators, internal "transform framework" projects at Spotify (Luigi) / Shopify / Uber all converge on **one logic + declarative config per table** when tables share structure. We are **not diverging** — choosing the opposite (eight jobs) would require justification.
- **Cost of reversal**: low, ~1 day. The registry is a Python dict, not infrastructure. Reversing means generating eight scripts mechanically: for each registry entry, copy the common script and inline the parameters. No data migration, no AWS resource recreation, no downstream impact on Power BI. The decision lives only in code.
- **Early warning signal**: the count of source-specific branches inside the common job. Day one has 2 (`geolocation` dedup strategy, `utf-8-sig` encoding for translation). If the count reaches **5 or more**, the abstraction has broken — at that point the right move is to split the job and accept the duplication. The metric is observable in code review with no instrumentation.

## Decision

We adopt a **single parametrized Glue Job** for the staging transformation, driven by a **per-table registry** declared in code.

### The single job

A wrapper script `infra/glue-jobs/staging_transform_glue.py` accepts a Glue Job argument `--SOURCE_TABLE <name>` and dispatches the same logic — read raw with `header=True`, HWM filter on `ingested_at`, type casts, dedup, write Parquet+Snappy — for any of the registered tables. The script is uploaded by a single provisioning script `infra/create-glue-job-staging-transform.sh`. There is **one** Glue Job in AWS (`olist-staging-transform`, replacing the table-specific `olist-staging-orders` once parity is verified), not one per table.

### The registry

A module `src/olist_pipeline/transformation/staging_registry.py` exports a typed dictionary, one entry per source table:

```python
@dataclass(frozen=True)
class StagingSpec:
    primary_key: tuple[str, ...]                       # list of columns; supports composite PKs
    timestamp_columns: tuple[str, ...]                 # columns to cast to TimestampType
    partition_by: tuple[str, ...] | None               # output partition columns, derived later
    dedup_strategy: Literal["standard", "full_row"]    # standard = row_number by PK; full_row = distinct
    csv_encoding: Literal["utf-8", "utf-8-sig"]        # raw read encoding

REGISTRY: dict[str, StagingSpec] = {
    "orders":                            StagingSpec(("order_id",), ORDERS_TIMESTAMPS, ("year", "month"), "standard", "utf-8"),
    "customers":                         StagingSpec(("customer_id",), (), None, "standard", "utf-8"),
    "sellers":                           StagingSpec(("seller_id",), (), None, "standard", "utf-8"),
    "products":                          StagingSpec(("product_id",), (), None, "standard", "utf-8"),
    "product_category_name_translation": StagingSpec(("product_category_name",), (), None, "standard", "utf-8-sig"),
    "order_items":                       StagingSpec(("order_id", "order_item_id"), ("shipping_limit_date",), None, "standard", "utf-8"),
    "order_payments":                    StagingSpec(("order_id", "payment_sequential"), (), None, "standard", "utf-8"),
    "order_reviews":                     StagingSpec(("review_id",), ("review_creation_date", "review_answer_timestamp"), None, "standard", "utf-8"),
    "geolocation":                       StagingSpec((), (), None, "full_row", "utf-8"),
}
```

### Partition strategy in staging

**Only `orders` is partitioned in staging**, inherited from the existing implementation (`year`/`month` derived from `order_purchase_timestamp`). The other eight are written **unpartitioned**: dimensions are too small to benefit, and the fact-shaped ones (`order_items`, `order_payments`, `order_reviews`) lack a business date naturally aligned to the order. Partitioning of the fact tables is handled in **curated** (where joins back to `dim_date` via `orders.order_purchase_timestamp` give a clean partition key).

The registry **models** `partition_by` as a field so future tables can opt in without schema change to the registry — the absence is data, not code.

### Two special cases handled by the registry, not by `if` branches in the job

1. **`geolocation` dedup**: `dedup_strategy="full_row"` triggers `df.distinct()` instead of the `row_number()`-by-PK pattern. The job code reads the strategy from the spec; there is no `if source == "geolocation"` in the script.
2. **`product_category_name_translation` BOM**: `csv_encoding="utf-8-sig"` is passed to `spark.read.option("encoding", ...)`. Again, no source-name check in the script.

This keeps the common job small and the heterogeneity in data (the registry), which is the entire point of the pattern.

### HWM scope

Each source table keeps its **own** HWM state file at `s3://<staging-bucket>/_metadata/staging_<source>_state.json`, as `staging_orders` already does. The state file is per-source, not shared, so a backfill or rerun of one table does not affect the others.

## Consequences

### Positive

- **Single source of truth for transformation logic** — bug fixes and improvements (better dedup, better logging, performance tuning) land in one script and apply to all eight tables.
- **Adding a 9th table is one registry entry**, not a new script, a new provisioning shell script, a new Glue Job resource in AWS, and a new test file. Removes 4 places to forget.
- **Test surface is smaller**: the common transform is tested once with parametrized fixtures over the registry; the registry itself is tested as data (does it cover every raw `source=*` prefix? do all PKs exist in the data?).
- **One Glue Job to provision, tag, monitor, and tear down** — not eight. Cuts the AWS surface area by 8× for the staging layer.
- **Aligns with industry-canonical pattern** (dbt, Airflow, internal frameworks at large data orgs), which is a portfolio signal.

### Negative

- **Indirection**: to answer "what does the pipeline do to `order_items`?" a reader has to open the registry and the common job, not a single self-contained script. Mitigation: the registry entry is dense and declarative — the answer is on one line.
- **Two special cases on day one**: `dedup_strategy="full_row"` and `csv_encoding="utf-8-sig"` already require the registry to model concepts beyond "PK + timestamps + partition". The abstraction is paying its first complexity cost before the second table is shipped.
- **Single point of failure in code**: a bug in the common job breaks all eight tables at once. Mitigation: dynamic partition overwrite + per-source HWM means a bad run on one table does not corrupt the others' partitions.
- **`geolocation` does not really belong in this pattern**: with no unique key, it's a lookup table that could arguably skip staging and be served directly from raw via Athena. We include it in the registry for uniformity, knowing the abstraction stretches.

### Neutral / open

- **Should the registry support a `transform_hook` callable** for tables that need extra steps beyond cast + dedup (e.g. a future `fx_rates` table that needs an HTTP fetch and a `LEFT JOIN` before write)? Deferred to when the need is concrete; the current registry covers the eight tables in scope.
- **Should `staging_orders.py` be refactored into the common job** or kept as the reference implementation while the new generic path is built and verified, then deprecated? Recommend the second: build the generic path, run both for one calendar day on `orders`, compare output, then delete the table-specific script.

## Alternatives considered

### Alternative A — Eight separate Glue Jobs, one per source

Each table gets its own `staging_<source>.py` and its own `infra/create-glue-job-staging-<source>.sh`. The transform logic is duplicated eight times.

**Rejected** because (i) duplication of identical logic (HWM, dedup, write) across eight scripts guarantees they drift apart; (ii) every bug fix becomes eight separate edits; (iii) eight Glue Jobs to tag, monitor, and tear down for the same conceptual operation; (iv) industry has converged away from this approach.

### Alternative B — One Glue Job with hard-coded `if/elif` per table

A single script that internally does `if source == "customers": ... elif source == "sellers": ...`. No separate registry — the configuration is inlined in the dispatch tree.

**Rejected** because it mixes data and code. Adding a table requires editing the dispatch tree, which is also where logic bugs live; reviewing the table list requires reading code instead of a declarative dict. It is the pattern that the registry exists to prevent.

### Alternative C — Skip staging for the eight; serve them via Athena `CREATE TABLE AS SELECT` directly over raw

For the dimension and lookup tables (small, few transformations needed), one could argue that staging adds cost without value: just register them as Athena views over raw and call it done. Only `order_items`, `order_payments`, `order_reviews` would go through Spark.

**Rejected** because it breaks the medallion principle adopted in ADR-0002. Staging is the *typed and clean* layer; raw CSVs need their timestamps cast, decimals typed, BOM stripped, duplicates removed. CTAS from raw would push those concerns onto every downstream consumer (Athena queries, Power BI). The cost of running a 2-DPU Glue Job on a 4 MB CSV is ~$0.07 — well below the cost of inconsistent typing in the dashboard.

## References

- [ADR-0002 — Medallion architecture](0002-medallion-architecture.md) — the layer this decision operates within.
- [ADR-0006 — Incremental ingestion with HWM](0006-incremental-ingestion-hwm.md) — the pattern each registry entry implements.
- [`docs/glossary.md`](../glossary.md) — entries for *Registry pattern (config-driven transformation)*, *explode / UNNEST*.
- [dbt — configurations and macros](https://docs.getdbt.com/docs/build/jinja-macros) — canonical example of one-logic-many-tables in the warehouse world.
- [Airflow — `TaskGroup`](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dag-run.html#task-groups) — same pattern in the orchestration world.
