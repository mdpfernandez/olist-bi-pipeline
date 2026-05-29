# Architecture Decision Records

Living catalogue of architectural decisions. Each row links to the full ADR.

ADRs are **append-only**: a decision is never edited in place. To change a decision, write a new ADR with status `Supersedes ADR-NNNN` and update the old one's status to `Superseded by ADR-MMMM`. The interpretation of past decisions through status changes is itself the historical record.

| #    | Title                                                                                              | Status   | Date       | Tags                                            |
| ---- | -------------------------------------------------------------------------------------------------- | -------- | ---------- | ----------------------------------------------- |
| 0001 | [Athena over Redshift](0001-athena-over-redshift.md)                                               | Accepted | 2026-05-08 | aws, query-engine, cost, lakehouse              |
| 0002 | [Medallion architecture (raw / staging / curated)](0002-medallion-architecture.md)                 | Accepted | 2026-05-08 | aws, s3, data-lake, lakehouse, layout           |
| 0003 | [EventBridge + Lambda for orchestration](0003-eventbridge-lambda-orchestration.md)                 | Accepted | 2026-05-08 | aws, orchestration, eventbridge, lambda, cost   |
| 0004 | [Brazilian Olist as the primary dataset](0004-olist-dataset.md)                                    | Accepted | 2026-05-08 | dataset, retail, e-commerce                     |
| 0005 | [Power BI Modeling MCP for semantic model authoring](0005-power-bi-modeling-mcp.md)                | Accepted | 2026-05-08 | power-bi, mcp, ai-tooling, dax                  |
| 0006 | [Incremental ingestion with high-watermark pattern](0006-incremental-ingestion-hwm.md)             | Accepted | 2026-05-08 | ingestion, incremental, hwm, idempotency        |
| 0007 | [Migrate curated layer to Apache Iceberg](0007-migration-to-iceberg.md)                            | Proposed | 2026-05-08 | storage, lakehouse, iceberg, merge, time-travel |
| 0008 | [Parametrized staging job with per-table registry](0008-parametrized-staging-job-with-per-table-registry.md) | Accepted | 2026-05-29 | glue, transformation, staging, parametrization, operational-model |
