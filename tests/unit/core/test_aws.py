"""Unit tests for olist_pipeline.core.aws."""

from __future__ import annotations

import pytest

from olist_pipeline.core.aws import s3_client, s3_tagging_querystring, tag_dict
from olist_pipeline.core.config import Settings


@pytest.mark.unit
def test_tag_dict_returns_three_mandatory_tags(settings: Settings) -> None:
    assert tag_dict(settings) == {
        "project": "olist-pipeline",
        "env": "dev",
        "owner": "marianela",
    }


@pytest.mark.unit
def test_tagging_querystring_is_url_encoded(settings: Settings) -> None:
    querystring = s3_tagging_querystring(settings)
    assert "project=olist-pipeline" in querystring
    assert "env=dev" in querystring
    assert "owner=marianela" in querystring
    assert querystring.count("&") == 2


@pytest.mark.unit
def test_s3_client_is_created_for_the_configured_region(
    aws_ready_settings: Settings,
) -> None:
    client = s3_client(aws_ready_settings)
    assert client.meta.region_name == "eu-west-1"
