# Provider Readiness and File Helper Contract Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收口默认 provider 就绪判定与 top-level file helper 边界，让 doctor/smoke/SKILL/validator 对这两个 contract 缺口使用同一套语义。

**Architecture:** 先在 `scripts/test_helpers.py` 写失败测试，锁定“默认 provider 实现文件缺失”与“remote file helper 必须 fail fast”这两类回归场景。然后在 `scripts/doctor.py` 补 selected-provider 存在性检查，在 `SKILL.md` / `evals/smoke-checklist.md` 补 prose contract，并用 `scripts/validate_bundle.py` 把这些规则硬化成章节级校验。

**Tech Stack:** Python 3.10+, source bundle docs/scripts, regression tests in `scripts/test_helpers.py`

---

## File Map

- Create: `docs/superpowers/specs/2026-03-31-provider-readiness-and-file-helper-contract-closure-design.md`
- Create: `docs/superpowers/plans/2026-03-31-provider-readiness-and-file-helper-contract-closure.md`
- Modify: `scripts/test_helpers.py`
- Modify: `scripts/doctor.py`
- Modify: `scripts/validate_bundle.py`
- Modify: `SKILL.md`
- Modify: `evals/smoke-checklist.md`

### Task 1: Lock the Two Gaps with Failing Tests

**Files:**
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Add failing doctor tests for missing selected provider implementation**

Add tests like:

```python
def test_doctor_check_requires_selected_default_provider_file() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        dp = root / ".dp"
        (dp / ".venv" / "bin").mkdir(parents=True)
        (dp / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
        (dp / "lib").mkdir(parents=True)
        for name in ("connect.py", "output.py", "utils.py", "_dp_compat.py"):
            (dp / "lib" / name).write_text("# ok\n", encoding="utf-8")
        (dp / "providers").mkdir(parents=True)
        (dp / "providers" / "cdp-port.py").write_text("# ok\n", encoding="utf-8")
        (dp / "config.json").write_text('{"default_provider":"adspower"}', encoding="utf-8")
        (dp / "state.json").write_text(
            _json.dumps({
                "bundle_version": _doctor._read_bundle_version(),
                "runtime_lib_version": _doctor._read_runtime_lib_version(),
            }),
            encoding="utf-8",
        )
        with _mock.patch.object(_doctor, "WORKSPACE", dp), \
             _mock.patch.object(_doctor, "resolve_venv_python", return_value=dp / ".venv" / "bin" / "python"), \
             _mock.patch.object(_doctor.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            issues = _doctor.evaluate_workspace(dp)["issues"]
        check("doctor: 缺少当前默认 provider 文件会报错", any("adspower" in s and "providers" in s for s in issues), repr(issues))
```

- [ ] **Step 2: Add failing init fail-fast test for the same scenario**

Add a test like:

```python
def test_doctor_init_fails_when_selected_default_provider_file_missing() -> None:
    ...
    (patched_dp / "config.json").write_text('{"default_provider":"adspower"}', encoding="utf-8")
    result = _doctor.init()
    check("init: 缺少当前默认 provider 文件返回 False", result is False, repr(result))
    check("init: 缺少当前默认 provider 文件不写 state", not (patched_dp / "state.json").exists(), str(patched_dp / "state.json"))
```

- [ ] **Step 3: Add failing validator tests for prose boundaries**

Add tests like:

```python
def test_validate_rule_markers_preflight_requires_selected_provider_presence_boundary() -> None:
    content = _build_skill_md(
        preflight=(
            "工作区根通过 cwd 设定；.dp/.venv 存在且可导入 DrissionPage；"
            ".dp/lib/connect.py、.dp/lib/output.py、.dp/lib/utils.py、.dp/lib/_dp_compat.py 存在；"
            ".dp/config.json 含 default_provider；.dp/providers/cdp-port.py 与 .dp/state.json 存在；"
            "runtime_lib_version / bundle_version 匹配时可跳过 doctor"
        ),
        port="若当前 provider 为 cdp-port，则必须显式传入 browser_profile.port",
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 显式传根路径",
    )
    ...
```

```python
def test_validate_rule_markers_file_helper_requires_remote_fail_fast_boundary() -> None:
    content = _build_skill_md(
        preflight=VALID_PREFLIGHT,
        port=VALID_PORT,
        reuse=VALID_REUSE,
        interaction="upload_file()/download_file() 在传入 launch_info 时会做更安全的本地文件访问判断",
    )
    ...
```

- [ ] **Step 4: Run tests and verify RED**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- 新增 doctor / validator tests FAIL
- 失败信息能直接指向“默认 provider 文件缺失”和“remote fail-fast prose 缺失”

### Task 2: Tighten Doctor Readiness and Init Semantics

**Files:**
- Modify: `scripts/doctor.py`
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Add selected-provider file lookup helper**

Implement helpers such as:

