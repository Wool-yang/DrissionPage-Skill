# Provider Contract Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收口内层开源仓库的 provider contract，使 runtime 只依赖工作区 `.dp/providers/`，把普通 CDP 端口接入收编为 `cdp-port` provider，并让公开工作流返回值改成规范化 launch info。

**Architecture:** 以 `templates/connect.py` 为唯一 runtime 入口，删除 env 注入，统一 provider 命名与发现逻辑，并把普通远程调试端口直连改造成 runtime-managed workspace provider `cdp-port`。公开文档与模板同步切到 provider-first 模型，raw `start_result` 只保留在低层 API 内部。

**Tech Stack:** Python 3.10+, DrissionPage 4.1.1.x, source bundle docs/tests (`scripts/test_helpers.py`)

---

## File Map

- Modify: `templates/connect.py`
- Modify: `scripts/doctor.py`
- Modify: `scripts/test_helpers.py`
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README_EN.md`
- Modify: `references/workflows.md`
- Modify: `references/mode-selection.md`
- Modify: `evals/smoke-checklist.md`
- Modify: `scripts/validate_bundle.py`
- Create: `references/provider-contract.md`
- Create: `templates/providers/cdp-port.py`

### Task 1: Close Loader Sources and Naming Contract

**Files:**
- Modify: `templates/connect.py`
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Write the failing tests for workspace-only loading and name normalization**

Add tests that cover:

```python
def test_browser_provider_loader_accepts_snake_case_filename_via_kebab_name() -> None:
    providers = connect_mod.list_browser_providers()
    assert "anti-detect" in providers
    module = connect_mod.load_browser_provider("anti-detect")
    assert callable(module.start_profile)


def test_browser_provider_loader_rejects_normalized_name_conflict() -> None:
    try:
        connect_mod.list_browser_providers()
    except ValueError as exc:
        assert "anti-detect" in str(exc)
    else:
        raise AssertionError("expected ValueError for normalized name conflict")
```

- [ ] **Step 2: Run tests to verify they fail on current implementation**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- FAIL in the new snake_case compatibility and conflict tests
- Existing provider tests may still pass

- [ ] **Step 3: Implement workspace-only provider discovery and conflict detection**

Update `templates/connect.py` so that:

```python
def _provider_file_names(name: str) -> tuple[str, str]:
    normalized = _normalize_provider_name(name)
    return f"{normalized}.py", f"{normalized.replace('-', '_')}.py"


def _discover_workspace_provider_files() -> dict[str, Path]:
    ...
    # map public kebab-case name -> actual file path
    # raise ValueError when kebab/snake files normalize to the same public name


def _provider_file_candidates(name: str) -> list[Path]:
    ...
    # only return workspace file candidates, no env injection
```

Also remove:

```python
_PROVIDER_FILE_ENV_PREFIX = ...
_PROVIDER_MODULE_ENV_PREFIX = ...
```

and all `DP_PROVIDER_FILE*` / `DP_PROVIDER_MODULE*` lookup branches.

- [ ] **Step 4: Run tests to verify loader and naming changes pass**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- PASS for provider discovery / snake_case compatibility / conflict detection
- No references to env injection remain in failures

- [ ] **Step 5: Review the loader diff without committing in the current dirty workspace**

Run:

```bash
git diff -- templates/connect.py scripts/test_helpers.py
```

Expected:
- Diff only reflects loader source closure and naming contract changes
- No accidental doc or bundle version edits yet

### Task 2: Switch Public Helpers to Opaque Result + Launch Info

**Files:**
- Modify: `templates/connect.py`
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Write the failing tests for opaque start result and normalized launch info**

Replace the current raw-result assertions with tests like:

```python
def test_workspace_provider_start_profile_returns_launch_info() -> None:
    launch_info, page = connect_mod.start_profile_and_connect_browser(
        "stub-provider",
        {"profile_id": 7},
        base_url="http://provider.local",
        timeout=12,
        extra_params={"region": "eu"},
    )
    assert launch_info["provider"] == "stub-provider"
    assert launch_info["provider_url"] == "http://provider.local"
    assert launch_info["browser_profile"]["profile_id"] == 7
    assert launch_info["debug_address"] == "127.0.0.1:50326"
    assert launch_info["provider_metadata"] == {"region": "eu"}


def test_provider_start_profile_allows_non_dict_result() -> None:
    result = connect_mod.start_browser_profile("tuple-provider", {"profile_id": 9})
    assert isinstance(result, tuple)
