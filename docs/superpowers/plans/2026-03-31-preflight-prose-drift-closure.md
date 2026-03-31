# Preflight Prose Drift Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收口 `SKILL.md` / `smoke-checklist` 中剩余的 preflight prose drift，并用 validator/tests 固化这两个 review 发现。

**Architecture:** 先在 `scripts/test_helpers.py` 中补针对性失败用例，锁住“ready 条件过弱”和“非法 provider 被误写成可 repair”两类问题；再增强 `validate_bundle.py` 的 preflight marker 检查，并同步修正文档与版本号。最后同步安装副本 `SKILL.md` 并运行验证命令。

**Tech Stack:** Python 3.10+, `scripts/test_helpers.py`, `scripts/validate_bundle.py`, markdown docs

---

## File Map

- Create: `docs/superpowers/specs/2026-03-31-preflight-prose-drift-closure-design.md`
- Create: `docs/superpowers/plans/2026-03-31-preflight-prose-drift-closure.md`
- Modify: `scripts/test_helpers.py`
- Modify: `scripts/validate_bundle.py`
- Modify: `SKILL.md`
- Modify: `evals/smoke-checklist.md`
- Local-only sync target: `<installed-skill-dir>/SKILL.md`（不属于 source repo）

### Task 1: Lock the Reviewed Drift with Failing Tests

**Files:**
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Add a failing test for missing managed-lib readiness markers**

```python
def test_validate_rule_markers_preflight_requires_managed_lib_markers() -> None:
    content = _build_skill_md(
        preflight=(
            "工作区根通过 cwd 设定，.dp 目录相对该根目录解析；"
            ".dp/.venv/ 存在且工作区 Python 可执行；"
            ".dp/lib/ 存在；"
            ".dp/config.json 含 default_provider；"
            ".dp/providers/cdp-port.py 与 .dp/state.json 存在，"
            "runtime_lib_version / bundle_version 匹配时可跳过 doctor"
        ),
        port="若当前 provider 为 cdp-port，则必须显式传入 browser_profile.port",
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 显式传根路径",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_rule_markers: Preflight 缺少 managed lib / DrissionPage marker 应失败",
            lambda: _vb.validate_rule_markers(Path(d)),
        )
```

- [ ] **Step 2: Add a failing test for missing illegal-provider boundary markers**

```python
def test_validate_rule_markers_preflight_requires_illegal_provider_boundary() -> None:
    content = _build_skill_md(
        preflight=(
            "工作区根通过 cwd 设定，.dp 目录相对该根目录解析；"
            "若 .dp/config.json 缺失、损坏，或 default_provider 为空 / 不合法，"
            "则运行 scripts/doctor.py 修复"
        ),
        port="若当前 provider 为 cdp-port，则必须显式传入 browser_profile.port",
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 显式传根路径",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_rule_markers: 非法 provider 未声明 fail-fast 边界时应失败",
            lambda: _vb.validate_rule_markers(Path(d)),
        )
```

- [ ] **Step 3: Add a passing test for the new equivalent prose**

```python
def test_validate_rule_markers_allows_preflight_prose_with_repair_boundary() -> None:
    content = _build_skill_md(
        preflight=(
            "工作区根通过 cwd 设定，.dp 目录相对该根目录解析；"
            ".dp/.venv/ 存在且工作区 Python 可执行并可导入 DrissionPage；"
            ".dp/lib/connect.py、.dp/lib/output.py、.dp/lib/utils.py、.dp/lib/_dp_compat.py、"
            ".dp/providers/cdp-port.py、.dp/config.json、.dp/state.json 全部就绪，"
            "且 default_provider 合法、runtime_lib_version / bundle_version 匹配时才可跳过 doctor；"
            "default_provider 非空但不合法属于配置错误，doctor 不做猜测式修复，需用户或客户端修正配置"
        ),
        port="若当前 provider 为 cdp-port，则必须显式传入 browser_profile.port",
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 显式传根路径",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        _vb.validate_rule_markers(Path(d))
        check("validate_rule_markers: 新 preflight prose 可通过", True)
```

- [ ] **Step 4: Run the test helper suite and verify RED**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- New `validate_rule_markers` tests fail
- Existing tests continue to provide baseline coverage

### Task 2: Harden Validator for the Reviewed Failure Modes

