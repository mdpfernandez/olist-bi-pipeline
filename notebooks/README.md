# `notebooks/` — exploratory only

> **These notebooks are NOT production code.** They are scratch space for data exploration, schema discovery, ad-hoc analysis, and prototyping transformations before they get refactored into `src/olist_pipeline/`.

## Conventions

- Notebooks are **never imported by `src/`**. Anything useful gets refactored into a proper Python module under `src/olist_pipeline/<layer>/` first.
- Notebooks are **not tested**. If logic in a notebook needs tests, it does not belong in a notebook anymore — refactor it.
- Notebook outputs (cell outputs, plots) **may** be committed when they document a finding. Otherwise clear them before committing — they bloat the repo and produce noisy diffs. Use `Cell → All Output → Clear` in Jupyter.

## Suggested file naming

```
NN-<author>-<topic>.ipynb
```

Where `NN` is a 2-digit sequence in chronological order. Examples:

- `01-mfern-olist-schema-exploration.ipynb`
- `02-mfern-fx-rates-coverage.ipynb`
- `03-mfern-cohort-analysis-prototype.ipynb`

## Running notebooks locally

```powershell
uv run jupyter lab
```

This launches Jupyter Lab inside the project's virtual environment, so all the dependencies from `pyproject.toml` are available.

To use Olist data in a notebook, read it from S3 staging or curated:

```python
import os
from dotenv import load_dotenv
import awswrangler as wr   # part of the [glue] optional group

load_dotenv()

df = wr.s3.read_parquet(
    f"s3://{os.environ['S3_BUCKET_CURATED']}/fact_orders/",
    boto3_session=...
)
```

## What you will NOT find here

- Glue Job logic. That lives in `src/olist_pipeline/transformation/`.
- Quality rules. That lives in `src/olist_pipeline/quality/`.
- Anything that runs on a schedule. Schedules live in `src/olist_pipeline/orchestration/` (Lambdas + EventBridge).
- Power BI dashboard authoring. That lives in `powerbi/`.
