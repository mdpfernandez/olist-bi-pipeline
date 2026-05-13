#!/usr/bin/env bash
# Hook: post_edit_ruff
# Purpose: after editing a Python file, run ruff check --fix + ruff format.
# BLOCKING (exit 2) if non-autofixable errors remain — Claude Code receives the
# stderr and must fix them before continuing.
#
# Input: JSON on stdin with {tool_name, tool_input: {file_path, ...}, ...}
# See: https://docs.claude.com/en/docs/claude-code/hooks

set -euo pipefail

payload=$(cat)

# Extract file_path from the JSON payload
file_path=$(echo "$payload" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('tool_input', {}).get('file_path', ''))
except Exception:
    print('')
")

# No file_path or not a .py file → silent exit
if [ -z "$file_path" ] || [[ "$file_path" != *.py ]]; then
    exit 0
fi

# The file may not exist yet if Write failed — defensive check
if [ ! -f "$file_path" ]; then
    exit 0
fi

# Prefer `uv run ruff` when there is a pyproject (ensures the same version as the lockfile).
# Otherwise fall back to ruff on PATH.
if command -v uv &>/dev/null && [ -f "pyproject.toml" ]; then
    RUFF_CMD="uv run --quiet ruff"
elif command -v ruff &>/dev/null; then
    RUFF_CMD="ruff"
else
    echo "WARNING: neither uv nor ruff available. Skipping autoformat." >&2
    exit 0
fi

# Autofix + format. Both can fail partially; we capture but do not stop.
$RUFF_CMD check --fix --quiet "$file_path" 2>&1 || true
$RUFF_CMD format --quiet "$file_path" 2>&1 || true

# Final check (without --fix) to see if there are unfixable errors left
if ! check_output=$($RUFF_CMD check "$file_path" 2>&1); then
    echo "ERROR: ruff detected non-autofixable errors in $file_path:" >&2
    echo "" >&2
    echo "$check_output" >&2
    echo "" >&2
    echo "Fix these errors before continuing. If there is a legitimate error you want" >&2
    echo "to suppress, use '# noqa: CODE' with justification, or adjust pyproject.toml." >&2
    exit 2
fi

exit 0
