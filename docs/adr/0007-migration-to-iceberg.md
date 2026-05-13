# ADR-0007 — Migrate curated layer to Apache Iceberg

- **Status**: Proposed
- **Date**: 2026-05-08
- **Tags**: storage, lakehouse, iceberg, merge, time-travel
- **Trigger to flip to Accepted**: ADR-0006 (HWM) is implemented and stable in production. The trigger condition is: late-arriving partition rewrites become operationally annoying — measured as ≥3 late-arriving events in a single calendar month, or any single late-arriving partition rewrite that touches ≥50 MB.

## Context

ADR-0006 implements incremental ingestion with a high-watermark pattern over plain Parquet. It works, but it has a structural limitation: **late-arriving data forces a full partition rewrite**. If a late-arriving order with `purchase_timestamp = 2017-10-15` arrives in May 2026, the entire `year=2017/month=10/` partition must be read, unioned with the new row, deduplicated, and rewritten.

This is acceptable when:
- Late-arriving is rare (<1% of total rows).
- Partition sizes are small (under ~50 MB).
- Operational cost (Glue Job time) is low.

It becomes a problem when:
- Late-arriving rates exceed ~1% of run volume.
- Partitions grow beyond a few hundred MB.
- The team wants **time travel** (querying "what did this table look like last Tuesday?").
- Schema evolution is needed (add a column without rewriting history).
- Multiple writers need to update the same table concurrently.

In 2023 AWS announced Apache Iceberg as the **default supported table format** for Athena, Glue, and EMR. By 2026 it is the de facto standard for AWS-native lakehouses. Adopting Iceberg now (Phase B) positions the project at the current industry baseline.

## Pre-decision review

- **Failure mode in 6 months**: an Iceberg version incompatibility between the writing engine (Glue 5.0) and the reading engine (Athena v3) breaks queries. Mitigation: pin Iceberg version explicitly in the Glue Job's `--conf` block, run `MSCK REPAIR`-equivalent operation (`CALL system.refresh_table`) after every write.
- **Prior art and divergence**: AWS Solutions Architecture, Tabular.io, Netflix (originator of Iceberg), Apple, LinkedIn, all migrated production warehouses to Iceberg in 2022–2024. We are not diverging.
- **Cost of reversal**: medium. Iceberg tables CAN be exported back to plain Parquet via `INSERT OVERWRITE` into a new Hive-style table. But it requires re-running the pipeline once. Estimate: half a day of work to revert.
- **Early warning signal**: query latency on Athena increases by >2× compared to the plain Parquet baseline. Iceberg has slight overhead for manifest list reads — if that overhead is large for our scale, the trade-off was wrong.

## Decision

After ADR-0006 is in stable production for at least 2 weeks, we will **migrate the curated layer from plain Parquet to Apache Iceberg**. The staging layer remains plain Parquet (it is rebuilt frequently; Iceberg's strengths don't apply there).

### Migration scope

| Curated table | Migrate to Iceberg? | Reason |
|---|---|---|
| `fact_orders` | Yes | Receives late-arriving; MERGE is the killer feature |
| `fact_order_items` | Yes | Linked to fact_orders, same volatility |
| `fact_payments` | Yes | Same as above |
| `fact_reviews` | Yes | Same as above |
| `dim_date` | No | Static, rebuilt nightly, no benefit |
| `dim_currency` | No | Append-only by date, no benefit |
| `dim_customers` | Yes | Future SCD-2 use cases |
| `dim_products` | Yes | Future SCD-2 use cases |
| `dim_sellers` | Yes | Same as above |
| `dim_geolocation` | No | Static reference data |

### How the writes change

**Before (Phase A, ADR-0006)**:

```python
# Late-arriving forces partition rewrite
incoming = staging.filter(F.col("ingested_at") > hwm)
for partition in incoming.select("year", "month").distinct().collect():
    existing = spark.read.parquet(f"{curated_uri}/year={partition.year}/month={partition.month}/")
    merged = existing.union(incoming.filter(...)).dropDuplicates(["order_id"])
    merged.write.parquet(f"{curated_uri}/year={partition.year}/month={partition.month}/", mode="overwrite")
```

**After (Phase B, this ADR)**:

