# Architecture Decision Records

Living catalogue of architectural decisions for olist-bi-pipeline. Each row links to the full ADR. Decisions are append-only — never edited; superseded.

| #    | Title                                                                              | Status    | Date       | Tags                              |
| ---- | ---------------------------------------------------------------------------------- | --------- | ---------- | --------------------------------- |
| 0001 | [Athena over Redshift](0001-athena-over-redshift.md)                               | Accepted  | 2026-05-08 | aws, query-engine, cost           |
| 0002 | [Medallion architecture (raw / staging / curated)](0002-medallion-architecture.md) | Accepted  | 2026-05-08 | aws, s3, layout, lakehouse        |
| 0003 | [EventBridge + Lambda for orchestration](0003-eventbridge-lambda-orchestration.md) | Accepted  | 2026-05-08 | aws, orchestration, lambda        |
| 0004 | [Brazilian Olist as the primary dataset](0004-olist-dataset.md)                    | Accepted  | 2026-05-08 | dataset, retail, e-commerce       |
| 0005 | [Power BI Modeling MCP for semantic model authoring](0005-power-bi-modeling-mcp.md) | Accepted | 2026-05-08 | power-bi, mcp, ai-tooling, dax    |
| 0006 | [Incremental ingestion with HWM pattern](0006-incremental-ingestion-hwm.md)        | Accepted  | 2026-05-08 | ingestion, incremental, hwm       |
| 0007 | [Migrate curated layer to Apache Iceberg](0007-migration-to-iceberg.md)            | Proposed  | 2026-05-08 | storage, iceberg, merge, time-travel |

## Conventions

- **Format**: Michael Nygard, with explicit `Pre-decision review`, `Alternatives considered`, and `Consequences` (positive AND negative) sections.
- **Numbering**: 4-digit, gap-free, in chronological order of acceptance.
- **Append-only**: a decision is never edited after acceptance. Revisions create a new ADR with status `Supersedes ADR-NNNN`; the old one's status changes to `Superseded by ADR-MMMM`.
- **Authoring**: use the `/adr` slash command in Claude Code — it walks through the four pre-decision questions and produces the file in the right place.

## What gets an ADR vs. what does not

| Tier | Vehicle                                  | Examples                                                                            |
| ---- | ---------------------------------------- | ----------------------------------------------------------------------------------- |
| **A — ADR here** | this folder                       | Cloud service choice, storage layout, orchestration pattern, dataset, MCP adoption  |
| **B — `docs/architecture.md`** | section in architecture doc | Naming conventions, partition keys, IAM role boundaries, pre-commit policy          |
| **C — comment + commit message** | inline in code                  | Library choice for one util, threshold tuning, SQL formatting style                 |

When in doubt, **default to Tier C**. Promotion (C → B → A) is cheap; pre-classification is the hard call.
