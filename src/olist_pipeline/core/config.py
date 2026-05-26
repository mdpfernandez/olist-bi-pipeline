"""Application configuration.

All runtime settings come from environment variables, loaded from a local
``.env`` file (see ``.env.example`` for the template). ``get_settings()``
returns a process-wide cached singleton, so the ``.env`` file is parsed only
once per process.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed view over the project's environment variables.

    Field names map case-insensitively to the ``.env`` keys, so ``aws_region``
    is populated from ``AWS_REGION``. Validation runs at construction time: a
    malformed ``.env`` fails loudly here instead of deep inside a later AWS
    call.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # AWS account / session
    aws_profile: str
    aws_region: str
    aws_account_id: str

    # S3 buckets (medallion layers + Athena query results)
    s3_bucket_raw: str
    s3_bucket_staging: str
    s3_bucket_curated: str
    s3_bucket_athena_results: str

    # AWS Glue
    glue_database: str
    glue_role_name: str
    glue_job_staging_prefix: str
    glue_job_curated: str

    # AWS Athena
    athena_workgroup: str

    # Kaggle (dataset download)
    kaggle_api_token: str

    # Frankfurter API (FX rates enrichment)
    fx_api_base_url: str

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    log_format: Literal["json", "console"]

    # Pipeline runtime + mandatory resource tags
    environment: Literal["dev", "prod"]
    project_tag: str
    owner_tag: str

    @field_validator(
        "s3_bucket_raw",
        "s3_bucket_staging",
        "s3_bucket_curated",
        "s3_bucket_athena_results",
    )
    @classmethod
    def _reject_placeholder_bucket(cls, value: str) -> str:
        """Catch a ``.env`` copied from ``.env.example`` with the ``-xx`` suffix left in."""
        if value.endswith("-xx"):
            raise ValueError(
                f"bucket name '{value}' still ends in the '-xx' placeholder suffix; "
                "set a real, globally-unique bucket name in .env"
            )
        return value

    @field_validator("kaggle_api_token")
    @classmethod
    def _reject_placeholder_kaggle(cls, value: str) -> str:
        """Catch a Kaggle token left at the ``.env.example`` placeholder value."""
        if value.startswith("your_kaggle"):
            raise ValueError(
                "KAGGLE_API_TOKEN still holds the .env.example placeholder value; "
                "generate a real token at kaggle.com -> Settings -> API and set "
                "it in .env"
            )
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached ``Settings`` singleton, parsing ``.env`` on first call."""
    return Settings()  # pyright: ignore[reportCallIssue]
