"""Download the Brazilian Olist dataset from Kaggle and upload it to the S3 raw layer.

The raw layer is append-only (ADR-0002): every run writes into a partition
keyed by ingest date --

    source=<table>/ingested_at=<YYYY-MM-DD>/<table>.csv.gz

Re-running on the same day is idempotent: objects that already exist are
skipped, never re-uploaded. A run on a later day lands in a fresh
``ingested_at=`` partition, so history is preserved.

Run from the project root:

    uv run python -m olist_pipeline.ingestion.kaggle_to_s3
"""

from __future__ import annotations

import gzip
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from botocore.exceptions import ClientError
from structlog.typing import FilteringBoundLogger

from olist_pipeline.core.aws import S3Client, s3_client, s3_tagging_querystring
from olist_pipeline.core.config import Settings, get_settings
from olist_pipeline.core.logging import configure_logging, get_logger

KAGGLE_DATASET = "olistbr/brazilian-ecommerce"

# Canonical table name -> CSV file name inside the Kaggle archive. An explicit
# map (rather than a regex) is deliberate: eight files follow the
# `olist_<name>_dataset.csv` pattern but `product_category_name_translation`
# does not.
SOURCE_CSV_FILENAMES: dict[str, str] = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "product_category_name_translation": "product_category_name_translation.csv",
}


class IngestionError(Exception):
    """Base error for the Kaggle-to-S3 ingestion module."""


class CorruptArchiveError(IngestionError):
    """The downloaded file is not a readable zip archive."""


class MissingTablesError(IngestionError):
    """The Kaggle archive does not contain all nine expected tables."""


class UploadStatus(StrEnum):
    """Outcome of attempting to upload one table to S3."""

    UPLOADED = "uploaded"
    SKIPPED = "skipped"


@dataclass
class TableUpload:
    """Result of handling a single source table."""

    table: str
    s3_key: str
    status: UploadStatus
    size_bytes: int


@dataclass
class IngestReport:
    """Summary of one ingestion run, logged and returned by ``run()``."""

    ingested_at: str
    uploads: list[TableUpload] = field(default_factory=list)

    @property
    def uploaded_count(self) -> int:
        return sum(1 for u in self.uploads if u.status is UploadStatus.UPLOADED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for u in self.uploads if u.status is UploadStatus.SKIPPED)

    @property
    def total_bytes(self) -> int:
        return sum(u.size_bytes for u in self.uploads)


def build_s3_key(table: str, ingested_at: str) -> str:
    """Return the raw-layer S3 key for a table at a given ingest date."""
    return f"source={table}/ingested_at={ingested_at}/{table}.csv.gz"


def download_dataset(
    workdir: Path,
    kaggle_api_token: str,
    log: FilteringBoundLogger,
) -> Path:
    """Download the Olist dataset archive from Kaggle into ``workdir``.

    Authenticates via ``KAGGLE_API_TOKEN`` (the single-token scheme Kaggle
    moved to in 2024; the older ``KAGGLE_USERNAME`` + ``KAGGLE_KEY`` pair is
    no longer issued). The ``kaggle`` library is imported lazily because
    importing it eagerly resolves credentials, which would break test
    collection on machines without a token.
    """
    os.environ["KAGGLE_API_TOKEN"] = kaggle_api_token

    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()

    log.info("kaggle.download.start", dataset=KAGGLE_DATASET)
    api.dataset_download_files(KAGGLE_DATASET, path=str(workdir), unzip=False, quiet=True)

    archives = list(workdir.glob("*.zip"))
    if len(archives) != 1:
        raise IngestionError(
            f"expected exactly one downloaded zip in {workdir}, found {len(archives)}"
        )
    zip_path = archives[0]
    log.info("kaggle.download.done", zip=zip_path.name, size_bytes=zip_path.stat().st_size)
    return zip_path