```python
def _provider_file_candidates(name: str, providers_dir: Path) -> tuple[Path, ...]:
    snake = name.replace("-", "_")
    return (
        providers_dir / f"{name}.py",
        providers_dir / f"{snake}.py",
    )


def _selected_provider_issue(name: str, providers_dir: Path) -> str | None:
    if name == "cdp-port":
        return None
    if any(path.is_file() for path in _provider_file_candidates(name, providers_dir)):
        return None
    return (
        f".dp/config.json default_provider={name!r} 对应的 provider 文件不存在，"
        f"需在 {providers_dir}/ 下提供实现或修正配置"
    )
```

- [ ] **Step 2: Use the helper in `evaluate_workspace()`**

After `default_provider` passes normalization, add:

```python
provider_issue = _selected_provider_issue(default_provider, paths["providers"])
if provider_issue:
    issues.append(provider_issue)
```

- [ ] **Step 3: Make `init()` fail before writing state**

Right after `_write_default_config()`:

```python
config = _read_config()
selected = normalize_provider_name(str(config.get("default_provider", "")))
provider_issue = _selected_provider_issue(selected, providers_dir)
if provider_issue:
    print(f"[dp] 错误：{provider_issue}", file=sys.stderr)
    return False
```

- [ ] **Step 4: Run tests and verify GREEN for doctor**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- 新增 doctor tests PASS
- 既有 doctor / smoke tests 继续 PASS

### Task 3: Strengthen SKILL Prose and Validator Guards

**Files:**
- Modify: `scripts/validate_bundle.py`
- Modify: `scripts/test_helpers.py`
- Modify: `SKILL.md`
- Modify: `evals/smoke-checklist.md`

- [ ] **Step 1: Extend `_build_skill_md()` so tests can target the interaction section**

Update helper shape to support:

```python
def _build_skill_md(preflight: str = "", port: str = "", interaction: str = "", reuse: str = "", other: str = "") -> str:
    ...
    "### 4. 交互与节奏约束\n"
    f"{interaction}\n"
```

- [ ] **Step 2: Harden validator markers**

In `validate_rule_markers()` add:

```python
selected_provider_boundary = (
    "default_provider" in preflight_sec
    and "cdp-port" in preflight_sec
    and ("对应 provider 文件" in preflight_sec or ".dp/providers/" in preflight_sec)
    and ("不存在" in preflight_sec or "缺失" in preflight_sec)
    and ("配置错误" in preflight_sec or "需用户" in preflight_sec or "需客户端" in preflight_sec)
)
```

and for the interaction section:

```python
interaction_sec = _extract_section(skill, "### 4. 交互与节奏约束")
file_helper_boundary = (
    "launch_info" in interaction_sec
    and ("upload_file()" in interaction_sec or "download_file()" in interaction_sec)
    and ("remote" in interaction_sec or "不支持本地文件访问" in interaction_sec)
    and ("直接报错" in interaction_sec or "失败" in interaction_sec)
)
```

- [ ] **Step 3: Update `SKILL.md` and `evals/smoke-checklist.md`**

Make the preflight section explicitly say:

```text
若当前默认 provider 不是 cdp-port，则其对应的 .dp/providers/<name>.py（或等价 snake_case 文件）也必须存在
```

and make the interaction section explicitly say:

```text
若 provider 明确声明 file_access_mode=remote 或不支持本地文件访问，upload_file()/download_file() 直接报错
```

- [ ] **Step 4: Bump bundle version only**

Update `SKILL.md` metadata:

```yaml
bundle-version: "2026-03-31.6"
runtime-lib-version: "2026-03-31.3"
```

- [ ] **Step 5: Re-run tests and validator**

Run:

```bash
python scripts/test_helpers.py
python scripts/validate_bundle.py
```

Expected:
- validator 与 test_helpers 全绿
- 新 prose 规则被回归网覆盖

### Task 4: Final Verification and Review

**Files:**
- Review only

- [ ] **Step 1: Inspect final diff**

Run:

```bash
git diff -- SKILL.md evals/smoke-checklist.md scripts/doctor.py scripts/validate_bundle.py scripts/test_helpers.py docs/superpowers/specs/2026-03-31-provider-readiness-and-file-helper-contract-closure-design.md docs/superpowers/plans/2026-03-31-provider-readiness-and-file-helper-contract-closure.md
```

Expected:
- 只包含本次两个 contract gap 的收口改动

- [ ] **Step 2: Re-run final verification**

Run:

```bash
python scripts/test_helpers.py
python scripts/validate_bundle.py
```

Expected:
- `ALL PASSED`
- `[OK] bundle looks clean`

- [ ] **Step 3: Self-review against the spec**

Check:

- doctor 是否不再把缺失的默认 provider 实现视为 ready
- init 是否在该场景下 fail fast 且不写 state
- top-level SKILL 是否明确写出 remote file helper fail-fast
- validator/tests 是否都对准这两个 reviewed gaps
