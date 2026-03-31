# Connect API Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除 `templates/connect.py` 中的 legacy `connect_*` 包装器，统一公开连接入口到 provider-first 正式 API，并把文档、校验与测试一起收口。

**Architecture:** `connect.py` 只保留三层公开能力：provider discovery / resolution、provider-first high-level、explicit address attachment。workflow、mode-selection、smoke checklist 和测试都围绕 `start_profile_and_connect_*()` 与 `*_by_address()` 组织，不再保留 legacy facade。由于会修改 `templates/connect.py`，必须同步 bump `SKILL.md` 的 `runtime-lib-version` 与 `bundle-version`，再同步安装副本并重跑 `doctor.py`。

**Tech Stack:** Python 3.10+, DrissionPage, source bundle docs/tests, bundle validation script

**Execution Note:** 当前仓库已存在未提交的 in-progress 变更；若执行时仍在当前工作区而非隔离 worktree，以下 `Commit` 步骤一律视为检查点，不实际提交。安装副本 `<installed-skill-dir>/SKILL.md` 不是内层仓库受版本控制的文件，只做同步，不纳入内层 git commit。

---

### Task 1: 用测试锁定新的公开 API 表面

**Files:**
- Modify: `scripts/test_helpers.py`
- Test: `scripts/test_helpers.py`

- [ ] **Step 1: 写失败中的 API surface 测试**

在 [`scripts/test_helpers.py`](/mnt/g/Program/DPSkill/dp-skill-source/scripts/test_helpers.py) 中，用下面两组测试替换 legacy wrapper 相关测试：

```python
def test_start_profile_and_connect_browser_fresh_tab_binds_tab_id() -> None:
    connect_mod, RecordingChromiumPage, _ = _load_connect_module()
    RecordingChromiumPage._instances.clear()
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        provider_dir = root / ".dp" / "providers"
        provider_dir.mkdir(parents=True, exist_ok=True)
        (provider_dir / "stub-provider.py").write_text(
            "def start_profile(profile=None, *, base_url=None, timeout=60, extra_params=None):\n"
            "    return {'debug_address': '127.0.0.1:9222'}\n"
            "\n"
            "def extract_debug_address(start_result):\n"
            "    return start_result['debug_address']\n",
            encoding="utf-8",
        )
        os.chdir(root)
        try:
            launch_info, page = connect_mod.start_profile_and_connect_browser(
                "stub-provider",
                {},
                fresh_tab=True,
            )
        finally:
            os.chdir(old_cwd)

    check("fresh_tab: launch_info 返回 provider", launch_info.get("provider") == "stub-provider", repr(launch_info))
    if RecordingChromiumPage._instances:
        recorded = RecordingChromiumPage._instances[-1]
        check("fresh_tab: ChromiumPage 构造时传入了 tab_id", recorded.tab_id is not None, repr(recorded.tab_id))
        check("fresh_tab: 返回的 page tab_id 与构造时一致", page.tab_id == recorded.tab_id, f"{page.tab_id!r} != {recorded.tab_id!r}")
    else:
        check("fresh_tab: ChromiumPage 被构造", False, "未记录到任何 ChromiumPage 实例")


def test_removed_legacy_connect_wrappers_are_absent() -> None:
    connect_mod, _, _ = _load_connect_module()
    check("removed api: connect_browser 不存在", not hasattr(connect_mod, "connect_browser"), dir(connect_mod))
    check("removed api: connect_browser_fresh_tab 不存在", not hasattr(connect_mod, "connect_browser_fresh_tab"), dir(connect_mod))
    check("removed api: connect_web_page 不存在", not hasattr(connect_mod, "connect_web_page"), dir(connect_mod))
```

- [ ] **Step 2: 运行定向测试，确认它们先失败**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- 现有 `connect_browser*` 仍存在，`removed api` 检查失败
- 旧 `fresh_tab` 测试仍引用 `connect_browser_fresh_tab()`，需要改成正式入口

- [ ] **Step 3: 删除旧的 legacy wrapper 单测**

从 [`scripts/test_helpers.py`](/mnt/g/Program/DPSkill/dp-skill-source/scripts/test_helpers.py) 中删除以下测试：

```python
test_fresh_tab_tab_id_binding()
test_connect_browser_requires_explicit_port()
test_connect_web_page_requires_explicit_port()
test_connect_browser_uses_workspace_default_provider()
```

并把保留的 provider-first 覆盖点留在：

```python
test_start_profile_and_connect_browser_fresh_tab_binds_tab_id()
test_workspace_provider_start_profile_and_connect()
```

- [ ] **Step 4: 再跑测试，确认失败点只剩生产代码未改**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- `removed api` 相关失败
- 其它 provider loader / launch info 测试继续通过

