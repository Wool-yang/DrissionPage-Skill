# Workspace Contract Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收口 `doctor.py`、`smoke.py`、文档与 validator 的 workspace readiness contract，消除 stale state / provider normalization / managed asset sync 的分叉行为。

**Architecture:** 让 `scripts/doctor.py` 提供结构化 workspace 评估结果，`scripts/smoke.py` 复用这套结果而不是维护第二套判定。doctor 同时收紧 config 修复与 managed asset fail-fast 语义，validator 则把新的 preflight contract 硬化为可回归检查。

**Tech Stack:** Python 3.10+, source bundle scripts (`doctor.py`, `smoke.py`, `validate_bundle.py`), regression tests in `scripts/test_helpers.py`

---

## File Map

- Create: `docs/superpowers/specs/2026-03-31-workspace-contract-unification-design.md`
- Create: `docs/superpowers/plans/2026-03-31-workspace-contract-unification.md`
- Modify: `scripts/test_helpers.py`
- Modify: `scripts/doctor.py`
- Modify: `scripts/smoke.py`
- Modify: `scripts/validate_bundle.py`
- Modify: `SKILL.md`
- Modify: `evals/smoke-checklist.md`

### Task 1: Lock the Contract with Failing Tests

**Files:**
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Add failing tests for doctor config repair and fail-fast behavior**

Add tests that lock the intended behavior:

```python
def test_doctor_init_repairs_blank_default_provider() -> None:
    ...
    (patched_dp / "config.json").write_text('{"default_provider": ""}', encoding="utf-8")
    result = _doctor.init()
    config = _json.loads((patched_dp / "config.json").read_text(encoding="utf-8"))
    check("init: 空 default_provider 被修复", result is True and config.get("default_provider") == "cdp-port", str(config))


def test_doctor_init_normalizes_default_provider() -> None:
    ...
    (patched_dp / "config.json").write_text('{"default_provider": " CDP-PORT "}', encoding="utf-8")
    result = _doctor.init()
    config = _json.loads((patched_dp / "config.json").read_text(encoding="utf-8"))
    check("init: default_provider 被规范化", result is True and config.get("default_provider") == "cdp-port", str(config))


def test_doctor_init_fails_without_managed_provider_template() -> None:
    ...
    original = _doctor.PROVIDER_TEMPLATES
    _doctor.PROVIDER_TEMPLATES = tmp / "missing-providers"
    result = _doctor.init()
    check("init: 缺 managed provider 模板返回 False", result is False, repr(result))
    check("init: 缺 managed provider 模板不写 state", not (patched_dp / "state.json").exists(), str(patched_dp / "state.json"))
```

- [ ] **Step 2: Add failing tests for smoke stale state and normalized provider handling**

Add tests like:

```python
def test_smoke_check_workspace_requires_matching_state_versions() -> None:
    ...
    (dp / "state.json").write_text('{"runtime_lib_version":"old","bundle_version":"old"}', encoding="utf-8")
    result = smoke_mod._check_workspace()
    check("smoke: 旧 state 版本返回错误", result is not None and "版本" in result, repr(result))


def test_smoke_main_normalizes_default_provider_before_port_gate() -> None:
    ...
    (dp / "config.json").write_text('{"default_provider":" CDP-PORT "}', encoding="utf-8")
    ...
    check("smoke: 规范化后的 cdp-port 仍要求显式 --port", got_exit_2, detail)
```

- [ ] **Step 3: Add failing validator test for preflight contract markers**

Add a test like:

```python
def test_validate_rule_markers_preflight_requires_workspace_contract_tokens() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _create_required_bundle_tree(root)
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        skill = skill.replace(".dp/config.json", "config.json")
        (root / "SKILL.md").write_text(skill, encoding="utf-8")
        _expect_fail(
            "validate_rule_markers: Preflight 缺少 workspace contract token 应失败",
            lambda: _vb.validate_rule_markers(root),
        )
```

- [ ] **Step 4: Run tests and verify RED**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- FAIL on the new doctor repair / smoke stale state / validator marker tests
- Existing passing tests remain valuable regression coverage

### Task 2: Make Doctor the Readiness Authority

**Files:**
- Modify: `scripts/doctor.py`
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Introduce structured workspace evaluation**

Implement a single entry point in `scripts/doctor.py`:

```python
def evaluate_workspace(workspace: Path = WORKSPACE) -> dict[str, object]:
    return {
        "issues": issues,
        "default_provider": default_provider,
        "runtime_lib_version": runtime_v,
        "bundle_version": bundle_v,
        "state_runtime_lib_version": state_runtime_v,
        "state_bundle_version": state_bundle_v,
    }
```

Also refactor:

```python
def resolve_venv_python(venv: Path) -> Path: ...
def venv_python() -> Path:
    return resolve_venv_python(VENV)
```

- [ ] **Step 2: Centralize scripts-side provider normalization**

Add a helper like:

```python
def normalize_provider_name(raw: str) -> str:
    key = raw.strip().lower()
    if not re.fullmatch(r"[a-z0-9-]+", key):
        raise ValueError(...)
    return key
```

Use it for config validation and repair.

- [ ] **Step 3: Tighten config repair semantics**

