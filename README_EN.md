# DrissionPage Skill

**[中文](README.md)**

`dp` is a browser automation and site workflow Skill for Skill-capable clients. It is built on
[DrissionPage](https://github.com/g1879/DrissionPage), attaches to a connectable Chromium debug
address through a browser provider, and supports screenshots, scraping, login, form filling,
file upload/download, new-tab handling, and reusable site workflow discovery.

This repository publishes the source bundle. Runtime state, virtual environments, browser state,
and task outputs are generated in the consuming project's `.dp/` workspace, not in this repository.

## Concepts

- **Provider-first**: browser tasks resolve a browser provider first, then attach through the debug address returned by that provider. Plain remote-debugging port attachment is modeled as the runtime-managed `cdp-port` provider.
- **Workflow-first**: a workflow is a repeatable path for a site and intent, including entry state, key steps, state checks, output contract, and reusable script.
- **Reuse / discovery first**: later tasks for the same site should reuse or repair scripts under `.dp/projects/<site>/scripts/` before creating new ones; low-confidence paths use workflow discovery first.
- **Native interaction first**: clicks, inputs, uploads, downloads, and new-tab handling should use DrissionPage / CDP native capabilities first. JavaScript is a fallback.

## Quick Start

### Prerequisites

- A client framework that supports the Skill specification, such as Codex, Claude Code, or another compatible implementation
- Python 3.10+
- A writable project directory where `.dp/` can be created
- If using the default `cdp-port` provider, Chromium / Chrome already exposing a remote debugging port

### Install the Skill

```bash
git clone https://github.com/Wool-yang/DrissionPage-Skill.git
cd DrissionPage-Skill
python scripts/install.py --target /path/to/skills/dp
```

### Initialize a Workspace

Run this from the project root where browser tasks should execute:

```bash
python /path/to/skills/dp/scripts/doctor.py
```

`doctor.py` creates or refreshes `.dp/`, including the virtual environment, runtime helpers,
default provider, configuration, and version state. `.dp/` is local runtime state and should not be
committed to version control.

To check without repairing:

```bash
python /path/to/skills/dp/scripts/doctor.py --check
```

## Browser Entry

### Use `cdp-port`

If no custom provider is configured, the workspace default provider is `cdp-port`. It does not
launch a browser; it only attaches to an already running Chromium / Chrome instance with remote
debugging enabled.

```bash
# macOS / Linux
google-chrome --remote-debugging-port=<port> --user-data-dir=/tmp/chrome-debug
```

```powershell
# Windows PowerShell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=<port> --user-data-dir="$env:TEMP\chrome-debug"
```

When the effective default provider remains `cdp-port`, scripts must receive an explicit
`--port <port>`. `dp` does not silently scan common ports.

### Use a Custom Provider

Provide a workspace provider implementation:

```text
.dp/providers/<name>.py
```

Then update `.dp/config.json`:

```json
{
  "default_provider": "<name>"
}
```

Generic workflow templates inherit this default provider. See `references/provider-contract.md`
for the provider contract.

## Usage

After installation and workspace initialization, describe the browser task naturally in a supported
client:

> "Take a full-page screenshot of https://news.ycombinator.com"
>
> "Scrape all product names and prices from the current page and save them as JSON"
>
> "I am already logged in; reuse the current browser session to request the orders API"

When an agent uses `dp`, it typically checks `.dp/`, resolves the provider, chooses `ChromiumPage` /
`WebPage` / `SessionPage`, searches for saved scripts, and saves outputs under
`.dp/projects/<site>/output/...`.

Temporary script runner: keep scripts in `.dp/tmp/`, use `.dp/.venv/Scripts/python.exe` on Windows,
and use `.dp/.venv/bin/python` on macOS / Linux. Script headers, runner commands, and action
templates live in `references/action-templates.md`.

## Layout

Source bundle:

```text
.
├── SKILL.md                    # Agent-facing entry contract
├── templates/                  # Runtime helpers copied to .dp/lib/ by doctor
├── scripts/                    # Install / doctor / smoke / validation tools
├── references/                 # Agent reference docs, read on demand
└── evals/                      # Smoke prompts and manual acceptance checklist
```

Workspace:

```text
.dp/
├── .venv/                      # Python virtual environment
├── lib/                        # Runtime helper copy
├── providers/                  # Workspace provider implementations
├── tmp/                        # Temporary scripts and temporary outputs
├── projects/<site>/            # Site scripts, README, and output archive
├── config.json                 # default_provider and other config
└── state.json                  # Bundle/runtime version state
```

## References

- Agent entry and routing rules: `SKILL.md`
- Script headers, runner, and action templates: `references/action-templates.md`
- Workflow discovery: `references/workflow-discovery.md`
- Provider contract: `references/provider-contract.md`
- Mode selection: `references/mode-selection.md`
- DrissionPage quick reference: `references/interface.md`
- Site README managed section: `references/site-readme.md`

## Development and Release

- When changing runtime templates (`templates/`), bump both `runtime-lib-version` and `bundle-version`
- When changing only docs, scripts, or references, bump only `bundle-version`
- Run `python scripts/validate_bundle.py` before release
- See `CONTRIBUTING_EN.md` for the full rules

## Dependencies

- [DrissionPage](https://github.com/g1879/DrissionPage) `>=4.1.1,<4.2`
- Python standard library

## License

[MIT](LICENSE)
