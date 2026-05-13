# 03 — Local environment: from clone to first command

By the end of this guide you will have:

1. The project repo on GitHub (created and pushed).
2. The repo cloned locally with all Python dependencies installed.
3. The `.env` file filled in with your secrets.
4. `gh` and `git` authenticated.
5. Claude Code configured and reading `CLAUDE.md`.
6. Kaggle API access configured to download the Olist dataset.
7. A working sanity-check that proves the hooks fire correctly.

> **Reading time:** ~10 min. **Active time:** ~30 min.
>
> **Prerequisite:** you've completed `01-prerequisites.md` and `02-aws-account.md`.

---

## Step 1 — Decide where the repo lives on disk

I recommend something like:

```
C:\Users\<you>\dev\olist-bi-pipeline
```

The `C:\Users\<you>\dev\` folder is your habitual workspace; clone all repos there. **Avoid OneDrive-synced folders** for code repos — sync conflicts mess with `.git/` and you'll waste time.

```powershell
mkdir C:\Users\$env:USERNAME\dev -ErrorAction SilentlyContinue
cd C:\Users\$env:USERNAME\dev
```

---

## Step 2 — Authenticate `gh` (GitHub CLI)

```powershell
gh auth login
```

This is interactive. Pick:

1. **What account?** GitHub.com
2. **What protocol for git operations?** HTTPS (simpler than SSH for first-timers; you can switch later).
3. **Authenticate Git with your GitHub credentials?** Yes.
4. **How would you like to authenticate?** "Login with a web browser".
5. `gh` shows you an 8-character code. Copy it. Press Enter — your default browser opens at `https://github.com/login/device`. Paste the code. Authorise.

Back in PowerShell, you'll see `✓ Authentication complete`.

**Verify:**

```powershell
gh auth status
```

Expected: `✓ Logged in to github.com as <your-username>`.

---

## Step 3 — Create the GitHub repo

You have two paths. **Path A** (recommended for a first portfolio piece) creates the repo on GitHub first, then we drop our local files in. **Path B** initializes locally and pushes — also fine.

**Path A — create empty repo on GitHub, clone, drop files in:**

```powershell
gh repo create olist-bi-pipeline `
    --public `
    --description "End-to-end data pipeline on AWS for Brazilian Olist e-commerce dataset, with Power BI dashboard." `
    --clone

cd olist-bi-pipeline
```

After this you have an empty `C:\Users\<you>\dev\olist-bi-pipeline\` connected to `https://github.com/<you>/olist-bi-pipeline`.

