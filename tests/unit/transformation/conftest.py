"""Local Spark fixtures for transformation unit tests.

The Spark fixture is session-scoped: cold-starting a SparkSession costs ~10s
and we only want to pay that once for the whole transformation test module.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


# `find_spec` checks availability without importing the package -- avoids
# both pyspark side-effects at collection time and a pyright unused-import
# error from the more idiomatic try/except pattern.
_pyspark_available = importlib.util.find_spec("pyspark") is not None


def _java_available() -> bool:
    """Cheap preflight: is the JVM reachable?

    Checked BEFORE invoking ``SparkSession.builder`` so we never half-start a
    JVM that we can't clean up. A half-started JVM leaks file descriptors
    that pytest's unraisable-exception collector then flags as test failures.
    """
    if os.environ.get("JAVA_HOME"):
        return True
    return shutil.which("java") is not None


@pytest.fixture(scope="session")
def spark() -> Iterator[SparkSession]:
    """Session-scoped local SparkSession.

    Skips if pyspark is missing (``uv sync --extra glue``) or if Java is not
    on PATH / ``JAVA_HOME``. The skip happens before any JVM bootstrap so
    nothing leaks.
    """
    if not _pyspark_available:
        pytest.skip("pyspark not installed; run `uv sync --extra glue`")
    if not _java_available():
        pytest.skip("Java not found on PATH or JAVA_HOME; install Java 11+ to run Spark tests")

    from pyspark.sql import SparkSession

    # pyright misreads `SparkSession.builder` as a classproperty without the
    # builder methods; pyspark's stubs are partial. The chained call works at
    # runtime and is the canonical PySpark idiom.
    session = (
        SparkSession.builder.appName("olist-pipeline-tests")  # pyright: ignore[reportAttributeAccessIssue]
        .master("local[2]")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()
