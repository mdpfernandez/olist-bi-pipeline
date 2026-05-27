"""Integration tests for the Kaggle-to-S3 ingestion run (AWS mocked with moto)."""

from __future__ import annotations

import gzip
from collections.abc import Callable
from pathlib import Path

import pytest
from moto import mock_aws

from olist_pipeline.core.aws import S3Client, s3_client
from olist_pipeline.core.config import Settings
from olist_pipeline.ingestion import kaggle_to_s3
from olist_pipeline.ingestion.kaggle_to_s3 import SOURCE_CSV_FILENAMES, build_s3_key, run


def _fake_download_from(
    zip_source: Path,
) -> Callable[[Path, str, object], Path]:
    """Build a ``download_dataset`` replacement that yields a copy of ``zip_source``."""

    def fake_download(workdir: Path, _kaggle_api_token: str, _log: object) -> Path:
        destination = workdir / "olist.zip"
        destination.write_bytes(zip_source.read_bytes())
        return destination

    return fake_download


def _create_raw_bucket(settings: Settings) -> S3Client:
    s3 = s3_client(settings)
    s3.create_bucket(
        Bucket=settings.s3_bucket_raw,
        CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
    )
    return s3


@pytest.mark.integration
@mock_aws
def test_run_uploads_all_nine_tables(
    aws_ready_settings: Settings,
    synthetic_olist_zip: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s3 = _create_raw_bucket(aws_ready_settings)
    monkeypatch.setattr(kaggle_to_s3, "download_dataset", _fake_download_from(synthetic_olist_zip))

    report = run(aws_ready_settings)

    assert report.uploaded_count == 9
    assert report.skipped_count == 0
    listed = s3.list_objects_v2(Bucket=aws_ready_settings.s3_bucket_raw)
    keys = {obj["Key"] for obj in listed["Contents"]}
    assert keys == {build_s3_key(table, report.ingested_at) for table in SOURCE_CSV_FILENAMES}


@pytest.mark.integration
@mock_aws
def test_rerun_on_same_day_is_idempotent(
    aws_ready_settings: Settings,
    synthetic_olist_zip: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_raw_bucket(aws_ready_settings)
    monkeypatch.setattr(kaggle_to_s3, "download_dataset", _fake_download_from(synthetic_olist_zip))

    first = run(aws_ready_settings)
    second = run(aws_ready_settings)

    assert first.uploaded_count == 9
    assert second.uploaded_count == 0
    assert second.skipped_count == 9


@pytest.mark.integration
@mock_aws
def test_uploaded_objects_carry_three_mandatory_tags(
    aws_ready_settings: Settings,
    synthetic_olist_zip: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s3 = _create_raw_bucket(aws_ready_settings)
    monkeypatch.setattr(kaggle_to_s3, "download_dataset", _fake_download_from(synthetic_olist_zip))

    report = run(aws_ready_settings)

    key = build_s3_key("orders", report.ingested_at)
    tagset = s3.get_object_tagging(Bucket=aws_ready_settings.s3_bucket_raw, Key=key)["TagSet"]
    tags = {tag["Key"]: tag["Value"] for tag in tagset}
    assert tags == {"project": "olist-pipeline", "env": "dev", "owner": "marianela"}


@pytest.mark.integration
@mock_aws
def test_uploaded_objects_are_gzip_encoded(
    aws_ready_settings: Settings,
    synthetic_olist_zip: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s3 = _create_raw_bucket(aws_ready_settings)
    monkeypatch.setattr(kaggle_to_s3, "download_dataset", _fake_download_from(synthetic_olist_zip))

    report = run(aws_ready_settings)

    key = build_s3_key("orders", report.ingested_at)
    obj = s3.get_object(Bucket=aws_ready_settings.s3_bucket_raw, Key=key)
    assert obj["ContentEncoding"] == "gzip"
    assert gzip.decompress(obj["Body"].read()) == b"col_a,col_b\n1,2\n"
