# 01 — Prerequisites: software you need installed

This is the first guide you should follow. By the end you will have every piece of software the project needs, on your Windows machine, with each installation verified.

> **Reading time:** ~10 minutes. **Active time:** ~45–60 minutes including downloads.
>
> **Audience:** Marianela. I am explaining each step assuming no prior familiarity with `winget`, package managers or what each tool does — even if some of this is obvious to you, I prefer to over-explain than to skip something that breaks later.

## Why we are using `winget` for most installations

`winget` is the official Windows package manager (built into Windows 10 1709+ and Windows 11). Instead of going to a website, downloading an installer, double-clicking through wizards, restarting, etc., you run **one command in PowerShell** and the installation happens. It also makes your setup **reproducible** — if you ever change machines or share the setup with someone, you give them the list of `winget install` commands and they get the same versions.

If a `winget install ...` ever fails, the website fallback is always there. Don't lose more than 5 minutes troubleshooting `winget` — switch to the website.

## How to open PowerShell

Press `Windows key`, type `PowerShell`, hit Enter. That opens a regular PowerShell window. For some commands you'll need PowerShell **as Administrator** — I'll flag those explicitly with `[Admin]`.

To open as Admin: right-click the PowerShell icon → "Run as administrator".

## Verify `winget` is installed

```powershell
winget --version
```

You should see something like `v1.7.10861`. If it says "winget is not recognised", update Windows: Settings → Windows Update → Check for updates. The "App Installer" component from Microsoft Store includes `winget`.

---

## 1. Python 3.12

**What it is:** the language we'll write all the pipeline code in.

**Why 3.12 specifically:** AWS Lambda supports Python 3.12 as its latest runtime, and AWS Glue 5.0 also runs on 3.12. Pinning to 3.12 means the code we run locally is the same as what runs in AWS — fewer "works on my machine" surprises.

**Install:**

```powershell
winget install Python.Python.3.12
```

This installs Python globally and adds it to your `PATH`. **Close and reopen PowerShell** so the new `PATH` takes effect.

**Verify:**

```powershell
python --version
```

Expected output: `Python 3.12.X` (where X is some number — anything 3.12.* is fine).

If you get `Python 3.11.x` or `3.13.x`, you have a previous Python that's earlier in the `PATH`. Use `python3.12 --version` instead, or fix the PATH order in System Properties → Environment Variables.

---

## 2. uv — the Python package manager

**What it is:** a modern replacement for `pip` + `venv` + `pip-tools` + `poetry`. Written in Rust, very fast, single tool that does everything.

**Why uv and not pip:** three reasons that matter for this project:
1. **Speed.** `uv sync` installs the project deps in seconds. With pip, the same takes 1–2 minutes every time.
2. **Lockfile.** `uv` produces `uv.lock` — exact versions of every dependency, transitive included. Anyone who clones the repo gets identical deps. With plain pip you can run the same `pip install` on two machines and get different versions.
3. **Single tool.** No mental overhead of "which command for what". `uv add`, `uv sync`, `uv run`, `uv lock`. Done.

**Install:**

```powershell
winget install astral-sh.uv
```

**Close and reopen PowerShell.**

**Verify:**

```powershell
uv --version
```

Expected: `uv 0.5.X` or higher.

---

## 3. Git for Windows

**What it is:** version control. You probably know git, but Windows doesn't include it by default.

**Install:**

```powershell
winget install Git.Git
```

**Close and reopen PowerShell.**

**Verify:**

```powershell
git --version
```

Expected: `git version 2.4X.X.windows.X`.

