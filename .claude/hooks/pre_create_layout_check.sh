#!/usr/bin/env bash
# Hook: pre_create_layout_check
# Purpose: before creating a new .py file under src/olist_pipeline/ or tests/,
# validate that it lands in a permitted layer of the project layout.
# BLOCKING (exit 2 on PreToolUse for Write) — the file never reaches disk if
# the location does not respect the structure.
#
# Edit/MultiEdit are not intercepted: by definition they operate on existing
# files, whose location was validated at creation.
#
# Valid layers under src/olist_pipeline/ (see CLAUDE.md):
#   - core/             cross-cutting: config, logging, types
#   - ingestion/        Kaggle download, S3 upload to raw/
#   - transformation/   Glue Job scripts, PySpark, Athena SQL
#   - quality/          data validation between layers
#   - orchestration/    Lambda handlers, EventBridge rule definitions
#
# Valid categories under tests/:
#   - unit/         fast, no IO
#   - integration/  externals mocked (moto) or testcontainers
#   - fixtures/     factories, helpers, test data

set -euo pipefail

payload=$(cat)

file_path=$(echo "$payload" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('tool_input', {}).get('file_path', ''))
except Exception:
    print('')
")

# Only .py files
if [ -z "$file_path" ] || [[ "$file_path" != *.py ]]; then
    exit 0
fi

# Resolve to a path relative to the repo
rel_path="$file_path"
if [[ "$rel_path" == /* ]]; then
    rel_path="${rel_path#$PWD/}"
fi

# Only validate files in src/olist_pipeline/ or tests/.
# Top-level (e.g. setup.py), notebooks, scripts at repo root, infra/: pass through.
if [[ "$rel_path" != src/olist_pipeline/* ]] && [[ "$rel_path" != tests/* ]]; then
    exit 0
fi

# __init__.py always allowed
if [[ "$rel_path" == *__init__.py ]]; then
    exit 0
fi

# conftest.py at any level under tests/ allowed
if [[ "$rel_path" == tests/conftest.py ]] || [[ "$rel_path" == tests/*/conftest.py ]]; then
    exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# Validation: src/olist_pipeline/
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$rel_path" == src/olist_pipeline/* ]]; then
    allowed_layers=(
        "src/olist_pipeline/core/"
        "src/olist_pipeline/ingestion/"
        "src/olist_pipeline/transformation/"
        "src/olist_pipeline/quality/"
        "src/olist_pipeline/orchestration/"
    )

    is_valid=0
    for layer in "${allowed_layers[@]}"; do
        if [[ "$rel_path" == "$layer"* ]]; then
            is_valid=1
            break
        fi
    done

    if [ $is_valid -eq 0 ]; then
        cat >&2 <<EOF
ERROR: $rel_path is not in a valid layer of olist-bi-pipeline.

Valid layers under src/olist_pipeline/:
  - core/             cross-cutting: config, logging, types
  - ingestion/        Kaggle download, S3 upload to raw/
  - transformation/   Glue Job scripts, PySpark, Athena SQL
  - quality/          data validation between layers
  - orchestration/    Lambda handlers, EventBridge rule definitions

Decide where your code belongs by reading CLAUDE.md (section "The 5 layers")
before retrying. If you genuinely need a new layer, that is a Tier A decision —
draft an ADR with /adr first.
EOF
        exit 2
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Validation: tests/
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$rel_path" == tests/* ]]; then
    allowed_tests=(
        "tests/unit/"
        "tests/integration/"
        "tests/fixtures/"
    )

    is_valid=0
    for layer in "${allowed_tests[@]}"; do
        if [[ "$rel_path" == "$layer"* ]]; then
            is_valid=1
            break
        fi
    done

    if [ $is_valid -eq 0 ]; then
        cat >&2 <<EOF
ERROR: $rel_path is not in a valid test category.

Valid categories under tests/:
  - unit/         fast, no IO, no AWS calls
  - integration/  externals mocked (moto) or testcontainers
  - fixtures/     factories, helpers, test data

Decide which kind of test this is before retrying.
EOF
        exit 2
    fi
fi

exit 0
