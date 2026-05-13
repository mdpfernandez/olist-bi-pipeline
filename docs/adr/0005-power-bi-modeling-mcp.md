# ADR-0005 — Power BI Modeling MCP for semantic model authoring

- **Status**: Accepted
- **Date**: 2026-05-08
- **Tags**: power-bi, mcp, ai-tooling, dax

## Context

Marianela's stated preference is to do **as much of the project as possible from inside Claude Code**, leaving Power BI Desktop only for the parts that genuinely require it (visual report design, layout, formatting). Power BI's semantic model — tables, relationships, measures, calculated columns, KPIs, calculation groups — is *modelling*, not visual design, and modelling is exactly the kind of work Claude Code accelerates.

In April 2026 Microsoft released the **Power BI Modeling MCP server** in public preview. The server exposes ~20 tool categories that let an MCP-aware AI client (Claude Code, Claude Desktop, GitHub Copilot in VS Code) read and modify the model of a `.pbix` file open in Power BI Desktop. Concretely it covers tables, columns, measures, relationships, DAX queries, calculation groups, RLS roles, partitions, hierarchies. There are also community alternatives (MCP Engine, sulaiman013/powerbi-mcp).

Adopting an MCP for the semantic model is a **Tier A** decision because it commits the modelling workflow to a tool that is in preview, that runs against a specific Power BI Desktop process on Windows, and that we will reference in the README as part of the project's value-prop.

## Pre-decision review

- **Failure mode in 6 months**: Microsoft makes a breaking API change in the GA release of the MCP, and our `CLAUDE.md` instructions / our muscle memory stop working. Mitigation: pin the VS Code extension version we use and document it in `docs/setup/04-power-bi-setup.md`; the underlying `.pbix` is a deliverable that does not depend on the MCP.
- **Prior art and divergence**: Power BI community is actively adopting MCP — Tabular Editor blog, Microsoft DataMonkey, and several VS Code workflows have written it up since early 2026. We are riding the wave, not leading it.
- **Cost of reversal**: hours. If the MCP becomes unusable, we go back to writing DAX measures in Power BI Desktop directly. The model itself is unaffected — DAX is DAX, regardless of what tool authored it.
- **Early warning signal**: any of (a) MCP returns errors on basic operations after a Power BI Desktop or extension upgrade, (b) the AI lead spends more time fighting MCP setup than authoring DAX, (c) Microsoft announces deprecation or major redesign before GA.

## Decision

We adopt the **Microsoft Power BI Modeling MCP** (the official Microsoft extension, distributed via the VS Code marketplace as `analysis-services.powerbi-modeling-mcp`) as the AI-assisted authoring tool for the semantic model in `powerbi/olist_dashboard.pbix`.

Workflow:

