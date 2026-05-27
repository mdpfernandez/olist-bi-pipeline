# CLAUDE.md — olist-bi-pipeline briefing

You are working on **olist-bi-pipeline**, a portfolio project. Read this once at session start; the rest of `.claude/`, `docs/` and `src/` are referenced from here.

## What this project is

An end-to-end data pipeline on AWS that ingests the **Brazilian Olist e-commerce dataset** (100k orders, 9 tables, 2016–2018) into a **medallion architecture** on S3, transforms it with **AWS Glue + Athena**, and exposes a **Power BI** dashboard for business users. Orchestration via **EventBridge + Lambda**.

The goal is **portfolio**, not production. The author is Marianela Fernández, BI Lead with 8 years' experience in retail analytics, targeting BI Lead / Data Architect roles in Madrid. Decisions favour clarity for a recruiter over operational sophistication.

## Project ground rules

1. **Cost-first.** Every AWS resource provisioned must be tagged `project=olist-pipeline` and `env=dev`, and its estimated monthly cost documented either in `infra/README.md` or in the ADR that introduced it. See `.claude/skills/aws-cost-discipline/SKILL.md`.
2. **Reproducibility.** A new reader must be able to bring up the whole pipeline from zero in under one hour following `docs/setup/`. If a step is missing, that's a bug.
3. **Documentation as code.** Every meaningful architectural choice gets an ADR under `docs/adr/`. Decisions are append-only — never edit an ADR; supersede it instead. See `/adr` slash command.
4. **Single-engineer bias.** When in doubt between a clever tool and a boring well-documented one, pick the boring one. Marianela works alone; onboarding cost matters.
5. **English in code, Spanish in chat.** READMEs, docstrings, comments, ADRs, commit messages: English (aligned with tooling and broader market). Conversation with Claude Code: Spanish.

## Stack at a glance

| Concern               | Choice                          | ADR  |
| --------------------- | ------------------------------- | ---- |
| Data ingestion        | Python + Kaggle API → S3        | —    |
| Storage layout        | Medallion (raw / staging / curated) | 0002 |
| Schema discovery      | AWS Glue Crawler                | —    |
| Distributed transform | AWS Glue Jobs (PySpark)         | —    |
| Query engine          | AWS Athena                      | 0001 |
| Orchestration         | AWS EventBridge + Lambda        | 0003 |
| Visualisation         | Power BI Desktop (free) + publish-to-web | — |
| Semantic model authoring | Power BI Modeling MCP (Microsoft, public preview) | 0005 |
| Refresh strategy      | Incremental w/ HWM (Phase A) → Iceberg MERGE (Phase B) | 0006, 0007 |
| Dataset               | Brazilian Olist (Kaggle)        | 0004 |
| Python tooling        | uv, ruff, pyright, pytest       | —    |
| Python version        | 3.12                            | —    |
| Operating system      | Windows 10/11 (Power BI Desktop is Windows-only) | — |

## Repository layout

```
olist-bi-pipeline/
├── .claude/             Claude Code config: hooks, commands, skills
├── docs/                ADRs, architecture notes, setup guides, screenshots
├── src/olist_pipeline/  Python source code (5 layers, see below)
├── infra/               Bash scripts + JSON for AWS resources
├── notebooks/           Exploratory only — NOT production
├── powerbi/             .pbix file + data model documentation
└── tests/               unit / integration / fixtures
```

### The 5 layers under `src/olist_pipeline/`

```
src/olist_pipeline/
├── core/             Cross-cutting: config, logging, types
├── ingestion/        Kaggle download → S3 raw
├── transformation/   Glue Job scripts + Athena SQL
├── quality/          Data validation (custom checks; Great Expectations later if needed)
└── orchestration/    Lambda handlers + EventBridge rule definitions
```

**Import rules (enforced by `pre_create_layout_check.sh`):**

- `core/` imports stdlib + boto3 + pydantic only.
- `ingestion/` may import `core/`. No transformation logic here.
- `transformation/` may import `core/`. No ingestion or orchestration.
- `quality/` may import `core/`, `transformation/` (read-only).
- `orchestration/` may import everything — it's the glue.
- New `.py` files must land in one of these 5 directories or under `tests/`.

## Hooks active in every session

- **`post_edit_ruff.sh`** — runs `ruff check --fix && ruff format` on edited `.py` files. Blocks (exit 2) if errors remain.
- **`pre_create_layout_check.sh`** — when a new `.py` is created under `src/` or `tests/`, blocks if it falls outside the allowed paths.

## Pre-commit (git hooks)

Separate from the Claude Code hooks above: the repo also runs the **`pre-commit`** framework (`.pre-commit-config.yaml`) on every `git commit`. Install it once per clone with `uv run pre-commit install`. It runs:

- **Hygiene** — trailing-whitespace, end-of-file-fixer, check-yaml/toml/json, `mixed-line-ending --fix=lf`, detect-private-key, check-added-large-files.
- **ruff** (`--fix`) + **ruff-format** on Python.
- **detect-secrets** against `.secrets.baseline` — scans staged files for accidentally committed AWS keys/secrets. The baseline must exist or the hook crashes the commit; it is committed to the repo. To update it after a legitimate new finding: `uv run detect-secrets scan --baseline .secrets.baseline`.
- **pyright** (strict on `src/`) — `pre-push` stage only, not on every commit.