Update `_write_default_config()` so that:

```python
config = _read_config()
if not isinstance(config, dict):
    config = {}
raw = config.get("default_provider")
if not isinstance(raw, str) or not raw.strip():
    config["default_provider"] = "cdp-port"
else:
    config["default_provider"] = normalize_provider_name(raw)
```

And make `evaluate_workspace()` add an issue when a non-empty provider name is invalid.

- [ ] **Step 4: Fail fast on missing managed assets**

Before copying workspace assets in `init()`, verify every required source template exists:

```python
def _required_source_assets() -> list[Path]:
    return [
        TEMPLATES / "connect.py",
        TEMPLATES / "output.py",
        TEMPLATES / "utils.py",
        TEMPLATES / "_dp_compat.py",
        PROVIDER_TEMPLATES / "cdp-port.py",
    ]
```

Abort `init()` immediately when any asset is missing; do not write state.

- [ ] **Step 5: Re-run tests and verify GREEN for doctor behavior**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- doctor repair / normalization / fail-fast tests PASS
- no regressions in existing doctor tests

### Task 3: Make Smoke Reuse Doctor’s Contract

**Files:**
- Modify: `scripts/smoke.py`
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Remove smoke’s duplicate readiness rules**

Refactor `smoke.py` so that `_check_workspace()` delegates to doctor:

```python
def _evaluate_workspace() -> dict:
    return _doctor_mod.evaluate_workspace(WORKSPACE)


def _check_workspace() -> str | None:
    issues = _evaluate_workspace()["issues"]
    return issues[0] if issues else None
```

- [ ] **Step 2: Reuse normalized default provider in the main port gate**

Update:

```python
default_provider = _evaluate_workspace().get("default_provider")
if need_browser and default_provider == DEFAULT_FALLBACK_PROVIDER:
    ...
```

Remove the old `_get_default_provider()` string semantics if it becomes redundant.

- [ ] **Step 3: Re-run tests and verify GREEN for smoke**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- stale state test PASS
- normalized `CDP-PORT` still requires explicit `--port`
- previous smoke regression tests still PASS

### Task 4: Harden Validator and Update Canonical Docs

**Files:**
- Modify: `scripts/validate_bundle.py`
- Modify: `SKILL.md`
- Modify: `evals/smoke-checklist.md`
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Extend validator marker checks**

Tighten `validate_rule_markers()` or split a helper so that the Preflight section must contain all of:

```python
(".dp/config.json", "default_provider", ".dp/providers/cdp-port.py", ".dp/state.json", "runtime_lib_version", "bundle_version")
```

- [ ] **Step 2: Align canonical prose with the new contract**

Ensure:

- `SKILL.md` preflight section matches doctor’s readiness fields exactly
- `evals/smoke-checklist.md` says smoke should only run when state versions match
- wording does not imply that missing `state.json` or stale bundle is acceptable

- [ ] **Step 3: Bump bundle metadata if source bundle contract changed**

Because scripts/docs behavior changed, update `SKILL.md`:

```yaml
metadata:
  bundle-version: "2026-03-31.1"
  runtime-lib-version: "2026-03-30.5"
```

Only bump `runtime-lib-version` if a copied runtime lib file changes. This plan does not require that.

- [ ] **Step 4: Re-run tests and validator**

Run:

```bash
python scripts/test_helpers.py
python scripts/validate_bundle.py
```

Expected:
- ALL PASSED
- `[OK] bundle looks clean`

### Task 5: Final Verification and Local Integration Check

**Files:**
- Modify: working tree only as required by earlier tasks

- [ ] **Step 1: Self-review the spec and plan for placeholders / contradictions**

Run:

```python
from pathlib import Path

paths = [
    Path("docs/superpowers/specs/2026-03-31-workspace-contract-unification-design.md"),
    Path("docs/superpowers/plans/2026-03-31-workspace-contract-unification.md"),
]
patterns = ["TO" + "DO", "TB" + "D", "implement" + " later", "fill in" + " details"]
for path in paths:
    text = path.read_text(encoding="utf-8")
    for pattern in patterns:
        if pattern in text:
            raise SystemExit(f"{path}: found placeholder pattern {pattern!r}")
```

Expected:
- no matches

- [ ] **Step 2: Run the complete evidence set**

Run:

```bash
python scripts/test_helpers.py
python scripts/validate_bundle.py
git diff -- \
  docs/superpowers/specs/2026-03-31-workspace-contract-unification-design.md \
  docs/superpowers/plans/2026-03-31-workspace-contract-unification.md \
  scripts/doctor.py scripts/smoke.py scripts/validate_bundle.py scripts/test_helpers.py \
  SKILL.md evals/smoke-checklist.md
```

Expected:
- tests and validator pass
- diff only contains this contract-unification batch

- [ ] **Step 3: If bundle-version was bumped, sync installed skill and refresh workspace**

Run only after source verification passes:

```bash
python scripts/install.py <installed-skill-dir>
python <installed-skill-dir>/scripts/doctor.py
python <installed-skill-dir>/scripts/doctor.py --check
```

Expected:
- installed copy updated
- outer workspace `.dp/state.json` refreshed to the new `bundle-version`
- `doctor.py --check` exits 0
