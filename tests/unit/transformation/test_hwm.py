"""Unit tests for the HWM state file helpers (moto-mocked S3)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from moto import mock_aws

from olist_pipeline.core.aws import S3Client, s3_client, s3_tagging_querystring
from olist_pipeline.core.config import Settings
from olist_pipeline.transformation.hwm import (
    EPOCH,
    HwmState,
    LastRun,
    RunStats,
    StateConflictError,
    Watermarks,
    read_state,
    write_state,
)

STATE_KEY = "_metadata/staging_orders_state.json"


@pytest.fixture
def staging_s3(aws_ready_settings: Settings) -> Iterator[S3Client]:
    """Spin up a moto S3 with the staging bucket already created."""
    with mock_aws():
        s3 = s3_client(aws_ready_settings)
        s3.create_bucket(
            Bucket=aws_ready_settings.s3_bucket_staging,
            CreateBucketConfiguration={"LocationConstraint": aws_ready_settings.aws_region},
        )
        yield s3


def _sample_state() -> HwmState:
    """An HwmState that exercises every field, for round-trip tests."""
    return HwmState(
        layer="staging",
        table="orders",
        watermarks=Watermarks(
            ingestion_hwm=datetime(2026, 5, 22, 6, 0, 0, tzinfo=UTC),
            business_hwm=datetime(2018, 4, 30, 23, 59, 59, tzinfo=UTC),
        ),
        last_run=LastRun(
            run_id="2026-05-22T06:00:00Z-run42",
            completed_at=datetime(2026, 5, 22, 6, 14, 32, tzinfo=UTC),
            status="success",
        ),
        stats=RunStats(
            rows_processed=8421,
            rows_late_arriving=0,
            partitions_touched=["year=2018/month=04"],
        ),
    )


@pytest.mark.integration
def test_read_returns_initial_when_file_missing(
    staging_s3: S3Client, aws_ready_settings: Settings
) -> None:
    snapshot = read_state(
        staging_s3,
        aws_ready_settings.s3_bucket_staging,
        STATE_KEY,
        layer="staging",
        table="orders",
    )
    assert snapshot.etag is None
    assert snapshot.state.watermarks.ingestion_hwm == EPOCH
    assert snapshot.state.watermarks.business_hwm == EPOCH
    assert snapshot.state.last_run is None


@pytest.mark.integration
def test_write_then_read_roundtrip(staging_s3: S3Client, aws_ready_settings: Settings) -> None:
    state = _sample_state()
    etag = write_state(
        staging_s3,
        aws_ready_settings.s3_bucket_staging,
        STATE_KEY,
        state=state,
        expected_etag=None,
    )
    assert etag

    snapshot = read_state(
        staging_s3,
        aws_ready_settings.s3_bucket_staging,
        STATE_KEY,
        layer="staging",
        table="orders",
    )
    assert snapshot.etag == etag
    assert snapshot.state.layer == state.layer
    assert snapshot.state.table == state.table
    assert snapshot.state.watermarks == state.watermarks
    assert snapshot.state.last_run == state.last_run
    assert snapshot.state.stats.rows_processed == state.stats.rows_processed
    assert snapshot.state.stats.partitions_touched == state.stats.partitions_touched


@pytest.mark.integration
def test_first_write_with_none_etag_fails_when_object_exists(
    staging_s3: S3Client, aws_ready_settings: Settings
) -> None:
    state = _sample_state()
    write_state(
        staging_s3,
        aws_ready_settings.s3_bucket_staging,
        STATE_KEY,
        state=state,
        expected_etag=None,
    )

    with pytest.raises(StateConflictError):
        write_state(
            staging_s3,
            aws_ready_settings.s3_bucket_staging,
            STATE_KEY,
            state=state,
            expected_etag=None,
        )


@pytest.mark.integration
def test_write_with_stale_etag_raises_conflict_error(
    staging_s3: S3Client, aws_ready_settings: Settings
) -> None:
    state = _sample_state()
    write_state(
        staging_s3,
        aws_ready_settings.s3_bucket_staging,
        STATE_KEY,
        state=state,
        expected_etag=None,
    )

    stale_etag = "0123456789abcdef0123456789abcdef"
    with pytest.raises(StateConflictError):
        write_state(
            staging_s3,
            aws_ready_settings.s3_bucket_staging,
            STATE_KEY,
            state=state,
            expected_etag=stale_etag,
        )


@pytest.mark.integration
def test_write_with_fresh_etag_succeeds(staging_s3: S3Client, aws_ready_settings: Settings) -> None:
    state = _sample_state()
    first_etag = write_state(
        staging_s3,
        aws_ready_settings.s3_bucket_staging,
        STATE_KEY,
        state=state,
        expected_etag=None,
    )

    advanced = HwmState(
        layer=state.layer,
        table=state.table,
        watermarks=Watermarks(
            ingestion_hwm=datetime(2026, 5, 23, 6, 0, 0, tzinfo=UTC),
            business_hwm=state.watermarks.business_hwm,
        ),
    )
    new_etag = write_state(
        staging_s3,
        aws_ready_settings.s3_bucket_staging,
        STATE_KEY,
        state=advanced,
        expected_etag=first_etag,
    )
    assert new_etag != first_etag


@pytest.mark.integration
def test_state_file_carries_three_mandatory_tags(
    staging_s3: S3Client, aws_ready_settings: Settings
) -> None:
    state = _sample_state()
    write_state(
        staging_s3,
        aws_ready_settings.s3_bucket_staging,
        STATE_KEY,
        state=state,
        expected_etag=None,
        tagging=s3_tagging_querystring(aws_ready_settings),
    )

    response = staging_s3.get_object_tagging(
        Bucket=aws_ready_settings.s3_bucket_staging, Key=STATE_KEY
    )
    tags = {item["Key"]: item["Value"] for item in response["TagSet"]}
    assert tags == {"project": "olist-pipeline", "env": "dev", "owner": "marianela"}


@pytest.mark.integration
def test_serialized_payload_matches_adr_0006_shape(
    staging_s3: S3Client, aws_ready_settings: Settings
) -> None:
    state = _sample_state()
    write_state(
        staging_s3,
        aws_ready_settings.s3_bucket_staging,
        STATE_KEY,
        state=state,
        expected_etag=None,
    )

    body = staging_s3.get_object(Bucket=aws_ready_settings.s3_bucket_staging, Key=STATE_KEY)[
        "Body"
    ].read()
    document = json.loads(body)

    assert document["layer"] == "staging"
    assert document["table"] == "orders"
    assert document["watermarks"]["ingestion_hwm"].endswith("Z")
    assert document["watermarks"]["business_hwm"].endswith("Z")
    assert document["last_run"]["status"] == "success"
    assert document["stats"]["rows_processed"] == 8421