**Files:**
- Modify: `scripts/validate_bundle.py`
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Extend preflight marker checks for managed-lib readiness**

Update `validate_rule_markers()` so `preflight_sec` must also contain:

```python
managed_readiness_tokens = (
    "DrissionPage",
    ".dp/lib/connect.py",
    ".dp/lib/output.py",
    ".dp/lib/utils.py",
    ".dp/lib/_dp_compat.py",
)
```

and fail with a targeted error if any token is missing.

- [ ] **Step 2: Add semantic guard for illegal provider fail-fast prose**

In `validate_rule_markers()`, require the preflight section to include a boundary like:

```python
has_illegal_provider_boundary = (
    "default_provider" in preflight_sec
    and "不合法" in preflight_sec
    and ("配置错误" in preflight_sec or "非法" in preflight_sec)
    and ("不做猜测式修复" in preflight_sec or "不会自动修复" in preflight_sec)
    and ("需用户" in preflight_sec or "需客户端" in preflight_sec or "需修正配置" in preflight_sec)
)
```

Fail if the boundary is absent.

- [ ] **Step 3: Re-run tests and verify GREEN for validator**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- The new preflight drift tests pass
- Existing `validate_rule_markers` tests remain green

### Task 3: Repair the Public Prose Contract

**Files:**
- Modify: `SKILL.md`
- Modify: `evals/smoke-checklist.md`

- [ ] **Step 1: Tighten `SKILL.md` skip-preflight wording**

Update the Preflight section so it explicitly says:

```markdown
- `.dp/.venv/` 存在，且工作区 Python 可执行并可导入 `DrissionPage`
- `.dp/lib/connect.py`、`.dp/lib/output.py`、`.dp/lib/utils.py`、`.dp/lib/_dp_compat.py` 全部存在
```

Do not leave the looser `“.dp/lib/ 存在”` wording behind.

- [ ] **Step 2: Split recoverable vs illegal `default_provider` states**

Update the “需要运行 preflight 的情况” and “操作” subsections so they distinguish:

```markdown
- `.dp/config.json` 缺失、损坏，或 `default_provider` 缺失 / 非字符串 / 空字符串 / 纯空白：可触发 doctor 自动修复
- `default_provider` 非空但不合法：属于显式配置错误，doctor 不做猜测式修复，需用户或客户端修正 `.dp/config.json`
```

- [ ] **Step 3: Sync the same semantics into `evals/smoke-checklist.md`**

Make the checklist say the same two things:

```markdown
- 跳过 doctor 的 ready 条件必须包含 `DrissionPage` 可导入与四个 managed lib 文件齐全
- `default_provider` 非空但不合法不是普通 repair path，而是配置错误
```

- [ ] **Step 4: Bump `bundle-version` in `SKILL.md`**

Update frontmatter:

```yaml
metadata:
  bundle-version: "2026-03-31.5"
  runtime-lib-version: "2026-03-31.3"
```

Reason: this is a bundle-level docs/scripts contract change, not a runtime-lib change.

### Task 4: Sync Installed Copy and Verify End-to-End

**Files:**
- Local-only sync target: `<installed-skill-dir>/SKILL.md`

- [ ] **Step 1: Sync source `SKILL.md` into the installed copy**

Run:

```bash
cp /path/to/source-bundle/SKILL.md <installed-skill-dir>/SKILL.md
```

- [ ] **Step 2: Refresh workspace state with doctor**

Run:

```bash
python <installed-skill-dir>/scripts/doctor.py
```

Expected:
- exit code `0`
- `.dp/state.json` updates `bundle_version` to `2026-03-31.5`

- [ ] **Step 3: Run bundle validation**

Run:

```bash
python scripts/validate_bundle.py
```

Expected:
- exit code `0`
- no missing preflight marker errors

- [ ] **Step 4: Re-run the helper test suite**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- `ALL PASSED`

- [ ] **Step 5: Review the resulting diff**

Run:

```bash
git diff -- SKILL.md evals/smoke-checklist.md scripts/validate_bundle.py scripts/test_helpers.py docs/superpowers/specs/2026-03-31-preflight-prose-drift-closure-design.md docs/superpowers/plans/2026-03-31-preflight-prose-drift-closure.md
```

Expected:
- Diff only covers the reviewed drift closure and supporting docs/tests
