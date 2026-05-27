"""Unit tests for the staging orders Spark transformation.

These tests need a local SparkSession. If pyspark is not installed or Java
is missing, the ``spark`` fixture (see ``conftest.py``) skips the entire
module with a clear message.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pyspark")

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from olist_pipeline.transformation.hwm import EPOCH
from olist_pipeline.transformation.staging_orders import (
    TIMESTAMP_COLUMNS,
    transform_orders,
)

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

# Column order of the raw orders DataFrame as it comes from
# ``spark.read.csv(header=True)`` on the raw bucket. ``ingested_at`` is the
# Hive-discovered partition column appended at the end.
RAW_SCHEMA: list[str] = [
    "order_id",
    "customer_id",
    "order_status",
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
    "ingested_at",
]


def _row(
    order_id: str,
    status: str,
    purchase_ts: str,
    ingested_at: str,
    customer_id: str = "cust1",
) -> tuple[str | None, ...]:
    """Build a raw orders row with sensible defaults for the timestamp columns."""
    return (
        order_id,
        customer_id,
        status,
        purchase_ts,
        "2017-10-02 11:07:15",
        "2017-10-04 19:55:00",
        "2017-10-10 21:25:13",
        "2017-10-18 00:00:00",
        ingested_at,
    )


@pytest.mark.unit
def test_transform_filters_by_hwm(spark: SparkSession) -> None:
    rows = [
        _row("ord-old", "delivered", "2017-10-02 10:56:33", "2026-05-15"),
        _row("ord-new", "delivered", "2017-10-02 10:56:33", "2026-05-22"),
    ]
    df = spark.createDataFrame(rows, schema=RAW_SCHEMA)

    hwm = datetime(2026, 5, 20, tzinfo=UTC)
    result = transform_orders(df, hwm).collect()

    assert len(result) == 1
    assert result[0].order_id == "ord-new"


@pytest.mark.unit
def test_transform_keeps_everything_when_hwm_is_epoch(spark: SparkSession) -> None:
    rows = [
        _row("ord-a", "delivered", "2017-10-02 10:56:33", "2026-05-15"),
        _row("ord-b", "delivered", "2017-11-15 09:00:00", "2026-05-22"),
    ]
    df = spark.createDataFrame(rows, schema=RAW_SCHEMA)

    result = transform_orders(df, EPOCH).collect()
    assert len(result) == 2


@pytest.mark.unit
def test_transform_casts_timestamp_columns(spark: SparkSession) -> None:
    df = spark.createDataFrame(
        [_row("ord1", "delivered", "2017-10-02 10:56:33", "2026-05-22")],
        schema=RAW_SCHEMA,
    )

    result = transform_orders(df, EPOCH)

    dtypes = dict(result.dtypes)
    for column in TIMESTAMP_COLUMNS:
        assert dtypes[column] == "timestamp", f"{column} kept type {dtypes[column]}"


@pytest.mark.unit
def test_transform_dedups_keeping_latest_by_ingested_at(spark: SparkSession) -> None:
    rows = [
        # Same order_id in two ingest partitions. The later partition wins.
        _row("ord1", "processing", "2017-10-02 10:56:33", "2026-05-15"),
        _row("ord1", "delivered", "2017-10-02 10:56:33", "2026-05-22"),
    ]
    df = spark.createDataFrame(rows, schema=RAW_SCHEMA)

    result = transform_orders(df, EPOCH).collect()
    assert len(result) == 1
    assert result[0].order_status == "delivered"
    assert result[0].ingested_at == "2026-05-22"


@pytest.mark.unit
def test_transform_derives_year_and_month_for_partitioning(spark: SparkSession) -> None:
    rows = [
        _row("ord-oct", "delivered", "2017-10-02 10:56:33", "2026-05-22"),
        _row("ord-nov", "delivered", "2017-11-15 09:00:00", "2026-05-22"),
    ]
    df = spark.createDataFrame(rows, schema=RAW_SCHEMA)

    by_id = {row.order_id: row for row in transform_orders(df, EPOCH).collect()}
    assert by_id["ord-oct"].year == 2017
    assert by_id["ord-oct"].month == 10
    assert by_id["ord-nov"].year == 2017
    assert by_id["ord-nov"].month == 11


@pytest.mark.unit
def test_transform_returns_empty_frame_when_nothing_new(spark: SparkSession) -> None:
    rows = [_row("ord1", "delivered", "2017-10-02 10:56:33", "2026-05-15")]
    df = spark.createDataFrame(rows, schema=RAW_SCHEMA)

    hwm = datetime(2026, 5, 22, tzinfo=UTC)
    assert transform_orders(df, hwm).count() == 0
