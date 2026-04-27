# DrissionPage Skill

**[中文](README.md)**

`dp` is a browser automation Skill for Skill-capable clients. It is built on
[DrissionPage](https://github.com/g1879/DrissionPage), acquires a connectable Chromium
debug address through a browser provider, and attaches to that browser for screenshots,
scraping, login, form filling, file upload/download, new-tab workflows, and related web tasks.

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

### Reuse First

Site scripts are saved under `.dp/projects/<site>/scripts/`. Later tasks for the same site, intent,
or URL family should reuse or repair existing scripts first, preserving login flows, stable
selectors, historical fixes, and site-specific knowledge.

### Native Interaction First

Clicks, inputs, uploads, downloads, and new-tab handling should use DrissionPage / CDP native
capabilities first. JavaScript clicks, direct `value` mutation, and manually dispatched DOM events
are last-resort fallbacks.

---

## Capabilities

| Task | Examples |
|------|----------|
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
5. Generates and runs a temporary script only when needed
6. Saves output under `.dp/projects/<site>/output/<script-name>/<timestamp>/`
7. Saves reusable workflows and maintains the managed section of the site README

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
│   ├── _run.py                 # Temporary script for the current execution
│   └── _out/                   # Temporary output
├── projects/
│   └── <site-name>/
│       ├── README.md           # Site index; Scripts section is agent-managed
│       ├── scripts/            # Saved reusable scripts
│       └── output/             # Execution outputs archived by task and timestamp
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