- [ ] **Step 5: Checkpoint（仅在隔离 worktree 中执行 commit）**

```bash
git add scripts/test_helpers.py
git commit -m "test(dp): lock connect api surface"
```

### Task 2: 删除 legacy wrapper，收口 `connect.py`

**Files:**
- Modify: `templates/connect.py`
- Test: `scripts/test_helpers.py`

- [ ] **Step 1: 实现最小代码改动**

在 [`templates/connect.py`](/mnt/g/Program/DPSkill/dp-skill-source/templates/connect.py) 中删除以下函数定义：

```python
def connect_browser(...): ...
def connect_browser_fresh_tab(...): ...
def connect_web_page(...): ...
```

保留并继续支持：

```python
def get_default_browser_provider(...): ...
def build_default_browser_profile(...): ...
def connect_browser_by_address(...): ...
def connect_browser_by_address_fresh_tab(...): ...
def connect_web_page_by_address(...): ...
def start_profile_and_connect_browser(...): ...
def start_profile_and_connect_web_page(...): ...
```

不要改动 provider loader / launch info 的行为；这一步只做 API surface 收口。

- [ ] **Step 2: 运行测试，确认新 surface 生效**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- `removed api` 检查通过
- `start_profile_and_connect_browser(..., fresh_tab=True)` 相关测试通过

- [ ] **Step 3: 做最小清理**

清理 [`templates/connect.py`](/mnt/g/Program/DPSkill/dp-skill-source/templates/connect.py) 中任何仅服务 removed API 的注释、打印或辅助函数引用，确保模块导出的公开层次只剩 spec 定义的三层。

- [ ] **Step 4: 再跑测试保持全绿**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- `ALL PASSED`

- [ ] **Step 5: Checkpoint（仅在隔离 worktree 中执行 commit）**

```bash
git add templates/connect.py scripts/test_helpers.py
git commit -m "refactor(dp): remove legacy connect wrappers"
```

### Task 3: 把文档和校验一起收口

**Files:**
- Modify: `SKILL.md`
- Modify: `references/workflows.md`
- Modify: `references/mode-selection.md`
- Modify: `evals/smoke-checklist.md`
- Modify: `scripts/validate_bundle.py`
- Modify: `scripts/test_helpers.py`
- Test: `scripts/test_helpers.py`
- Test: `scripts/validate_bundle.py`

- [ ] **Step 1: 写失败中的文档 contract 测试**

在 [`scripts/test_helpers.py`](/mnt/g/Program/DPSkill/dp-skill-source/scripts/test_helpers.py) 里新增一组针对 removed API 文档引用的失败测试：

```python
def test_validate_removed_connect_wrappers_not_referenced_in_docs() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _create_required_bundle_tree(root)
        (root / "references" / "workflows.md").write_text("connect_web_page()", encoding="utf-8")
        _expect_fail(
            "validate: canonical docs 不应再引用 removed connect wrappers",
            lambda: _vb.validate_removed_connect_wrappers(root),
        )
```

同时在 [`scripts/validate_bundle.py`](/mnt/g/Program/DPSkill/dp-skill-source/scripts/validate_bundle.py) 规划一个新校验函数：

```python
def validate_removed_connect_wrappers(root: Path) -> None:
    ...
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- 因为 `validate_removed_connect_wrappers()` 还不存在或未接入主流程而失败

- [ ] **Step 3: 实现 validator 并更新 canonical docs**

在 [`scripts/validate_bundle.py`](/mnt/g/Program/DPSkill/dp-skill-source/scripts/validate_bundle.py) 中新增：

```python
REMOVED_CONNECT_WRAPPERS = (
    "connect_browser(",
    "connect_browser_fresh_tab(",
    "connect_web_page(",
)


