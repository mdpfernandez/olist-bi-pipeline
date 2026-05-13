# 04 — Power BI: Athena connection + Modeling MCP for Claude Code

By the end of this guide you will have:

1. Power BI Desktop installed and configured.
2. The Simba Athena ODBC driver installed and tested with a connection to your `olist_dev` Glue database.
3. The Power BI Modeling MCP server installed (Microsoft's official, public preview) and registered with Claude Code.
4. A first end-to-end smoke test: open a `.pbix`, ask Claude Code (in Spanish) to create a measure, watch it appear in Power BI Desktop in real time.

> **Reading time:** ~10 min. **Active time:** ~30–45 min.
>
> **Prerequisite:** you've completed `01`, `02`, `03`. You also need at least the **`olist_dev` Glue database** existing in AWS — even if the curated tables are empty, the database has to exist for Athena to connect. We'll create it as part of `infra/` before you actually need this guide. If you got here before that, complete the AWS resource bring-up first.

---

## Step 1 — Power BI Desktop is already installed

You did this in `01-prerequisites.md`. Confirm:

1. Open Power BI Desktop from the Start menu.
2. Sign in with the same email you'll use for Power BI Service (typically your personal email is fine for free tier).
3. The first launch shows a tutorial dialog — close it, you don't need it.

If you see the welcome screen, you're good.

---

## Step 2 — Install the Simba Athena ODBC driver

The driver is what lets Power BI talk to Athena. AWS publishes it via Simba (their preferred ODBC vendor).

### Download

1. Go to **<https://docs.aws.amazon.com/athena/latest/ug/connect-with-odbc.html>**.
2. Find the **"ODBC driver download links"** section.
3. Click the link for **Windows 64-bit ODBC driver, version 2.x** (newest stable; 1.x is legacy).
4. Save the `.msi` file to your Downloads folder.

### Install

1. Double-click the `.msi`. Follow the wizard. Accept defaults except for one thing:
2. When asked, **install for all users** (this avoids permission issues with Power BI's process model).
3. Finish the wizard.

### Verify the driver is registered

1. Press `Windows key`, type "ODBC Data Sources (64-bit)", hit Enter.
2. Click the **Drivers** tab.
3. Look for an entry **"Simba Amazon Athena ODBC Driver"**. If it's there, the install succeeded.

### Configure a DSN (Data Source Name)

A DSN is a saved connection profile. We'll create one called `olist-athena`.

1. In the same ODBC Data Sources window, go to **System DSN** tab → **Add**.
2. Select **Simba Amazon Athena ODBC Driver**, click Finish.
3. Fill in the configuration window:
   - **Data Source Name:** `olist-athena`
   - **Description:** `Athena for olist-bi-pipeline (dev)`
   - **AWS Region:** `eu-west-1` (or whatever region you chose in `02-aws-account.md`)
   - **S3 Output Location:** `s3://olist-athena-results-mfern-xx/` (the bucket from your `.env`'s `S3_BUCKET_ATHENA_RESULTS`, with a trailing slash)
   - **Authentication Options** → click "AWS Authentication Type" dropdown → **AWS Profile**
   - **Profile Name:** `olist-portfolio` (the AWS CLI profile you configured)
4. Click **Test** at the bottom of the dialog. You should see "**Connection successful**".

If the test fails:
- "Could not connect to S3 location" → check the bucket name; make sure it exists (`aws s3 ls s3://...`) and your IAM user has read/write access to it.
- "Profile not found" → check `~/.aws/credentials` has a `[olist-portfolio]` section. Run `aws sts get-caller-identity --profile olist-portfolio` to confirm.
- "No catalog selected" or similar → leave Catalog blank for now; we'll select per-query.

5. Click **OK** to save. Close the ODBC Data Sources window.

---

## Step 3 — Connect Power BI Desktop to Athena

In Power BI Desktop:

1. **Home → Get Data → More...**
2. In the search box, type "**ODBC**".
3. Select **ODBC**, click **Connect**.
4. **Data source name (DSN):** select `olist-athena` from the dropdown.
5. Click **OK**.
6. Authentication dialog: leave it on "Default or Custom", click **Connect**.
7. The Navigator window opens. You should see your AWS Glue databases — including `olist_dev`.
8. Expand `olist_dev`. You should see the curated tables (`fact_orders`, `dim_customers`, etc.) once the pipeline has produced them.

> **If you don't see `olist_dev`:** it means the database doesn't exist yet in Glue. Create it with `aws glue create-database --database-input '{"Name":"olist_dev"}'`. If the database exists but is empty, that's fine — you'll see an empty namespace.

9. For now, **don't import any tables**. Click **Cancel**. We're just verifying the connection works.

If you got this far without errors, **Power BI ↔ Athena is working**. Save what would be the empty `.pbix`:

- **File → Save As → `powerbi/olist_dashboard.pbix`** (inside your repo).
- Commit it to git: `git add powerbi/olist_dashboard.pbix && git commit -m "feat(powerbi): empty dashboard with Athena connection"`.

---

## Step 4 — Install the Power BI Modeling MCP

This is the AI-assisted modelling piece. The MCP runs as a process on your machine that Claude Code talks to.

### Install the VS Code extension that bundles the MCP server

The MCP executable ships inside a VS Code extension. Easiest way:

1. Open VS Code.
2. Extensions panel (`Ctrl+Shift+X`).
3. Search for: **"Power BI Modeling MCP"**.
4. Make sure the publisher is **"Analysis Services"** (Microsoft's BI team).
5. Click **Install**.

That installs the extension, which extracts the MCP server executable into your VS Code extensions folder.

### Find the path to the MCP executable

The exact path depends on the version. As of mid-2026, the pattern is:

```
C:\Users\<you>\.vscode\extensions\analysis-services.powerbi-modeling-mcp-<version>-win32-x64\server\powerbi-modeling-mcp.exe
```

Find the actual path:

```powershell
Get-ChildItem -Path "$env:USERPROFILE\.vscode\extensions" -Filter "analysis-services.powerbi-modeling-mcp*" -Directory | ForEach-Object { Join-Path $_.FullName "server\powerbi-modeling-mcp.exe" }
```

This prints the full path. **Copy it** — you'll paste it in the next step. It will look something like:

```
C:\Users\Marianela\.vscode\extensions\analysis-services.powerbi-modeling-mcp-0.1.9-win32-x64\server\powerbi-modeling-mcp.exe
```

### Register the MCP with Claude Code

Claude Code's MCP servers are configured per-machine, not in the repo. The command:

```powershell
claude mcp add `
    --transport stdio `
    powerbi-modeling-mcp `
    --env PBI_MODELING_MCP_CLIENT_ID=ea0616ba-638b-4df5-95b9-636659ae5121 `
    -- `
    "C:\Users\<you>\.vscode\extensions\analysis-services.powerbi-modeling-mcp-0.1.9-win32-x64\server\powerbi-modeling-mcp.exe" `
    --start
```

Replace the path with the actual path you got from the previous step. The `PBI_MODELING_MCP_CLIENT_ID` is Microsoft's public client ID for this MCP — it's not a secret.

### Verify the MCP is registered

```powershell
claude mcp list
```

You should see `powerbi-modeling-mcp` in the list.

---

## Step 5 — End-to-end smoke test

The big test: can Claude Code actually drive Power BI Desktop?

1. **Open Power BI Desktop** with your `olist_dashboard.pbix` (the empty one). Leave it open.
2. **Open VS Code** in your project folder. Open a Claude Code session (`claude` in the terminal).
3. In the Claude Code chat, ask in Spanish:

   > Conectate al modelo de Power BI abierto y listame las tablas que tiene actualmente.

4. Claude Code should:
   - Call the MCP's "list tables" tool against the open `.pbix`.
   - Reply with the (possibly empty) list of tables.

5. If you have at least one table loaded into the model (try importing a small CSV from the Olist dataset for this test), ask:

   > Crea una medida llamada "Total Orders" que cuente el número de filas distintas de orders, y formatealá como número entero con separador de miles.

6. Claude Code should:
   - Call the MCP's "create measure" tool.
   - You should see the measure appear in Power BI Desktop's Fields pane within a couple of seconds.
   - The measure shows up as `Total Orders` with the DAX `DISTINCTCOUNT(orders[order_id])` (or equivalent).

If both work, **the MCP is fully wired**. Save the `.pbix`, commit it.

---

## Step 6 — Export the model as TMDL (text format)

Power BI's recent versions support **PBIP** (Power BI Project) format — instead of saving as a single `.pbix` binary, you save as a folder of text files. The semantic model is in TMDL (Tabular Model Definition Language). This is what makes the model **diff-able in git**.

### Convert your dashboard to PBIP

1. In Power BI Desktop: **File → Options and settings → Options → Preview features**.
2. Tick **"Power BI Project (.pbip) save option"**.
3. Click **OK**, restart Power BI Desktop.
4. Open your dashboard, **File → Save As**, choose **Power BI project files (*.pbip)** as the format.
5. Save it as `powerbi/olist_dashboard.pbip`. Power BI creates a folder structure:

   ```
   powerbi/
   ├── olist_dashboard.pbip
   ├── olist_dashboard.Report/
   │   ├── definition.pbir
   │   └── ...
   └── olist_dashboard.SemanticModel/
       ├── definition.pbism
       ├── model.tmdl
       └── tables/
           ├── orders.tmdl
           └── ...
   ```

6. The `.tmdl` files are plain text. Open one — it's readable.

### Why we use both .pbix and .pbip

- **.pbix** → for the recruiter who downloads it, opens in Power BI Desktop, and clicks around. That's the deliverable.
- **.pbip + TMDL files** → for git history, code review, and the "this person practices version-controlled BI development" signal.

We commit both. The `.pbix` is binary (git LFS not strictly needed at our size); the TMDL is text and shows up in `git diff`.

### Update `.gitignore`

Power BI sometimes generates auto-cache files inside the PBIP folder. Make sure your `.gitignore` excludes them — these patterns are already in our `.gitignore`:

```
# Power BI cache and local artefacts
**/.pbi/
**/cache.abf
**/Snapshot.tmdl
```

---

## Sanity check

1. `olist-athena` DSN connects, navigator shows `olist_dev` database.
2. `olist_dashboard.pbix` opens in Power BI Desktop.
3. `claude mcp list` shows `powerbi-modeling-mcp`.
4. Asking Claude Code to list tables / create a measure works.
5. The PBIP folder structure exists and `.tmdl` files are committed.

If all five tick, you have **the most modern Power BI development workflow available in 2026**: AWS data via ODBC, model authored conversationally with AI, model versioned as text, visuals authored manually where your expertise actually shines.

---

## What's next

You're done with setup. The real work begins:

1. Write the ingestion module (`src/olist_pipeline/ingestion/`) — Kaggle download to S3 raw.
2. Provision the AWS resources defined in `infra/` (`bash infra/create-buckets.sh`, etc.).
3. Write the staging Glue Jobs.
4. Build the curated star schema.
5. Author the dashboard.

Each step has its own future doc / runbook under `docs/runbooks/` (not yet written; we add them as the work happens).

When in doubt, in any session of Claude Code, ask:

```
/explain-decision <topic>
```

If the slash command returns nothing, the answer is in `CLAUDE.md` or in `docs/architecture.md`. Read those before reinventing.
