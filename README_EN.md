# DrissionPage Skill

**[中文](README.md)**

`dp` is a browser automation and site workflow Skill for Skill-capable clients. It is built on
[DrissionPage](https://github.com/g1879/DrissionPage), acquires a connectable Chromium
debug address through a browser provider, and attaches to that browser for screenshots,
scraping, login, form filling, file upload/download, new-tab handling, and reusable site
workflow discovery.

This repository publishes the universal source bundle. `SKILL.md` is the agent-facing execution
contract, `templates/` contains runtime helpers, and `references/` contains templates and API notes
that agents read only when needed. Runtime state is generated in the consuming project's `.dp/`
workspace, not in this source repository.

---

## Design Model

### Provider-first

Browser tasks resolve a browser provider first, then attach through the debug address returned by
that provider. Plain remote-debugging port attachment is modeled as the runtime-managed
`cdp-port` provider instead of being special-cased in every script.

### Extensible Providers

The `dp` core provides the provider contract and loader only. It does not embed private APIs for
AdsPower, fingerprint browsers, or specific launchers. Custom providers live in the target
workspace as `.dp/providers/<name>.py` and are maintained by the client or user.

### Workflow-first

A workflow is a repeatable path for a site and intent: entry state, prerequisites, ordered steps,
state checks, output contract, and reusable script. Screenshots, scraping, login, forms, upload,
download, and new-tab handling are execution primitives that can compose a workflow.

### Reuse and Discovery First

Site scripts are saved under `.dp/projects/<site>/scripts/`. Later tasks for the same site, intent,
entry state, URL family, or output contract should reuse or repair existing scripts first,
preserving login flows, stable selectors, historical fixes, and site-specific knowledge. When no
high-confidence reusable workflow exists, use workflow discovery before saving a new script.

### Native Interaction First

Clicks, inputs, uploads, downloads, and new-tab handling should use DrissionPage / CDP native
capabilities first. JavaScript clicks, direct `value` mutation, and manually dispatched DOM events
are last-resort fallbacks.

---

## Capabilities

Core capabilities:

| Capability | Examples |
|------------|----------|
| Site workflow reuse | Find saved scripts by `site + intent`, entry state, URL, and output contract; reuse or repair first |
| Workflow discovery | Explore page structure, selector candidates, state checks, and output contracts for low-confidence reusable workflows |
| Provider-first attach | Acquire a Chromium debug address through the workspace provider and reuse real profiles or sessions |
| Run archive | Store each execution in one run-dir with semantic output files |
| Action templates | Use templates for screenshot, scrape, login, form, upload, download, new tab, WebPage, and SessionPage primitives |

Common execution primitives:

| Primitive | Examples |
|-----------|----------|
| Screenshot | Full-page, element, and region screenshots |
| Scrape | List extraction, detail extraction, paginated scraping |
| Login | Username/password login, reuse an already logged-in browser |
| Form | Fill fields, submit forms, save result screenshots |
| Upload | Normalize local file paths and fill upload controls |
| Download | Single-target downloads, semantic filenames, cross-platform download paths |
| New tab | Click a link, switch to the new tab, and continue work |
| Hybrid mode | Browser login plus cookie sync into requests/session mode |
| Custom provider | Start or locate a browser through a workspace provider, then attach |

---

## Quick Start

### Prerequisites

- A client framework that supports the Skill specification, such as Claude Code, Codex, or another compatible implementation
- Python 3.10+
- A writable project directory where `.dp/` can be created
- If the effective default provider is `cdp-port`, a Chromium / Chrome instance already exposing a remote debugging port

### Install the Skill

```bash
git clone https://github.com/Wool-yang/DrissionPage-Skill.git
cd DrissionPage-Skill

# Install to your client's skill directory. Adjust the path for your client.
python scripts/install.py --target /path/to/skills/dp
```

### Initialize a Workspace

Run this from the project root where browser tasks should execute:

```bash
python /path/to/skills/dp/scripts/doctor.py
```

This creates `.dp/` in the current project root, including the virtual environment, runtime helpers,
default provider, configuration, and version state. `.dp/` is local runtime state and should not be
committed to version control.

### Attach with `cdp-port`

If no custom provider is configured, the workspace default provider is `cdp-port`. It does not
launch a browser; it only attaches to an already running Chromium / Chrome instance with remote
debugging enabled.

```bash
# macOS / Linux
google-chrome --remote-debugging-port=<port> --user-data-dir=/tmp/chrome-debug

# Windows PowerShell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=<port> --user-data-dir="$env:TEMP\chrome-debug"
```

When the effective default provider remains `cdp-port`, scripts must receive an explicit port,
for example `--port <port>`. `dp` does not silently scan common ports.

### Switch to a Custom Provider

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

Generic workflow templates inherit this default provider. A script should pin a provider name only
when the task explicitly depends on that provider. See `references/provider-contract.md` for the
provider contract.

---

## Usage

After installation and workspace initialization, describe the task naturally in a supported client:

> "Take a full-page screenshot of https://news.ycombinator.com"
>
> "Scrape all product names and prices from the current page and save them as JSON"
>
> "I am already logged in; reuse the current browser session to request the orders API"

When an agent uses `dp`, it typically:

1. Checks whether `.dp/` is ready and runs doctor when needed
2. Resolves the default provider and acquires a debug address through it
3. Chooses `ChromiumPage`, `WebPage`, or `SessionPage`
4. Searches for saved scripts and reuses or repairs them first
5. Runs workflow discovery when reusable workflow matching is low-confidence
6. Saves output under `.dp/projects/<site>/output/<script-name>/<timestamp>/`
7. Saves reusable workflows and maintains the managed section of the site README

---

## Workflow Discovery

Workflow discovery is the exploration pass used when the user needs a reusable site workflow and
existing scripts, README notes, or history do not provide a high-confidence path. It is above the
action templates: it decides how screenshots, scraping, login, forms, downloads, and other actions
compose into a stable workflow.

Temporary probe scripts live in `.dp/tmp/`. Discovery evidence, including `workflow-draft.md`, lives
in the run-dir for that discovery pass:

```text
.dp/projects/<site>/output/workflow-discovery-<intent>/<timestamp>/
```

Only after the path is repeatable, the output contract is stable, and the saved script can mark
`status: ok` should the workflow enter `.dp/projects/<site>/scripts/` and the managed site README
section.

---

## Source Bundle Layout

```text
.
├── SKILL.md                    # Agent-facing execution contract
├── templates/                  # Runtime library copied to .dp/lib/ by doctor
│   ├── connect.py              # Provider-first browser connection helpers
│   ├── download_correlation.py # Single-target download request-correlation layer
│   ├── output.py               # Run directory and output path management
│   ├── utils.py                # Screenshot, click, input, upload, and download helpers
│   ├── _dp_compat.py           # Compatibility shim for DrissionPage internals
│   └── providers/
│       └── cdp-port.py         # Runtime-managed fallback provider
├── scripts/                    # Install, doctor, smoke, and validation tools
├── references/                 # Agent reference docs, read on demand
└── evals/                      # Minimal smoke prompts and manual acceptance checklist
```

## Workspace Layout

```text
.dp/
├── .venv/                      # Auto-created Python virtual environment
├── lib/                        # Runtime library copy managed by doctor
├── providers/                  # Workspace provider implementations
├── tmp/
│   ├── _run.py                 # Overwritable one-off temporary script
│   ├── _workflow_discovery_<site>_<intent>.py
│   │                           # Semantic temporary script for multi-step discovery
│   └── _out/                   # Temporary output
├── projects/
│   └── <site-name>/
│       ├── README.md           # Site index; Scripts section is agent-managed
│       ├── scripts/            # Saved reusable scripts
│       └── output/             # Execution outputs archived by script/workflow and timestamp
├── config.json                 # Workspace config, including default_provider
└── state.json                  # Bundle/runtime version state
```

`.dp/` belongs to the local workspace. It may contain virtual environments, runtime state, browser
profile-related data, or task outputs. Do not publish it as part of the source bundle.

---

## Client Adaptation

This repository defines the cross-client bundle and runtime contract. It is not tied to a single
client framework. Different clients may keep their own adapter files in the installed skill
directory; those files belong to the client adapter layer and are not part of the `dp` core contract.

- Codex: follow the official OpenAI Codex Skills documentation (https://developers.openai.com/codex/skills)
- Claude Code: follow the official Anthropic Claude Code Skills documentation (https://docs.anthropic.com/en/docs/claude-code/skills)

`scripts/install.py` syncs upstream bundle files while preserving target files that are not part of
the upstream manifest. Client-specific supplementary files can coexist with the `dp` bundle and are
not removed during normal upgrades.

---

## Development and Release

- When changing runtime templates (`templates/`), bump both `runtime-lib-version` and `bundle-version`
- When changing only docs, scripts, or references, bump only `bundle-version`
- Run `scripts/validate_bundle.py` before release
- See `CONTRIBUTING_EN.md` for the full rules

## Dependencies

- [DrissionPage](https://github.com/g1879/DrissionPage) `>=4.1.1,<4.2`
- Python standard library

## License

[MIT](LICENSE)
