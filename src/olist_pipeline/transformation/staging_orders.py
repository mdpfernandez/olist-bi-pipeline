"""Pure Spark transformation: raw orders (CSV) -> staging-ready DataFrame.

``transform_orders`` takes the DataFrame as it would come from
``spark.read.csv(header=True)`` over the raw layer, plus the previous run's
ingestion high-watermark, and returns a typed, deduplicated DataFrame with
``year`` and ``month`` partition columns appended -- ready to write to
staging in Parquet+Snappy.

The module is intentionally pure: no IO, no AWS clients, no env reads. The
Glue Job wrapper in ``infra/glue-jobs/`` is the side-effectful adapter; this
module is what the unit tests exercise locally.
"""

from __future__ import annotations

from datetime import datetime

from pyspark.sql import DataFrame
from pyspark.sql import functions as F  # noqa: N812 -- `F` is the canonical PySpark alias
from pyspark.sql.window import Window

# Olist orders primary key -- used for dedup.
PRIMARY_KEY = "order_id"

# Olist CSV timestamp format -- consistent across all five timestamp columns.
TIMESTAMP_FORMAT = "yyyy-MM-dd HH:mm:ss"

# Columns we cast from string to TimestampType.
TIMESTAMP_COLUMNS: tuple[str, ...] = (
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
)


def transform_orders(raw: DataFrame, ingestion_hwm: datetime) -> DataFrame:
    """Transform raw orders into the staging-ready shape.

    Steps applied, in order:

    1. **HWM filter.** Drop rows whose ``ingested_at`` partition is at or
       below the previous high-watermark. Spark applies the predicate at
       partition-prune time, so only the new ingestion days are scanned.
    2. **Type casts.** Convert the five timestamp columns from string to
       ``TimestampType`` using the Olist CSV format.
    3. **Dedup.** Keep the latest row per ``order_id`` (by ``ingested_at``
       desc) -- a late-arriving fix for an existing order wins over an
       earlier copy.
    4. **Output partition columns.** Derive ``year`` and ``month`` from
       ``order_purchase_timestamp`` for downstream partition-by writes.

    Parameters
    ----------
    raw:
        DataFrame with the columns of the Olist ``orders`` CSV plus a
        Hive-discovered ``ingested_at`` partition column (as string).
    ingestion_hwm:
        The previous run's ingestion watermark. Pass ``hwm.EPOCH`` on the
        very first run.

    Returns
    -------
    DataFrame with typed columns, deduplicated, and the ``year`` / ``month``
    partition columns appended. The returned frame is lazy -- no Spark action
    has run.
    """
    hwm_date = ingestion_hwm.date().isoformat()
    new_rows = raw.where(F.col("ingested_at") > F.lit(hwm_date))

    typed = new_rows
    for column in TIMESTAMP_COLUMNS:
        typed = typed.withColumn(column, F.to_timestamp(F.col(column), TIMESTAMP_FORMAT))

    dedup_window = Window.partitionBy(PRIMARY_KEY).orderBy(F.col("ingested_at").desc())
    deduped = (
        typed.withColumn("_dedup_rn", F.row_number().over(dedup_window))
        .where(F.col("_dedup_rn") == 1)
        .drop("_dedup_rn")
    )

    return deduped.withColumn("year", F.year("order_purchase_timestamp")).withColumn(
        "month", F.month("order_purchase_timestamp")
    )