```

- [ ] **Step 2: Run tests to verify they fail against the current helper return shape**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- FAIL because `start_profile_and_connect_browser()` still returns raw `start_result`
- FAIL because `start_browser_profile()` still enforces `dict`

- [ ] **Step 3: Implement opaque result handling and launch info builder**

Add logic similar to:

```python
def get_provider_metadata(provider: str, start_result: Any) -> dict[str, Any] | None:
    module = load_browser_provider(provider)
    extractor = getattr(module, "extract_metadata", None)
    if extractor is None:
        return None
    metadata = extractor(start_result)
    if metadata is None:
        return None
    if not isinstance(metadata, Mapping):
        raise TypeError(...)
    return dict(metadata)


def build_launch_info(
    provider: str,
    profile: Mapping[str, Any] | None,
    *,
    base_url: str | None,
    start_result: Any,
) -> dict[str, Any]:
    return {
        "provider": _normalize_provider_name(provider),
        "provider_url": base_url,
        "browser_profile": dict(profile or {}),
        "debug_address": get_debug_address(provider, start_result),
        "provider_metadata": get_provider_metadata(provider, start_result),
    }
```

Then change:

```python
def start_browser_profile(...) -> Any:
    ...


def start_profile_and_connect_browser(...) -> tuple[dict[str, Any], ChromiumPage]:
    start_result = start_browser_profile(...)
    launch_info = build_launch_info(...)
    ...
    return launch_info, page
```

and update all `*_from_start_result` helpers to accept `Any`.

- [ ] **Step 4: Run tests to verify the public helper contract is green**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- PASS for launch info assertions
- PASS for non-dict provider result support
- PASS for existing browser connection behavior (`existing_only(True)`)

- [ ] **Step 5: Review the helper diff without committing in the current dirty workspace**

Run:

```bash
git diff -- templates/connect.py scripts/test_helpers.py
```

Expected:
- Diff shows opaque result support and normalized launch info changes
- Raw `start_result` is no longer the workflow-facing public shape

### Task 3: Publish the New Provider Contract

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README_EN.md`
- Modify: `references/workflows.md`
- Modify: `references/mode-selection.md`
- Modify: `evals/smoke-checklist.md`
- Modify: `scripts/validate_bundle.py`
- Create: `references/provider-contract.md`

- [ ] **Step 1: Write the failing contract/documentation checks mentally against current docs**

Current docs still contain these now-invalid statements:

```text
客户端可通过 DP_PROVIDER_FILE[_<NAME>] 或 DP_PROVIDER_MODULE[_<NAME>] 注入 provider 实现
start_result, page = start_profile_and_connect_browser(...)
```

The replacement text must describe:

```text
唯一正式 provider 路径：.dp/providers/<name>.py
高层 workflow 使用 launch_info, page = ...
provider 可以是本地 API provider 或本地 launcher provider
通用 workflow 模板可继承工作区默认 provider
客户端/用户可以修改 .dp/config.json 的 default_provider
```

- [ ] **Step 2: Update public docs to match the closed contract**

Apply these doc-level changes:

```markdown
- 删除所有 env 注入描述
- 新增 references/provider-contract.md
- 在 workflows 示例中改成 launch_info, page = start_profile_and_connect_browser(...)
- 明确普通 CDP 端口接管由 cdp-port provider 承担，不再作为并列默认模式
- 明确 provider raw response 不得直接落盘
- frontmatter description 只保留“何时使用”，不混入 provider 解析流程
- 明确通用 workflow 模板继承工作区默认 provider，同时告诉客户端/用户可修改 default_provider
- 更新 SKILL.md 的 preflight 条件，使其显式覆盖 .dp/config.json 与 .dp/providers/cdp-port.py，并与 doctor.check() 一致
- 更新 smoke-checklist，不再把 9222 写成隐藏默认端口
- 更新 validate_bundle.py，把 references/provider-contract.md 与 templates/providers/cdp-port.py 纳入必需 bundle 资产
```

`references/provider-contract.md` should include two minimal templates:

```python
# API provider template
def start_profile(...): ...
def extract_debug_address(start_result): ...

# launcher provider template
def start_profile(...): ...
def extract_debug_address(start_result): ...
def extract_metadata(start_result): ...
```

- [ ] **Step 3: Bump bundle versions required by template and runtime changes**

Edit the `SKILL.md` frontmatter:

```yaml
metadata:
  bundle-version: "2026-03-30.7"
  runtime-lib-version: "2026-03-30.4"
```

If only docs / references / scripts changed after the runtime landed, bump `bundle-version` only and keep `runtime-lib-version` unchanged.

- [ ] **Step 4: Run bundle validation**

