"""AWS Glue Job adapter for the staging-orders transformation.

Thin wrapper around ``olist_pipeline.transformation.staging_orders.transform_orders``:

  1. Parse Glue Job arguments (``getResolvedOptions``).
  2. Read the HWM state file from the staging bucket.
  3. Read raw orders CSVs directly with ``spark.read.csv(header=True)`` --
     bypassing the raw Catalog tables (which have ``col0..col7`` due to a
     Glue Crawler quirk -- see ``docs/architecture.md``).
  4. Apply the pure transformation.
  5. Write Parquet+Snappy partitioned by ``year``/``month`` using DYNAMIC
     partition overwrite (only the partitions in the current batch are
     replaced -- previous months stay).
  6. Write a ``_SUCCESS`` marker (triggers downstream Lambda per ADR-0003).
  7. Atomically update the HWM state file with the new watermarks.

The Glue runtime injects ``awsglue.*`` and ``pyspark.*``. Project code is
delivered via ``--extra-py-files`` (a zip of ``src/olist_pipeline/`` uploaded
by ``infra/create-glue-job-staging-orders.sh``).

Note on boto3: Glue 5.0 ships an older botocore that lacks the
``IfMatch``/``IfNoneMatch`` parameters for ``put_object`` (S3 conditional
writes are a late-2024 feature). The job spec installs boto3>=1.36 via
``--additional-python-modules`` so the atomic HWM state-file writes work.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

import boto3
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import functions as F  # noqa: N812

from olist_pipeline.transformation.hwm import (
    EPOCH,
    HwmState,
    LastRun,
    RunStats,
    Watermarks,
    read_state,
    write_state,
)
from olist_pipeline.transformation.staging_orders import transform_orders

LAYER = "staging"
TABLE = "orders"
STATE_KEY = f"_metadata/{LAYER}_{TABLE}_state.json"
SOURCE_PREFIX = f"source={TABLE}/"
SUCCESS_KEY = f"{SOURCE_PREFIX}_SUCCESS"

# Tags applied to objects this Job creates. Kept as a constant to avoid a
# dependency on the Settings object (which is .env-driven and not available
# inside Glue). The values match `.claude/skills/aws-cost-discipline/SKILL.md`.
TAG_QUERYSTRING = "project=olist-pipeline&env=dev&owner=marianela"


def main() -> None:
    args = getResolvedOptions(
        sys.argv,
        ["JOB_NAME", "S3_BUCKET_RAW", "S3_BUCKET_STAGING"],
    )

    sc = SparkContext.getOrCreate()
    glue_context = GlueContext(sc)
    spark = glue_context.spark_session
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)

    # Dynamic partition overwrite: only the (year, month) partitions touched
    # by this batch get replaced. Without this, every run would wipe the
    # entire staging table -- catastrophic for incremental loads.
    spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")

    # Keep Hive partition values as strings. Without this Spark infers
    # `ingested_at=2026-05-22` as DateType, which breaks our string
    # comparisons in `transform_orders` and our string parsing in the
    # watermark computation below.
    spark.conf.set("spark.sql.sources.partitionColumnTypeInference.enabled", "false")

    raw_bucket = args["S3_BUCKET_RAW"]
    staging_bucket = args["S3_BUCKET_STAGING"]
    s3 = boto3.client("s3")

    # 1. Read HWM state (epoch on first run).
    snapshot = read_state(s3, staging_bucket, STATE_KEY, layer=LAYER, table=TABLE)
    previous_state = snapshot.state
    previous_etag = snapshot.etag

    # 2. Read raw with header=True. Hive partition discovery picks up
    # `ingested_at` automatically because the path uses `key=value/`.
    raw_uri = f"s3://{raw_bucket}/{SOURCE_PREFIX}"
    raw_df = (
        spark.read.option("header", "true").option("quote", '"').option("escape", '"').csv(raw_uri)
    )

    # 3. Apply the pure transformation.
    transformed = transform_orders(raw_df, previous_state.watermarks.ingestion_hwm)
    transformed.cache()  # write + aggregate -- cache to avoid recomputation.

    row_count = transformed.count()
    if row_count == 0:
        print("[staging_orders] no new rows since last HWM; nothing to write.")
        job.commit()
        return

    # 4. Write Parquet+Snappy partitioned by year/month (dynamic overwrite).
    staging_uri = f"s3://{staging_bucket}/{SOURCE_PREFIX}"
    (
        transformed.write.mode("overwrite")
        .format("parquet")
        .option("compression", "snappy")
        .partitionBy("year", "month")
        .save(staging_uri)
    )

    # 5. Write the _SUCCESS marker. Downstream Lambdas (ADR-0003) watch for
    # this PUT to trigger the next step.
    s3.put_object(
        Bucket=staging_bucket,
        Key=SUCCESS_KEY,
        Body=b"",
        Tagging=TAG_QUERYSTRING,
    )

    # 6. Compute new watermarks from the batch.
    agg_row = transformed.agg(
        F.max("ingested_at").alias("max_ingested"),
        F.max("order_purchase_timestamp").alias("max_purchase"),
    ).first()
    new_ingestion_hwm = datetime.fromisoformat(agg_row["max_ingested"]).replace(tzinfo=UTC)
    if agg_row["max_purchase"] is not None:
        new_business_hwm = agg_row["max_purchase"].replace(tzinfo=UTC)
    else:
        new_business_hwm = previous_state.watermarks.business_hwm

    # 7. Count late-arriving rows (only meaningful after the first run).
    if previous_state.watermarks.business_hwm > EPOCH:
        late_arriving = transformed.where(
            F.col("order_purchase_timestamp") < F.lit(previous_state.watermarks.business_hwm)
        ).count()
    else:
        late_arriving = 0

    # 8. Capture partitions touched (for audit / monitoring).
    touched_rows = transformed.select("year", "month").distinct().collect()
    partitions_touched = sorted({f"year={r.year}/month={r.month}" for r in touched_rows})

    # 9. Atomic state update. expected_etag comes from the read above so a
    # concurrent writer is detected and we abort instead of overwriting.
    new_state = HwmState(
        layer=LAYER,
        table=TABLE,
        watermarks=Watermarks(
            ingestion_hwm=new_ingestion_hwm,
            business_hwm=new_business_hwm,
        ),
        last_run=LastRun(
            run_id=f"{args['JOB_NAME']}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
            completed_at=datetime.now(UTC),
            status="success",
        ),
        stats=RunStats(
            rows_processed=row_count,
            rows_late_arriving=late_arriving,
            partitions_touched=partitions_touched,
        ),
    )
    write_state(
        s3,
        staging_bucket,
        STATE_KEY,
        new_state,
        expected_etag=previous_etag,
        tagging=TAG_QUERYSTRING,
    )

    print(
        f"[staging_orders] wrote {row_count} rows across {len(partitions_touched)} "
        f"partitions; late-arriving={late_arriving}; "
        f"new_ingestion_hwm={new_ingestion_hwm.isoformat()}"
    )
    job.commit()


if __name__ == "__main__":
    main()
