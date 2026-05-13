# `powerbi/` — dashboard, semantic model, and TMDL

This folder contains everything Power BI: the dashboard binary, its text representation as TMDL, and the documentation of the dimensional model.

## Files

| File / Folder                       | Purpose                                                                            |
| ----------------------------------- | ---------------------------------------------------------------------------------- |
| `olist_dashboard.pbix`              | Binary deliverable. Opens in Power BI Desktop. Recruiters download this.           |
| `olist_dashboard.pbip`              | Power BI Project file (text). Opens in Power BI Desktop, persists model as TMDL.   |
| `olist_dashboard.SemanticModel/`    | TMDL representation of the model — tables, columns, measures, relationships.       |
| `olist_dashboard.Report/`           | Visual layout of the report (PBIR format). One folder per page.                    |
| `data_model.md`                     | Human-readable documentation of the star schema and key DAX measures.              |

The `.pbix` and the `.pbip + tmdl` are committed both — see ADR-0005 for the rationale.

## How to open

1. Make sure you have completed `docs/setup/04-power-bi-setup.md` (Athena DSN configured, Power BI Desktop installed).
2. Double-click `olist_dashboard.pbix` (or `.pbip` for project mode).
3. On first open, Power BI prompts to refresh — **say no** until you have AWS resources up and the curated layer populated. An empty refresh shows ugly errors.

## Authoring workflow

The intended workflow combines manual Power BI Desktop work and AI-assisted modelling via the MCP (see ADR-0005):

| Task                                             | Where it happens          |
| ------------------------------------------------ | ------------------------- |
| Add / refactor / optimise a DAX measure          | Claude Code (via MCP)     |
| Manage table relationships                       | Claude Code (via MCP)     |
| Add a calculated column                          | Claude Code (via MCP)     |
| Run a DAX query to debug                         | Claude Code (via MCP)     |
| Design a chart / slicer / page layout            | Power BI Desktop (manual) |
| Conditional formatting, drill-through, bookmarks | Power BI Desktop (manual) |
| Theme / styling                                  | Power BI Desktop (manual) |
| Publish to Power BI Service                      | Power BI Desktop (manual) |

## Conventions

- **Snake_case for table names** (`fact_orders`, `dim_customers`) — matches the curated S3 layer.
- **PascalCase for measure names** (`TotalRevenue`, `OrdersYoY`) — Power BI convention.
- **Display folders** organise measures by domain (`Sales`, `Customers`, `Geography`, `Time Intelligence`).
- **Every measure has a description** filled in (Power BI's measure properties pane). The MCP populates these automatically when you ask Claude Code to create a measure with intent.
- **Every measure has a format string** (e.g., `#,##0` for integer counts, `#,##0.00` for monetary values, `0.0%` for percentages).

## Star schema overview

See `data_model.md` for the full breakdown. At a glance:

```
                           dim_date
                              │
                              ▼
   dim_customers ── fact_orders ── dim_geolocation
                              │
                              ├── fact_order_items ── dim_products
                              │                   ├── dim_sellers
                              │                   └── dim_currency (via fact_orders)
                              │
                              └── fact_payments
```

Two facts (`fact_orders`, `fact_order_items`) share several dimensions; this is the standard multi-fact star.
