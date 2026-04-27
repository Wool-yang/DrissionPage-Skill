# Contributing

**[中文](CONTRIBUTING.md)**

The source of truth is the source bundle in this repository. Before release, make sure `.dp/`,
virtual environments, browser profiles, temporary outputs, and local runtime state are not present
in the repository.

## Version Fields

`SKILL.md` front matter contains two version fields:

| Field | Meaning | When to bump |
|-------|---------|--------------|
| `runtime-lib-version` | Workspace runtime library version | Any runtime code change under `templates/` |
| `bundle-version` | Whole source bundle version | Any distributed file change |

Format: `YYYY-MM-DD.N`, where `N` is the N-th release of that day.

## Bump Rules

- If only README, references, evals, scripts, or other non-runtime files change, bump only `bundle-version`
- If `templates/connect.py`, `templates/output.py`, `templates/utils.py`,
  `templates/download_correlation.py`, `templates/_dp_compat.py`, or provider templates change,
  bump both `runtime-lib-version` and `bundle-version`
- If another release has already happened on the same day, increment `.N`; do not reuse a previous version

## Doctor Refresh Semantics

`doctor.py` uses `.dp/state.json` to decide whether a workspace needs refresh:

- When `runtime-lib-version` changes, doctor syncs `.dp/lib/` and runtime-managed providers,
  then updates `.dp/state.json`
- When only `bundle-version` changes, doctor refreshes workspace docs/state without rebuilding the
  venv or syncing runtime-managed code

For that reason, changing runtime templates without bumping `runtime-lib-version` leaves existing
workspaces on old helpers. That is a release error, not a doctor behavior issue.

## Release Checklist

1. Edit source bundle files
2. Bump `SKILL.md` according to the rules above
3. Run bundle validation:
   ```bash
   python scripts/validate_bundle.py
   ```
4. If a local installed copy is needed for testing, sync from the source bundle:
   ```bash
   python scripts/install.py --target /path/to/skills/dp
   ```
5. Run doctor or smoke in the target workspace to confirm the installed copy and `.dp/state.json`
   reflect the new version

## Documentation Principles

- `SKILL.md` is the agent-facing execution contract, not a marketing page
- `README*.md` is for human readers and explains the design model, installation, usage, and layout
- `references/*.md` carries topic-specific details for progressive disclosure
- `evals/*` should stay operational and testable, not just abstract principles
- Do not delete important boundaries just to make text shorter; documentation should be reasonable,
  accurate, and executable first
