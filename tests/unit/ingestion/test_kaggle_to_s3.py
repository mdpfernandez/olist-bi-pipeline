"""Unit tests for olist_pipeline.ingestion.kaggle_to_s3 (pure functions, no AWS)."""

from __future__ import annotations

import gzip
import zipfile
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from olist_pipeline.core.logging import get_logger
from olist_pipeline.ingestion.kaggle_to_s3 import (
    SOURCE_CSV_FILENAMES,
    CorruptArchiveError,
    MissingTablesError,
    build_s3_key,
    extract_and_validate,
    gzip_csv,
)


@pytest.mark.unit
def test_build_s3_key_follows_raw_layout() -> None:
    assert (
        build_s3_key("orders", "2026-05-19") == "source=orders/ingested_at=2026-05-19/orders.csv.gz"
    )


@pytest.mark.unit
def test_extract_and_validate_returns_nine_tables(
    synthetic_olist_zip: Path, tmp_path: Path
) -> None:
    result = extract_and_validate(synthetic_olist_zip, tmp_path / "out", get_logger("test"))
    assert set(result) == set(SOURCE_CSV_FILENAMES)
    assert all(path.exists() for path in result.values())


@pytest.mark.unit
def test_missing_table_raises(tmp_path: Path) -> None:
    archive = tmp_path / "incomplete.zip"
    filenames = list(SOURCE_CSV_FILENAMES.values())[:-1]
    with zipfile.ZipFile(archive, "w") as zf:
        for filename in filenames:
            zf.writestr(filename, "a,b\n1,2\n")
    with pytest.raises(MissingTablesError):
        extract_and_validate(archive, tmp_path / "out", get_logger("test"))


@pytest.mark.unit
def test_corrupt_archive_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"definitely not a zip file")
    with pytest.raises(CorruptArchiveError):
        extract_and_validate(bad, tmp_path / "out", get_logger("test"))


@pytest.mark.unit
def test_unexpected_file_warns_but_succeeds(tmp_path: Path) -> None:
    archive = tmp_path / "extra.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for filename in SOURCE_CSV_FILENAMES.values():
            zf.writestr(filename, "a,b\n1,2\n")
        zf.writestr("surprise_table.csv", "x\n1\n")

    with capture_logs() as logs:
        result = extract_and_validate(archive, tmp_path / "out", get_logger("test"))

    assert len(result) == 9
    assert any(e.get("event") == "kaggle.extract.unexpected_files" for e in logs)


@pytest.mark.unit
def test_gzip_csv_roundtrip(tmp_path: Path) -> None:
    csv = tmp_path / "sample.csv"
    csv.write_bytes(b"col_a,col_b\n1,2\n")
    gz = gzip_csv(csv)
    assert gz.name == "sample.csv.gz"
    assert gzip.decompress(gz.read_bytes()) == b"col_a,col_b\n1,2\n"