1. Open `powerbi/olist_dashboard.pbix` in Power BI Desktop.
2. Open Claude Code in the project root in VS Code; the MCP is registered globally (per-machine configuration, NOT in the repo's `.claude/settings.json`).
3. Ask Claude Code in plain Spanish to create / refactor / optimise measures, manage relationships, etc. The MCP runs the operations against the open `.pbix`; results are visible in Power BI Desktop in real time.
4. Save the `.pbix` periodically; commit it to git when the model is in a coherent state.

Specifically out of scope of the MCP, and **explicitly done manually in Power BI Desktop**:

- Visual design (charts, slicers, layout, formatting, conditional formatting).
- Page navigation, drill-through, bookmarks.
- Theme / styling.
- Publish to Power BI Service.
- Final review of every measure the MCP creates — **no measure ships without a human read-through** ("AI as accelerator, not as author of record").

We **also commit the model definition as TMDL** (Tabular Model Definition Language — text format introduced in PBIP) under `powerbi/Model/` so the model is reviewable in git. The `.pbix` is binary and useful as a download for the recruiter; the TMDL is what makes the modelling work *legible*.

## Consequences

### Positive

- **Modelling is conversational.** Authoring 20+ DAX measures via "create a measure for YoY revenue, partition-aware, with a sensible default for the first year" is materially faster than typing each in DAX.
- **Same-tool development.** Marianela does not context-switch between Claude Code and Power BI's DAX editor for measure authoring. Visuals still happen in Power BI Desktop, where she is faster than any AI anyway.
- **TMDL in git.** The model is reviewable as text — additions, modifications, refactors all show up in `git diff`. A recruiter who clicks through `powerbi/Model/` sees real engineering practices applied to BI development.
- **Demonstrably modern.** Using an AI-assisted BI workflow in 2026 is itself a CV signal — it says the candidate keeps up with tooling.

### Negative

- **Public preview status.** Microsoft's documentation explicitly warns the implementation may change before GA. We accept that risk; mitigations are above.
- **Windows-only, Power-BI-Desktop-running requirement.** The MCP only operates on a live `.pbix` opened in Power BI Desktop. This is fine for Marianela's setup (Windows native) but is not portable if the project ever needs cross-platform development.
- **AI-authored DAX needs review.** The MCP can produce DAX that is syntactically valid and semantically wrong (e.g., subtle calendar-table misuse). **Mitigation:** every measure is human-reviewed; complex measures get unit-tested via DAX queries with known expected outputs (see future `tests/dax/`).
- **Setup friction.** The MCP requires a JSON config edit in the Claude Code config and a restart. Documented in `docs/setup/04-power-bi-setup.md` step by step.
- **Per-machine config.** Cannot be checked into the repo; must be set up on each developer's machine. **Mitigation:** the setup doc reduces this to ~10 minutes one-off.

### Neutral / open questions

- Microsoft has hinted at a "Modeling MCP for Power BI Service" that runs without Desktop. If that ships, we re-evaluate. Not a blocker today.
- Community alternatives (MCP Engine, sulaiman013/powerbi-mcp) offer overlapping or richer features. We chose Microsoft's because (a) it is first-party, (b) it is explicitly documented in Microsoft's tabular-editor channels, (c) when GA arrives, integration with the Microsoft Fabric ecosystem will be tighter.

## Alternatives considered

### Manual DAX in Power BI Desktop only

The traditional workflow — type measures in the DAX editor inside Power BI Desktop. **Rejected because** it does not exploit the project's premise of "as much from Claude Code as possible", does not produce a git-reviewable trail, and is slower for a 20-measure model. It remains the fallback if the MCP becomes unworkable.

### MCP Engine (community, mcpengine.dev)

A polished community MCP, claims to support Windows and macOS. **Rejected because** for a portfolio piece showing Microsoft's stack we prefer the first-party tool over a community one — easier to defend in an interview ("I used the official Microsoft tool"). Worth re-evaluating if Microsoft's MCP stagnates in preview.

### sulaiman013/powerbi-mcp

Open-source MCP with 34 tools, including XMLA endpoint support and PII masking. **Rejected because** XMLA requires Power BI Premium / Fabric capacity (Marianela has free tier), and the additional features (PII masking, audit logging) are not relevant for a public-domain dataset. Microsoft's MCP covers what we actually need.

### TMDL only, no MCP

Edit the model as text files (TMDL) in VS Code with a TMDL extension, never opening Power BI Desktop except to author visuals. **Rejected because** this loses the *interactive* benefit of the MCP — running DAX queries against the live model and seeing results immediately. TMDL alone is "git-friendly modelling"; TMDL + MCP is "git-friendly + AI-assisted modelling". We get both by using the MCP and committing the resulting TMDL.

### Tabular Editor (3rd party desktop tool, free + paid editions)

Industry-standard for advanced Power BI modelling. **Rejected because** it is not AI-assisted, has a learning curve of its own, and adds another tool to the stack without paying its way at portfolio scale. Tabular Editor is a tool to add when the model has hundreds of measures and CI/CD around them — we are not there.

## References

- [Microsoft Power BI Modeling MCP — VS Code Marketplace listing](https://marketplace.visualstudio.com/items?itemName=analysis-services.powerbi-modeling-mcp)
- [Tabular Editor: AI agents that work with Power BI semantic model MCP servers](https://tabulareditor.com/blog/ai-agents-that-work-with-power-bi-semantic-model-mcp-servers)
- [Beyond The Analytics: Connect Claude AI to Power BI with MCP](https://beyondtheanalytics.com/blog/claude-ai-power-bi-mcp-setup-guide-2026)
- [TMDL (Tabular Model Definition Language) overview](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview)
- Related: setup at `docs/setup/04-power-bi-setup.md` — the *how*; this ADR is the *why*.
