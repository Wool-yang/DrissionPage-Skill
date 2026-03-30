# Contributing

**[中文](CONTRIBUTING.md)**

## Versioning

`SKILL.md` contains two version fields in its front matter. Update them before each release:

| Field | Meaning | When to bump |
|-------|---------|--------------|
| `runtime-lib-version` | Runtime library version | Any change to `templates/` |
| `bundle-version` | Overall bundle version | Any file change |

Format: `YYYY-MM-DD.N` (N-th release of the day)

When both fields are bumped (templates changed), re-run `doctor.py` to refresh `.dp/lib/` in the workspace.
When only `bundle-version` is bumped (docs/scripts only), `doctor.py` can be skipped.

## Release Checklist

1. Edit source files
2. Bump the relevant fields in `SKILL.md` per the table above
3. Run `scripts/validate_bundle.py` to verify bundle integrity
4. Sync local install copy (if needed for testing):
   ```bash
   python scripts/install.py --target /path/to/skills/dp
   ```
