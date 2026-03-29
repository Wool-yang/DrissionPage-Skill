# DrissionPage Skill

**[中文](README.md)**

A browser automation Skill for any client framework that supports the Skill specification. Built on [DrissionPage](https://github.com/g1879/DrissionPage), it takes over the user's already-open Chromium browser to perform screenshots, scraping, login, form filling, file upload/download, and more.

`dp-skill-source/` is the public installation source and single source of truth, defining a cross-client Skill contract — not a private implementation tied to any one host.

---

## Core Philosophy

- **Take over, don't spawn**: Connects to the user's existing browser via the remote debugging port, reusing active sessions and cookies. Never launches or closes the browser on its own.
- **Reuse, don't rewrite**: Automation scripts are saved per-site and reused on subsequent similar tasks instead of being regenerated.
- **Native interaction first**: Clicks and inputs use DrissionPage's built-in native interaction chain — no raw DOM event manipulation, closer to real user behavior.

## What It Can Do

| Task | Examples |
|------|---------|
| Screenshot | Full-page, region-specific |
| Scrape | List extraction, paginated scraping |
| Login | Username/password, session persistence |
| Form | Fill and submit forms |
| Upload | File upload (direct input + file chooser) |
| Download | File download (with cross-platform path handling) |
| New tab | Open links and interact with new tabs |
| Hybrid mode | Browser login + efficient requests |

## Installation

### Prerequisites

- Any client framework that supports the Skill specification (e.g. Claude Code, Codex, or other compatible implementations)
- Python 3.10+
- Chromium / Chrome with remote debugging enabled (`--remote-debugging-port=9222`)

### Install the Skill

```bash
# Clone the repo
git clone https://github.com/Wool-yang/DrissionPage-Skill.git

# Install to your client's skill directory (adjust the path as needed)
python scripts/install.py --target /path/to/skills/dp
```

### Initialize the Workspace

Run this in your project root to create the `.dp/` workspace (includes virtual environment and runtime libs):

```bash
python /path/to/skills/dp/scripts/doctor.py
```

### Enable Browser Remote Debugging

```bash
# macOS / Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug

# Windows (PowerShell)
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 --user-data-dir="$env:TEMP\chrome-debug"
```

## Usage

Once installed and initialized, describe your task in natural language inside a supported client:

> "Take a full-page screenshot of https://news.ycombinator.com"
>
> "Scrape all product names and prices from this page, save as JSON"
>
> "Log me into this site, username is xxx"

The Skill will automatically:
1. Check workspace version and upgrade if needed
2. Connect to the existing browser (scanning ports `9222 / 9333 / 9444 / 9111`)
3. Look for previously saved scripts for this site/task and reuse them
4. Generate and execute the automation script
5. Save output to `.dp/projects/<site>/output/<task>/<timestamp>/`

## Repository Structure

```
.
├── SKILL.md                  # Skill descriptor (read by any Skill-spec-compatible client)
├── templates/                # Runtime library (copied to .dp/lib/ during workspace init)
│   ├── connect.py            # Browser connection helper
│   ├── output.py             # Output path management
│   ├── utils.py              # Common operations (screenshot, click, input, upload, download)
│   └── _dp_compat.py         # DrissionPage internal API compatibility shim
├── scripts/                  # Management tools
│   ├── doctor.py             # Workspace init and health check
│   ├── install.py            # Bundle sync installer
│   ├── list-scripts.py       # Enumerate saved scripts
│   ├── smoke.py              # Automated acceptance tests
│   ├── test_helpers.py       # Unit test suite
│   └── validate_bundle.py    # Pre-release bundle validation
├── references/               # Agent reference docs
│   ├── workflows.md          # Workflow code templates
│   ├── mode-selection.md     # Object selection decision matrix
│   ├── interface.md          # DrissionPage API quick reference
│   └── site-readme.md        # Site README specification
└── evals/                    # Evaluation and acceptance
    ├── evals.json            # 11 minimal smoke prompts
    └── smoke-checklist.md    # Manual acceptance checklist
```

## Client Adaptation & Optional Supplementary Files

This repo only defines the universal `dp` bundle content and runtime contract. It is not tied to any specific client framework. Different clients may **optionally** add client-specific files to the install directory before use. These files belong to the client-side adapter layer and are not part of the cross-client core contract.

### 1. Codex

For Codex-specific directory layout, discovery locations, optional metadata files, and invocation rules, follow the official OpenAI docs:

- https://developers.openai.com/codex/skills

### 2. Claude Code

For Claude Code-specific skill directories, frontmatter extensions, and invocation rules, follow the official Anthropic docs:

- https://docs.anthropic.com/en/docs/claude-code/skills

### Compatibility Guarantee

`scripts/install.py` only syncs upstream bundle files, preserving any files in the target directory that are not part of the upstream manifest. Client-specific supplementary files coexist with the `dp` bundle and are not removed during normal upgrades.

## Workspace Directory (`.dp/`)

```
.dp/
├── .venv/                    # Auto-created Python virtual environment
├── lib/                      # Runtime library copy (managed by doctor.py)
├── tmp/
│   ├── _run.py               # Temporary script for current execution
│   └── _out/                 # Temporary output
├── projects/
│   └── <site-name>/
│       ├── README.md         # Site index
│       ├── scripts/          # Saved reusable scripts
│       └── output/           # Execution output archived by task and timestamp
└── state.json                # Version state (used by preflight check)
```

> `.dp/` contains local runtime artifacts and should not be committed to version control.

## Dependencies

- [DrissionPage](https://github.com/g1879/DrissionPage) (`>=4.1.1,<4.2`): The core browser automation library. The runtime library and workflow design in this project are built on DrissionPage's API.
- Python standard library (no other third-party dependencies)

## Versioning

| Field | Meaning | When to bump |
|-------|---------|--------------|
| `runtime-lib-version` | Runtime library version | Any change to `templates/` |
| `bundle-version` | Overall bundle version | Any file change |

Format: `YYYY-MM-DD.N` (N-th release of the day)

## License

[MIT](LICENSE)