```sql
-- Single MERGE statement in Athena
MERGE INTO fact_orders AS target
USING (SELECT * FROM staging_fact_orders_delta) AS source
ON target.order_id = source.order_id
WHEN MATCHED THEN UPDATE SET
    order_status = source.order_status,
    delivered_date_id = source.delivered_date_id,
    delivery_delay_days = source.delivery_delay_days
WHEN NOT MATCHED THEN INSERT VALUES (
    source.order_id, source.customer_id, ...
)
```

Row-level upsert. No partition rewrites. Athena handles the manifest-level changes transparently.

### Time travel

```sql
-- "What did fact_orders look like at the end of March 2018?"
SELECT * FROM fact_orders
FOR TIMESTAMP AS OF TIMESTAMP '2018-03-31 23:59:59 UTC'
WHERE order_status = 'delivered';
```

This unlocks audit / reconciliation queries that are otherwise impossible.

### Schema evolution

```sql
-- Add a column without rewriting history
ALTER TABLE fact_orders ADD COLUMN promotion_code STRING;
```

In Phase A this required rewriting every partition. Iceberg makes it metadata-only.

## Consequences

### Positive

- **MERGE INTO** replaces partition-rewrites for late-arriving data. Row-level semantics. Much faster, no risk of losing rows during overwrite races.
- **Time travel** queries unlock auditing use cases.
- **Schema evolution** without data rewrites.
- **Hidden partitioning**: Iceberg can evolve partition schemes without breaking queries.
- **Snapshot isolation**: readers see a consistent view even if a write is in flight.
- **CV signal**: "I migrated curated layer from plain Parquet to Iceberg, documented the trade-offs in ADR-0007" is exactly what senior data engineering interviews probe.

### Negative

- **Operational overhead**: Iceberg snapshots accumulate. We need to schedule a maintenance Lambda that runs `CALL system.expire_snapshots('fact_orders', TIMESTAMP '...', 5)` weekly to prevent unbounded metadata growth.
- **Query cost**: Athena charges slightly more per TB scanned on Iceberg tables (manifest reads) — estimated +5–10%. At our scale this is cents.
- **Migration is a one-way door** without effort. Once on Iceberg, we are committed; reverting requires re-running the pipeline.
- **Learning curve**: 6–8 focused hours to understand snapshots, manifests, partition specs, hidden partitioning, retention policies.

### Neutral / open questions

- Do we use Iceberg's hidden partitioning or stick with explicit `year`/`month`? Decision deferred to implementation; default to explicit for transparency in Phase B.
- Snapshot retention policy: 7 days for snapshots, 30 days for manifest files? Decision deferred.

## Alternatives considered

### Stay on plain Parquet + HWM forever

Accept the partition-rewrite cost as a permanent operational pattern. **Rejected because**: at scale this becomes the bottleneck, the operational pattern doesn't match current industry standards, and the CV signal of "migrated to Iceberg" is exactly what makes the difference between mid-level and senior in interviews.

### Delta Lake

Functionally equivalent to Iceberg. **Rejected because**: AWS made Iceberg the first-class format for Athena. Delta Lake on AWS works but requires extra setup (Delta Universal Format, more conversion friction). Iceberg is the path of least resistance for AWS-native portfolio.

### Apache Hudi

Hudi has merits, especially with Glue Job Bookmarks integration. **Rejected because**: less momentum on AWS in 2026 vs Iceberg, fewer Athena-side optimizations, and the community has consolidated on Iceberg for new green-field projects.

### Snowflake or BigQuery

Move the warehouse to a managed solution. **Rejected because**: the project's premise is AWS-native architecture; switching warehouses is out of scope and inflates cost.

## When to flip Status to Accepted

This ADR is `Proposed` until:

1. ADR-0006 (HWM pattern) is fully implemented and at least 2 weeks of stable runs are recorded.
2. At least 3 late-arriving simulations have been run successfully under Phase A — the team has lived with the partition-rewrite cost long enough to appreciate what MERGE solves.
3. A spike branch (`feature/iceberg-poc`) has demonstrated a working Iceberg table for `fact_orders` queryable from Athena.

When all three are true, this ADR's Status changes to `Accepted` and the migration work starts.

## References

- [Apache Iceberg](https://iceberg.apache.org/)
- [Athena support for Iceberg](https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg.html)
- [Glue support for Iceberg](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-etl-format-iceberg.html)
- [Netflix's migration story (original Iceberg motivation)](https://netflixtechblog.com/)
- **Companion**: ADR-0006 (the Phase A baseline that this evolves)
- **Companion**: `docs/INCREMENTAL_LOADS.md` (operational guide for both phases)