**Now drop in the project skeleton** (the files we've been generating in this conversation). The simplest way:

1. Download/extract the zip I'll provide at the end of this conversation into the repo folder.
2. Or, manually copy each file from chat into the right path.

After the files are in place:

```powershell
git add .
git commit -m "feat: initial project skeleton (CLAUDE.md, hooks, skill, ADR scaffolding)"
git push -u origin main
```

You should see your repo at `https://github.com/<you>/olist-bi-pipeline` with all the files.

---

## Step 4 — Install Python dependencies with `uv`

Inside the repo folder:

```powershell
uv sync
```

This reads `pyproject.toml`, resolves all dependencies (and their transitives), creates a virtual environment in `.venv/`, and installs everything.

**First run takes ~30 seconds.** Subsequent `uv sync` runs are nearly instant (cached).

> **Why a virtualenv:** project dependencies live inside `.venv/` (the project folder), not globally on your machine. If you have two projects needing different versions of `pandas`, they don't collide. `uv` manages the venv for you — you don't activate it manually; just use `uv run <command>` and uv injects the venv automatically.

**Verify:**

```powershell
uv run python --version
# expected: Python 3.12.X

uv run pytest --version
# expected: pytest 8.X.X
```

If both work, your env is ready.

---

## Step 5 — Set up the `.env` file

Secrets live in `.env`, never in `git`. The repo includes `.env.example` as a template; copy it and fill it in.

```powershell
Copy-Item .env.example .env
notepad .env
```

The file looks something like this (you'll fill in your actual values):

```bash
# AWS
AWS_PROFILE=olist-portfolio
AWS_REGION=eu-west-1
AWS_ACCOUNT_ID=123456789012

# S3 buckets — names must be globally unique across all of AWS.
# Pattern suggested: <purpose>-<your-initials>-<random-suffix>
S3_BUCKET_RAW=olist-raw-mfern-xx
S3_BUCKET_STAGING=olist-staging-mfern-xx
S3_BUCKET_CURATED=olist-curated-mfern-xx
S3_BUCKET_ATHENA_RESULTS=olist-athena-results-mfern-xx

# Glue
GLUE_DATABASE=olist_dev
GLUE_ROLE_NAME=olist-glue-role

# Kaggle
KAGGLE_USERNAME=your_kaggle_username
KAGGLE_KEY=your_kaggle_api_key
```

> **About `xx`:** S3 bucket names must be **globally unique across all of AWS**, not just your account. If `olist-raw-mfern` is taken, you need to add a suffix. Pick `01`, `02`, your birthday, anything.

> **About `AWS_PROFILE`:** by setting it here, the AWS SDK and CLI inside this project's terminal sessions will automatically use the `olist-portfolio` profile we created in `02-aws-account.md`. No need to set it globally.

Save the file.

**Verify `.env` is gitignored:**

```powershell
git status
```

`.env` should NOT appear in the output. If it does, `.gitignore` is missing or wrong — fix it before doing **anything** else (committing `.env` to a public repo means leaking your AWS access keys, Kaggle key, and account ID).

---

## Step 6 — Set up Kaggle API access

The Olist dataset is hosted on Kaggle. The `kaggle` Python library (already in our deps) needs an API token.

1. Go to **<https://www.kaggle.com/>** and create a free account if you don't have one.
2. Click your avatar (top right) → **Settings**.
3. Scroll to **API** section → **"Create New Token"**.
4. A file `kaggle.json` downloads. It contains `{"username":"...","key":"..."}`.
5. Copy `username` into `KAGGLE_USERNAME` and `key` into `KAGGLE_KEY` in your `.env`.
6. Delete the downloaded `kaggle.json` from your Downloads folder (the values are now in `.env`, no need to keep two copies).

> **About the token rotation:** Kaggle lets you rotate the token any time. If you suspect it leaked (or accidentally committed it), regenerate it from the same page — that invalidates the old one.

---

## Step 7 — Configure Claude Code

Open the project folder in VS Code:

```powershell
code .
```

In VS Code, open a terminal (`` Ctrl+` ``) and run:

```powershell
claude
```

The first time, Claude Code asks you to authenticate. Follow the browser flow.

Claude Code will read `CLAUDE.md` automatically when you start the session in a directory that contains it. **You can verify this by asking, in your first prompt, "what do you know about this project?"** — if it answers with details from `CLAUDE.md` (the 5 layers, the cost discipline rules, etc.), the briefing is loading.

**Verify `.claude/settings.json` is loaded:**

In Claude Code, type:

```
/hooks
```

It should list `pre_create_layout_check.sh` and `post_edit_ruff.sh` as active.

---

## Step 8 — Test the hooks

Let's confirm the hooks actually fire. From Claude Code, try this prompt:

> Crea un archivo `src/olist_pipeline/utils/random.py` con un comentario "hello".

This should **fail** because `utils/` is not one of our 5 valid layers. The `pre_create_layout_check.sh` hook should block the creation with a clear error message listing the allowed layers (`core`, `ingestion`, `transformation`, `quality`, `orchestration`). Claude Code will see the error and either retry in a valid layer or ask you what to do.

**If it succeeds and the file is created:** the hooks aren't firing. Check that `.claude/hooks/*.sh` are executable (`ls -la .claude/hooks/`) and that `.claude/settings.json` exists and is valid JSON.

Now try the inverse:

> Crea un archivo `src/olist_pipeline/core/types.py` con una sola línea: `Foo = str`.

This should **succeed** because `core/` is a valid layer. After creation, the `post_edit_ruff.sh` hook should run and either leave the file alone (if ruff is happy) or autofix small issues.

If both tests behave correctly, **your environment is fully wired**.

---

## Step 9 — Set up `pre-commit` for git hooks

Different from Claude Code hooks — this runs on `git commit` regardless of whether you used Claude Code.

```powershell
uv run pre-commit install
```

This installs git hooks that run `ruff check` and `ruff format` on every commit. If you try to commit code with linting errors, the commit is blocked until you fix them.

**Verify:**

```powershell
uv run pre-commit run --all-files
```

Should report all checks passing on a fresh skeleton.

---

## Sanity check — the full loop

In a fresh PowerShell, in the repo folder:

```powershell
# 1. Python env works
uv run python -c "print('Python OK')"

# 2. Linter works
uv run ruff check

# 3. Type checker works
uv run pyright src

# 4. Tests work (no tests yet, but the runner should report 0 collected)
uv run pytest

# 5. AWS works
aws sts get-caller-identity

# 6. GitHub works
gh auth status

# 7. Kaggle credentials are loaded (we'll test the actual download in the ingestion layer)
uv run python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('KAGGLE_USERNAME ok' if os.getenv('KAGGLE_USERNAME') else 'MISSING')"
```

Each command should succeed. If any fails, fix it before moving on.

---

## What's next

→ `04-power-bi-setup.md` — install the Athena ODBC driver, configure Power BI Desktop, install the Power BI Modeling MCP for Claude Code, build the connection from Power BI to your AWS data lake.

After that you're ready to start writing actual pipeline code. The first piece will be the ingestion module: download Olist from Kaggle, upload to S3 raw layer, with proper tagging.