Run:

```bash
python scripts/validate_bundle.py
```

Expected:
- PASS
- No missing required bundle files
- Frontmatter still contains both version fields
- smoke / SKILL 文案不再宣称隐藏默认 9222

- [ ] **Step 5: Review the documentation diff without committing in the current dirty workspace**

Run:

```bash
git diff -- SKILL.md README.md README_EN.md references/workflows.md references/mode-selection.md references/provider-contract.md evals/smoke-checklist.md scripts/validate_bundle.py
```

Expected:
- All env injection wording is gone
- Workflow examples now use launch info
- Provider contract docs describe both API and launcher providers
- Preflight wording and smoke acceptance wording match the provider-first contract

### Task 4: Introduce Runtime-Managed `cdp-port` Provider and Remove Default Port Scanning

**Files:**
- Create: `templates/providers/cdp-port.py`
- Modify: `scripts/doctor.py`
- Modify: `templates/connect.py`
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Write the failing tests for `cdp-port` sync and explicit-port-only fallback**

Add tests that prove:

```python
def test_doctor_init_syncs_cdp_port_provider() -> None:
    assert (patched_dp / "providers" / "cdp-port.py").exists()


def test_connect_browser_requires_explicit_port() -> None:
    with pytest.raises(ValueError):
        connect_mod.connect_browser()
```

- [ ] **Step 2: Run tests to verify they fail on current runtime**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- FAIL because `doctor.py` does not sync `.dp/providers/cdp-port.py`
- FAIL because `connect_browser()` / `connect_web_page()` still scan default ports

- [ ] **Step 3: Implement `cdp-port` as a runtime-managed workspace provider**

Create `templates/providers/cdp-port.py` with behavior equivalent to:

```python
def start_profile(profile=None, *, base_url=None, timeout=60, extra_params=None):
    port = dict(profile or {}).get("port")
    if port in (None, ""):
        raise ValueError("cdp-port provider 需要显式 port。")
    return {"debug_address": f"127.0.0.1:{port}", "port": str(port)}


def extract_debug_address(start_result):
    return start_result["debug_address"]
```

Then update `doctor.py` so that:

```python
.dp/providers/__init__.py
.dp/providers/cdp-port.py
```

are created or refreshed during workspace init/upgrade.

If the source bundle is missing `templates/providers/cdp-port.py`, `doctor.py` should fail instead of silently reporting a healthy workspace.

- [ ] **Step 4: Convert compatibility wrappers to provider-first behavior**

Update `templates/connect.py` so that:

```python
def connect_browser(port: str | None = None) -> ChromiumPage:
    if not port:
        raise ValueError("未提供测试端口。当前默认 provider 为 cdp-port，必须显式传入 port。")
    _, page = start_profile_and_connect_browser("cdp-port", {"port": port})
    return page
```

Apply the same rule to:

```python
connect_browser_fresh_tab()
connect_web_page()
```

and remove default port scanning from the public path.

- [ ] **Step 5: Run tests to verify the provider-first fallback is green**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- PASS for `cdp-port` sync
- PASS for explicit-port-only fallback behavior
- No public helper still relies on default port scanning

### Task 5: Refresh Installed Skill and Verify Workspace Runtime

**Files:**
- Modify: `<installed-skill-dir>/SKILL.md` (generated by install step)
- Modify: `.dp/lib/connect.py` (generated by doctor step)
- Modify: `.dp/providers/cdp-port.py` (generated by doctor step)

- [ ] **Step 1: Sync the updated inner bundle into the installed skill copy**

Run:

```bash
python scripts/install.py --target <installed-skill-dir>
```

Expected:
- Install succeeds
- Installed skill copy preserves local custom files outside upstream manifest

- [ ] **Step 2: Re-run doctor to refresh `.dp/lib/*` and workspace state**

Run from the workspace root:

```bash
cd <workspace-root>
python <installed-skill-dir>/scripts/doctor.py
```

Expected:
- `.dp/lib/connect.py` refreshed from updated template
- `.dp/providers/cdp-port.py` refreshed from updated template
- `.dp/config.json` contains a non-empty `default_provider` while preserving user overrides
- `.dp/state.json` reflects the bumped versions

- [ ] **Step 3: Run the full helper test suite again after installation refresh**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- PASS
- No regressions in install/doctor/helper tests

- [ ] **Step 4: Review final source-of-truth status and leave code uncommitted for user review**

```bash
git status --short
```

Expected:
- Only source-of-truth repo files remain modified for the public change
- Installed skill copy and `.dp/lib/*` changes stay outside the inner repo commit set