**Quick global config (do this now, won't ask again):**

```powershell
git config --global user.name "Marianela Fernandez"
git config --global user.email "fernandezmarianeladp@gmail.com"
git config --global init.defaultBranch main
git config --global core.autocrlf true
git config --global pull.rebase false
```

The last three lines:
- `init.defaultBranch main` — new repos default to `main` branch (modern convention; old default was `master`).
- `core.autocrlf true` — Windows uses `\r\n` line endings, Linux/Mac use `\n`. This setting auto-converts on commit/checkout so your repo stays Linux-compatible (AWS Lambda is Linux). Important for cross-platform work.
- `pull.rebase false` — when you `git pull`, it merges instead of rebasing. Safer default for solo work; you can change it later if you prefer rebase.

---

## 4. GitHub CLI (`gh`)

**What it is:** GitHub's official command-line tool. Lets you create repos, open PRs, manage issues — all without leaving the terminal.

**Why we want it:** so you can do `gh repo create olist-bi-pipeline --public --source=.` instead of clicking through the GitHub website.

**Install:**

```powershell
winget install GitHub.cli
```

**Close and reopen PowerShell.**

**Verify:**

```powershell
gh --version
```

Expected: `gh version 2.X.X`.

> We will run `gh auth login` later in `03-local-environment.md`, not now. That step opens a browser to authenticate.

---

## 5. AWS CLI v2

**What it is:** Amazon's official command-line tool for AWS. Let us provision and inspect every AWS service from PowerShell.

**Install:**

```powershell
winget install Amazon.AWSCLI
```

**Close and reopen PowerShell** (this one really needs the restart — its PATH update is fussy).

**Verify:**

```powershell
aws --version
```

Expected: `aws-cli/2.X.X Python/3.X.X Windows/10 exe/AMD64`.

If you get "aws is not recognised" after restarting PowerShell, manually verify: open File Explorer, navigate to `C:\Program Files\Amazon\AWSCLIV2\`. If `aws.exe` is there, the issue is PATH; if it's not there, the install failed.

> We will run `aws configure` in `02-aws-account.md`, not now. That step requires the IAM access keys, which we haven't created yet.

---

## 6. Visual Studio Code

**What it is:** the code editor. Free, made by Microsoft, the de facto standard for Python and most modern dev work.

**Install:**

```powershell
winget install Microsoft.VisualStudioCode
```

**Verify:** open VS Code from the Start menu. If it opens, you're done.

**Recommended extensions** (install from the Extensions panel inside VS Code, `Ctrl+Shift+X`):

- **Python** (Microsoft) — language support
- **Pylance** (Microsoft) — type checking (auto-installs with Python extension)
- **Ruff** (Astral Software) — linter and formatter, integrates with our pre-commit hooks
- **GitLens** (GitKraken) — better git integration in the editor
- **Even Better TOML** — for editing `pyproject.toml`

You can install all of them in one go from PowerShell:

```powershell
code --install-extension ms-python.python
code --install-extension ms-python.vscode-pylance
code --install-extension charliermarsh.ruff
code --install-extension eamodio.gitlens
code --install-extension tamasfe.even-better-toml
```

---

## 7. Node.js LTS

**What it is:** JavaScript runtime. **You won't write any JavaScript** — we need Node.js because Claude Code is distributed as an npm package, and `npm` is bundled with Node.

**Install:**

```powershell
winget install OpenJS.NodeJS.LTS
```

**Close and reopen PowerShell.**

**Verify:**

```powershell
node --version
npm --version
```

Expected: Node v20.X.X or higher, npm 10.X.X or higher.

---

## 8. Claude Code

**What it is:** the agentic AI assistant we're going to be using throughout this project. It runs in the terminal, reads `CLAUDE.md`, respects the hooks defined in `.claude/settings.json`, and integrates with VS Code.

**Install:**

```powershell
npm install -g @anthropic-ai/claude-code
```

The `-g` means "install globally" (available system-wide, not just in one project).

**Verify:**

```powershell
claude --version
```

Expected: some version string. The Claude Code CLI evolves rapidly, exact version doesn't matter — just confirm it runs.

> We will configure Claude Code (`claude config`, login, etc.) in `03-local-environment.md` after we have the repo cloned.

---

## 9. Power BI Desktop

**What it is:** the application where you'll build the dashboard. You know it well already.

**Install** (use Microsoft Store — auto-updates, no manual upgrades to manage):

1. Open Microsoft Store from the Start menu.
2. Search for "Power BI Desktop".
3. Click "Install" (the publisher should be Microsoft Corporation).

Alternatively from PowerShell:

```powershell
winget install Microsoft.PowerBI
```

**Verify:** open Power BI Desktop from the Start menu. If it opens and you see the welcome screen, you're done.

> We won't connect Power BI Desktop to anything yet. The Athena ODBC driver and the MCP setup happen in `04-power-bi-setup.md`, after the AWS pipeline is producing data.

---

## 10. Optional but very useful

These are not strictly required, but make life much better. Install if you want, skip if not.

**Windows Terminal** (modern terminal with tabs, profiles, themes) — usually pre-installed on Windows 11; on Windows 10:

```powershell
winget install Microsoft.WindowsTerminal
```

**`jq`** (JSON parser for the command line — useful for AWS CLI output):

```powershell
winget install jqlang.jq
```

**`gh copilot` extension** (GitHub Copilot from CLI) — only if you have a Copilot subscription:

```powershell
gh extension install github/gh-copilot
```

---

## Sanity check — everything together

Run all of these in a fresh PowerShell window. Every one should print a version number, none should error.

```powershell
python --version
uv --version
git --version
gh --version
aws --version
code --version
node --version
npm --version
claude --version
```

If any of these fails, fix it before moving on. **Do not proceed to the next guide with a broken tool** — debugging cascades is much harder than debugging one thing.

---

## What's next

→ `02-aws-account.md` — create your AWS account, configure IAM and budget alerts, set up the AWS CLI.