**Windows gotcha:** the `mixed-line-ending` hook rewrites CRLF→LF and **exits non-zero, aborting the first commit attempt**. The file is left fixed in the working tree, so the recovery is just `git add <same files>` and re-run the identical commit — the second attempt passes. This re-stage + recommit cycle is normal, not an error. Don't reach for `--no-verify`.

## Skills

- **`.claude/skills/aws-cost-discipline/SKILL.md`** — required reading before provisioning any AWS resource (Glue Crawler, Glue Job, Lambda, Athena workgroup, S3 lifecycle rule). Covers the 3 mandatory tags, budget alerts, the "always destroy on Friday" rule, and worked cost estimates per service.

## MCP servers available

These are configured per-machine in Claude Code (not in `.claude/settings.json`, which is project-scoped). Marianela installs them on her Windows machine following `docs/setup/04-power-bi-setup.md`.

- **`powerbi-modeling-mcp`** — Microsoft's official MCP for Power BI semantic model authoring (public preview). Lets Claude Code read the open `.pbix` model and create/modify DAX measures, manage relationships, edit calculated columns, run DAX queries, and reorganise the model. **Does NOT design visuals** — those are authored manually in Power BI Desktop. See ADR-0005 for the rationale.

  When the user asks for measure logic, model refactoring, or DAX optimisation, prefer the MCP tools over writing DAX in chat — the MCP runs against the actual model and surfaces real errors.

## Slash commands

- **`/adr [title]`** — guided ADR drafting with auto-numbering, Michael Nygard format, mandatory Alternatives Considered and Pre-decision Review sections.

## Decision rubric — when does something become an ADR?

| Tier | Vehicle                                  | Examples                                                     |
| ---- | ---------------------------------------- | ------------------------------------------------------------ |
| **A** | ADR via `/adr`                          | Cloud service choice, storage layout, orchestration pattern, dataset choice |
| **B** | Section in `docs/architecture.md`       | Naming conventions, partitioning scheme, IAM role boundaries |
| **C** | Comment + descriptive commit message    | Library choice for a util, threshold tuning, SQL formatting  |

Default under uncertainty: **Tier C**. Promote to B when the choice is referenced in a second place. Promote to A when it commits the project to something hard to reverse.

## Workflow

```bash
uv sync                                  # install deps
cp .env.example .env                     # fill in AWS creds and bucket names

uv run pytest                            # tests
uv run ruff check && uv run ruff format  # auto-applied by hook; manual when needed
uv run pyright src                       # strict type check on src/

# AWS — always use the local profile, never hardcode keys
export AWS_PROFILE=olist-portfolio
aws s3 ls                                # smoke test
```

## Anti-patterns — flag and stop

- Provisioning an AWS resource without `project=olist-pipeline` and `env=dev` tags.
- Leaving a Glue Crawler scheduled or a Glue Job triggered without documenting estimated monthly cost.
- Hardcoded AWS access keys, bucket names, account IDs, or any secret in `src/`. Use `.env` + `core/config.py`.
- Notebook code path-imported into `src/`. If a notebook produces value, refactor into a `src/olist_pipeline/<layer>/` module first.
- `boto3.client("s3")` instantiated at module top-level (defeats mocking, breaks tests). Inject via `core/aws.py` factories.
- A test under `tests/unit/` that hits real AWS. Real AWS calls live only in `tests/integration/` with proper teardown.
- Editing an existing ADR's decision. ADRs are append-only — supersede instead.
- A Glue Job written in Python (script mode) when a Spark SQL or Athena CTAS would do. Spark is for joins/aggregations that don't fit in Athena's query timeout.
- **Filtering the incremental read by `purchase_timestamp > hwm` instead of `ingested_at > hwm`** — silently skips late-arriving data. ADR-0006 covers this; `docs/INCREMENTAL_LOADS.md` §8 explains why.
- **Writing the HWM state file without atomic semantics** (no `If-Match` ETag). Two concurrent runs can corrupt state.
- **Running a full reload without an ADR justifying the override** — the project is incremental by default (ADR-0006). Full reload is for backfills only, and goes through `scripts/reset_hwm.py` with an audit log entry.

## Communication style

Marianela reads English fine but writes in Spanish. Reply in Spanish for explanations and discussion. Keep code, comments, ADRs, commits and docs in English.

She has 8 years of BI/Data Science experience but is **a junior on infra/devops topics** (AWS CLI, IAM, git advanced, package managers, hooks). When she needs to set up something on her machine — AWS CLI profile, `.env`, virtual env, git config, Power BI connection — explain it step by step, command by command, and explain *why* each step exists. Don't assume; ask if unsure.

Prefer concrete recommendations with reasoning, push back when something seems off, and brevity over completeness when both are options. When she announces a decision in chat that smells Tier A, propose `/adr` before writing code.
