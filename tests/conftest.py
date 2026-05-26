"""Shared pytest fixtures for the olist-bi-pipeline test suite."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from olist_pipeline.core.config import Settings
from olist_pipeline.ingestion.kaggle_to_s3 import SOURCE_CSV_FILENAMES

# A complete, valid set of project settings -- buckets and Kaggle credentials
# deliberately avoid the `.env.example` placeholder values so validation passes.
_TEST_ENV: dict[str, str] = {
    "AWS_PROFILE": "test-profile",
    "AWS_REGION": "eu-west-1",
    "AWS_ACCOUNT_ID": "123456789012",
    "S3_BUCKET_RAW": "olist-raw-test-01",
    "S3_BUCKET_STAGING": "olist-staging-test-01",
    "S3_BUCKET_CURATED": "olist-curated-test-01",
    "S3_BUCKET_ATHENA_RESULTS": "olist-athena-results-test-01",
    "GLUE_DATABASE": "olist_dev",
    "GLUE_ROLE_NAME": "olist-glue-role",
    "GLUE_JOB_STAGING_PREFIX": "olist-staging",
    "GLUE_JOB_CURATED": "olist-build-curated",
    "ATHENA_WORKGROUP": "olist-dev",
    "KAGGLE_API_TOKEN": "KGAT_test_token_value",
    "FX_API_BASE_URL": "https://api.frankfurter.app",
    "LOG_LEVEL": "INFO",
    "LOG_FORMAT": "console",
    "ENVIRONMENT": "dev",
    "PROJECT_TAG": "olist-pipeline",
    "OWNER_TAG": "marianela",
}


@pytest.fixture(autouse=True)
def _populate_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto-applied: populate os.environ with a valid set of project settings.

    Autouse so any test (and downstream fixture) can build ``Settings`` without
    declaring the env-setup dependency explicitly. Tests that need to exercise
    a specific invalid value override one key with ``monkeypatch.setenv`` after
    this fixture has run.
    """
    for key, value in _TEST_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def settings() -> Settings:
    """Return a ``Settings`` built from the auto-populated test environment."""
    return Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.fixture
def aws_ready_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """``Settings`` with the environment prepared for moto-mocked AWS calls.

    ``AWS_PROFILE`` is removed (a non-existent profile would raise
    ``ProfileNotFound`` during credential resolution) and dummy static
    credentials are set. ``settings`` is already built, so its captured
    ``aws_profile`` value is unaffected.
    """
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    return settings


@pytest.fixture
def synthetic_olist_zip(tmp_path: Path) -> Path:
    """Return a zip mimicking the Kaggle archive: nine CSVs, one data row each."""
    zip_path = tmp_path / "synthetic-olist.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for filename in SOURCE_CSV_FILENAMES.values():
            archive.writestr(filename, "col_a,col_b\n1,2\n")
    return zip_path