def validate_removed_connect_wrappers(root: Path) -> None:
    for rel in (
        "SKILL.md",
        "references/workflows.md",
        "references/mode-selection.md",
        "evals/smoke-checklist.md",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        for marker in REMOVED_CONNECT_WRAPPERS:
            if marker in text:
                fail(f"{rel} 不应再引用已移除的 legacy connect API：{marker}")
```

并把它接入 `main()` 的校验流程。

同时更新文档：

- [`SKILL.md`](/mnt/g/Program/DPSkill/dp-skill-source/SKILL.md)
  - 脚本规范只保留 provider-first 正式入口表述
- [`references/workflows.md`](/mnt/g/Program/DPSkill/dp-skill-source/references/workflows.md)
  - 删掉“`connect_browser()` 不能切换模式；需要 session 模式时必须用 `connect_web_page()`”这一句
  - 改成“浏览器类任务统一走 `start_profile_and_connect_*()`；WebPage 场景使用 `start_profile_and_connect_web_page()`”
- [`references/mode-selection.md`](/mnt/g/Program/DPSkill/dp-skill-source/references/mode-selection.md)
  - 保持 provider-first 示例，不新增 removed API 引用
- [`evals/smoke-checklist.md`](/mnt/g/Program/DPSkill/dp-skill-source/evals/smoke-checklist.md)
  - 把 fresh-tab 手工验收从 `connect_browser_fresh_tab()` 改成

```text
start_profile_and_connect_browser(provider, browser_profile, fresh_tab=True)
```

- [ ] **Step 4: 运行 bundle 校验和测试**

Run:

```bash
python scripts/validate_bundle.py .
python scripts/test_helpers.py
```

Expected:
- `validate_bundle.py` 输出 `[OK] bundle looks clean`
- `test_helpers.py` 输出 `ALL PASSED`

- [ ] **Step 5: Checkpoint（仅在隔离 worktree 中执行 commit）**

```bash
git add SKILL.md references/workflows.md references/mode-selection.md evals/smoke-checklist.md scripts/validate_bundle.py scripts/test_helpers.py
git commit -m "docs(dp): consolidate connect api contract"
```

### Task 4: bump 版本、同步安装副本并刷新工作区 runtime

**Files:**
- Modify: `SKILL.md`
- Modify: `<installed-skill-dir>/SKILL.md`
- Test: `<installed-skill-dir>/scripts/doctor.py`

- [ ] **Step 1: bump `SKILL.md` frontmatter**

因为会修改 [`templates/connect.py`](/mnt/g/Program/DPSkill/dp-skill-source/templates/connect.py)，必须更新 [`SKILL.md`](/mnt/g/Program/DPSkill/dp-skill-source/SKILL.md)：

```yaml
metadata:
  bundle-version: "2026-03-30.8"
  runtime-lib-version: "2026-03-30.5"
```

如果执行时当天已有更高序号，按当天下一次递增。

- [ ] **Step 2: 同步安装副本的 `SKILL.md`**

把内层仓库的 [`SKILL.md`](/mnt/g/Program/DPSkill/dp-skill-source/SKILL.md) 同步到：

```text
<installed-skill-dir>/SKILL.md
```

- [ ] **Step 3: 重跑安装副本 doctor**

从外层工作区运行：

```bash
python <installed-skill-dir>/scripts/doctor.py
```

Expected:
- `.dp/state.json` 被刷新到新 `bundle-version` / `runtime-lib-version`
- `.dp/lib/connect.py` 被新模板覆盖

- [ ] **Step 4: 校验安装副本已与源码版本一致**

Run:

```bash
python <installed-skill-dir>/scripts/doctor.py --check
```

Expected:
- `[dp] ✓ 环境正常`

- [ ] **Step 5: Checkpoint（仅提交内层仓库中的 `SKILL.md`）**

```bash
git add SKILL.md
git commit -m "chore(dp): bump runtime bundle versions"
```

### Task 5: 端到端验证与收尾

**Files:**
- Verify: `templates/connect.py`
- Verify: `SKILL.md`
- Verify: `references/workflows.md`
- Verify: `references/mode-selection.md`
- Verify: `evals/smoke-checklist.md`

- [ ] **Step 1: 运行完整源码验证**

Run:

```bash
python scripts/validate_bundle.py .
python scripts/test_helpers.py
```

Expected:
- `validate_bundle.py` exit code 0
- `test_helpers.py` 输出 `ALL PASSED`

- [ ] **Step 2: 做源码与安装副本的 diff spot check**

Run:

```bash
git diff -- templates/connect.py SKILL.md references/workflows.md references/mode-selection.md evals/smoke-checklist.md scripts/validate_bundle.py scripts/test_helpers.py docs/superpowers/specs/2026-03-30-connect-api-consolidation-design.md docs/superpowers/plans/2026-03-30-connect-api-consolidation.md
```

Expected:
- 改动只围绕 connect API 收口、版本 bump、相关文档和测试

- [ ] **Step 3: 检查设计 spec 覆盖**

人工核对：

- removed API 已从 `templates/connect.py` 删除
- provider-first 正式入口仍完整
- `fresh tab` 文档/验收已切换到 `fresh_tab=True`
- validator 能阻止 canonical docs 再引用 removed API
- AGENTS 要求的版本 bump 与安装副本同步已完成

- [ ] **Step 4: Checkpoint（仅在隔离 worktree 中执行 commit）**

```bash
git add templates/connect.py SKILL.md references/workflows.md references/mode-selection.md evals/smoke-checklist.md scripts/validate_bundle.py scripts/test_helpers.py docs/superpowers/specs/2026-03-30-connect-api-consolidation-design.md docs/superpowers/plans/2026-03-30-connect-api-consolidation.md
git commit -m "feat(dp): consolidate connect api surface"
```
