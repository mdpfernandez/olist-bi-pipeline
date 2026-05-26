"""Unit tests for olist_pipeline.core.config."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from olist_pipeline.core.config import Settings


@pytest.mark.unit
def test_settings_load_from_environment(settings: Settings) -> None:
    assert settings.aws_region == "eu-west-1"
    assert settings.s3_bucket_raw == "olist-raw-test-01"
    assert settings.project_tag == "olist-pipeline"
    assert settings.environment == "dev"


@pytest.mark.unit
def test_placeholder_bucket_suffix_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("S3_BUCKET_RAW", "olist-raw-mfern-xx")
    with pytest.raises(ValidationError, match="-xx"):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.unit
def test_placeholder_kaggle_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAGGLE_API_TOKEN", "your_kaggle_api_token")
    with pytest.raises(ValidationError, match="KAGGLE_API_TOKEN"):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.unit
def test_invalid_log_level_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