def extract_and_validate(
    zip_path: Path,
    dest: Path,
    log: FilteringBoundLogger,
) -> dict[str, Path]:
    """Extract the archive into ``dest`` and confirm all nine tables are present.

    Returns a map of table name -> extracted CSV path. Raises if the archive is
    unreadable or a table is missing; unexpected extra files only warn.
    """
    if not zipfile.is_zipfile(zip_path):
        raise CorruptArchiveError(f"{zip_path} is not a valid zip archive")

    with zipfile.ZipFile(zip_path) as archive:
        members = set(archive.namelist())
        archive.extractall(dest)

    expected = set(SOURCE_CSV_FILENAMES.values())
    missing = expected - members
    if missing:
        raise MissingTablesError(f"Kaggle archive is missing expected tables: {sorted(missing)}")

    unexpected = members - expected
    if unexpected:
        log.warning("kaggle.extract.unexpected_files", files=sorted(unexpected))

    log.info("kaggle.extract.done", tables=len(SOURCE_CSV_FILENAMES))
    return {table: dest / fname for table, fname in SOURCE_CSV_FILENAMES.items()}


def gzip_csv(csv_path: Path) -> Path:
    """Compress a CSV with gzip alongside the original; return the ``.gz`` path."""
    gz_path = csv_path.with_suffix(csv_path.suffix + ".gz")
    with csv_path.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    return gz_path


def _object_exists(s3: S3Client, bucket: str, key: str) -> bool:
    """Return whether an object already exists at ``key`` in ``bucket``."""
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"404", "NoSuchKey"}:
            return False
        raise
    return True


def upload_table(
    s3: S3Client,
    bucket: str,
    table: str,
    csv_gz_path: Path,
    ingested_at: str,
    tagging: str,
    log: FilteringBoundLogger,
) -> TableUpload:
    """Upload one gzipped table to the raw layer, skipping it if already present."""
    key = build_s3_key(table, ingested_at)
    size_bytes = csv_gz_path.stat().st_size

    if _object_exists(s3, bucket, key):
        log.info("s3.upload.skip", table=table, key=key, reason="already present")
        return TableUpload(table, key, UploadStatus.SKIPPED, size_bytes)

    with csv_gz_path.open("rb") as body:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="text/csv",
            ContentEncoding="gzip",
            Tagging=tagging,
        )
    log.info("s3.upload.done", table=table, key=key, size_bytes=size_bytes)
    return TableUpload(table, key, UploadStatus.UPLOADED, size_bytes)


def run(settings: Settings | None = None) -> IngestReport:
    """Download the Olist dataset and upload all nine tables to the raw layer."""
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    log = get_logger("ingestion.kaggle_to_s3")

    ingested_at = datetime.now(UTC).date().isoformat()
    report = IngestReport(ingested_at=ingested_at)
    log.info(
        "ingestion.start",
        dataset=KAGGLE_DATASET,
        bucket=settings.s3_bucket_raw,
        ingested_at=ingested_at,
    )

    s3 = s3_client(settings)
    tagging = s3_tagging_querystring(settings)

    with tempfile.TemporaryDirectory(prefix="olist-ingest-") as tmp:
        workdir = Path(tmp)
        zip_path = download_dataset(workdir, settings.kaggle_api_token, log)
        csv_paths = extract_and_validate(zip_path, workdir / "extracted", log)

        for table, csv_path in csv_paths.items():
            gz_path = gzip_csv(csv_path)
            outcome = upload_table(
                s3, settings.s3_bucket_raw, table, gz_path, ingested_at, tagging, log
            )
            report.uploads.append(outcome)

    log.info(
        "ingestion.done",
        uploaded=report.uploaded_count,
        skipped=report.skipped_count,
        total_bytes=report.total_bytes,
    )
    return report


def main() -> int:
    """CLI entry point. Returns a process exit code."""
    try:
        report = run()
    except IngestionError as exc:
        get_logger("ingestion.kaggle_to_s3").error("ingestion.failed", error=str(exc))
        return 1

    print(f"\nIngestion report for {report.ingested_at}")
    print(f"  uploaded: {report.uploaded_count}")
    print(f"  skipped:  {report.skipped_count}")
    print(f"  total:    {report.total_bytes:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
