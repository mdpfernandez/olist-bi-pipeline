# `tests/` — testing layout

Three categories, separated by directory and by pytest marker. The `pre_create_layout_check.sh` hook enforces that every new test file lands in one of these three places.

## Categories

| Folder              | Marker         | What goes here                                          | Speed     |
| ------------------- | -------------- | ------------------------------------------------------- | --------- |
| `tests/unit/`       | `@pytest.mark.unit`        | Fast tests. **No IO, no AWS, no network.**     | < 1s each |
| `tests/integration/`| `@pytest.mark.integration` | Tests with mocked AWS (moto) or testcontainers | 1–10s     |
| `tests/fixtures/`   | n/a            | Factories, helpers, sample data files                   | n/a       |

There is **no `tests/e2e/`** for portfolio. End-to-end testing means running the actual pipeline against real AWS, which costs real money and is what `infra/run-glue-job.sh` already does on demand.

## Rules

1. **Every test file must declare its category via marker.**
   ```python
   import pytest
   pytestmark = pytest.mark.unit
   ```
   This applies the marker to every test in the file. Override per-test if needed.

2. **No live AWS calls** in `tests/unit/` or `tests/integration/`. `moto` mocks every AWS service we use.

3. **No fixtures duplicated across files** — they live in `tests/fixtures/` and are imported. `conftest.py` wires them.

4. **Names match the source under test.** `src/olist_pipeline/ingestion/kaggle.py` → `tests/unit/ingestion/test_kaggle.py`.

## How to run

```powershell
# All tests (default — runs everything)
uv run pytest

# Only unit (fast, on every commit)
uv run pytest -m unit

# Only integration (slower, before push)
uv run pytest -m integration

# Specific file
uv run pytest tests/unit/ingestion/test_kaggle.py

# Specific test
uv run pytest tests/unit/ingestion/test_kaggle.py::test_download_unpacks_correctly

# With coverage report
uv run pytest --cov --cov-report=term-missing

# Verbose, with timing
uv run pytest -v --durations=10
```

## Mocking AWS — moto

`moto` is configured as a project dependency. Use it like this:

```python
import boto3
import pytest
from moto import mock_aws

pytestmark = pytest.mark.integration


@mock_aws
def test_upload_to_raw_creates_object_with_tags():
    # Inside this test, all boto3 calls go to a fake AWS in-memory.
    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.create_bucket(
        Bucket="olist-raw-test",
        CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
    )

    # ... call your code under test ...

    response = s3.list_objects_v2(Bucket="olist-raw-test")
    assert response["KeyCount"] == 1
    # ... assertions on tags, content, etc.
```

The `mock_aws` decorator intercepts all AWS API calls within the test scope.

## Fixtures

Common fixtures live in `tests/fixtures/`:

- `tests/fixtures/olist_samples/` — small representative CSVs (10 rows each) for testing transformations without downloading the real dataset.
- `tests/fixtures/manifests/` — example manifest dicts for testing config loading.

Wire them via `tests/conftest.py`:

```python
import pytest
from pathlib import Path


@pytest.fixture
def olist_orders_sample() -> Path:
    return Path(__file__).parent / "fixtures" / "olist_samples" / "orders_10rows.csv"
```

## Pre-commit / pre-push behaviour

- Pre-commit: `ruff check` and `ruff format` run on every commit.
- Pre-push: `pyright src/` runs (strict mode) — slower, blocks if types are wrong.
- Tests **do not** run automatically on commit (would slow the loop). They run in CI when set up; until then, run them manually before pushing.
