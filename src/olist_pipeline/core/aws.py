"""AWS client factories and project tagging helpers.

boto3 clients are built by factory functions, never at module import time: a
top-level client would bind before ``moto`` can patch the SDK in tests.
Tagging helpers centralise the three mandatory tags that every AWS resource in
this project must carry (see ``.claude/skills/aws-cost-discipline/SKILL.md``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import boto3

if TYPE_CHECKING:
    # Importing Settings only at type-check time keeps this module free of a
    # runtime pydantic dependency. That lets `transformation/hwm.py` import
    # `S3Client` from here inside the Glue runtime, which does not ship with
    # pydantic. The `from __future__ import annotations` above makes the
    # `Settings` parameter annotations work without the import at runtime.
    from olist_pipeline.core.config import Settings

# boto3 clients are generated dynamically at runtime; the project treats them
# as untyped on purpose (see the [tool.pyright] notes in pyproject.toml).
S3Client = Any


def s3_client(settings: Settings) -> S3Client:
    """Return an S3 client for the project's region.

    Credentials resolve through the standard AWS chain. For local runs that
    means the ``AWS_PROFILE`` exported in the shell (see the workflow in
    CLAUDE.md); under test, ``moto`` intercepts the calls.
    """
    return boto3.client("s3", region_name=settings.aws_region)


def tag_dict(settings: Settings) -> dict[str, str]:
    """Return the three mandatory project tags as a plain dict."""
    return {
        "project": settings.project_tag,
        "env": settings.environment,
        "owner": settings.owner_tag,
    }


def s3_tagging_querystring(settings: Settings) -> str:
    """Return the mandatory tags encoded for S3's ``Tagging`` request parameter.

    ``put_object`` expects tags as a single url-encoded querystring
    (``key=value&key=value``) -- unlike Glue (JSON) or Lambda (comma-separated).
    """
    return urlencode(tag_dict(settings))
