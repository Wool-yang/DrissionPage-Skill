# Single-Target Download Runtime Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `dp` 的下载能力收口成可靠的单目标下载内核：新增独立的下载 correlation 子层，修复 WSL 路径闭环，保留 `by_js` 兜底并彻底移除 `new_tab`，同时同步 doctor/validator/docs/workspace contract。

**Architecture:** 先用失败测试锁定三类回归：非目标响应污染、WSL distro 回退断链、`download_file()` 的假参数。然后新增 `templates/download_correlation.py` 承载下载意图、匹配器和受限 Fetch 生命周期，把 `templates/utils.py` 收回到 orchestration 层。最后把新 runtime 资产并入 `doctor.py`、`validate_bundle.py`、`SKILL.md`、checklist/workflows/evals，并 bump 版本、同步安装副本、重跑 doctor 更新外层工作区。

**Tech Stack:** Python 3.10+, source bundle docs/scripts/templates, `scripts/test_helpers.py`, `scripts/validate_bundle.py`

---

## File Map

- Create: `templates/download_correlation.py`
- Modify: `templates/utils.py`
- Modify: `scripts/test_helpers.py`
- Modify: `scripts/doctor.py`
- Modify: `scripts/validate_bundle.py`
- Modify: `SKILL.md`
- Modify: `evals/evals.json`
- Modify: `evals/smoke-checklist.md`
- Modify: `references/workflows.md`
- Modify: `README.md`
- Modify: `README_EN.md`
- Modify: `<installed-skill-dir>/`（通过 `scripts/install.py --target` 同步安装副本，不手工编辑）

### Task 1: Lock the New Runtime Contract with Failing Tests

**Files:**
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Add failing tests for the new managed runtime asset**

在 `scripts/test_helpers.py` 的 doctor / validator 区域新增测试，明确 `.dp/lib/download_correlation.py` 已经成为 managed runtime 资产：

```python
def test_doctor_check_requires_download_correlation_lib() -> None:
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            (dp / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (dp / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (dp / "lib").mkdir(parents=True, exist_ok=True)
            for name in ("connect.py", "output.py", "utils.py", "_dp_compat.py"):
                (dp / "lib" / name).write_text("# ok\n", encoding="utf-8")
            (dp / "providers").mkdir(parents=True, exist_ok=True)
            (dp / "providers" / "cdp-port.py").write_text("# ok\n", encoding="utf-8")
            (dp / "config.json").write_text('{"default_provider":"cdp-port"}', encoding="utf-8")
            (dp / "state.json").write_text(
                _json.dumps({
                    "bundle_version": _doctor._read_bundle_version(),
                    "runtime_lib_version": _doctor._read_runtime_lib_version(),
                }),
                encoding="utf-8",
            )
            with _mock.patch.object(
                _doctor, "resolve_venv_python", return_value=dp / ".venv" / "bin" / "python"
            ), _mock.patch.object(_doctor.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
                issues = _doctor.evaluate_workspace(dp)["issues"]
            check(
                "doctor: 缺少 download_correlation.py 会报错",
                any("download_correlation.py" in item for item in issues),
                repr(issues),
            )
```

再补 validator prose 测试，要求 preflight 章节必须出现 `.dp/lib/download_correlation.py`。

- [ ] **Step 2: Add failing tests for WSL path closure and `new_tab` removal**

在 upload/download helper 测试区域新增：

```python
def test_browser_upload_path_wsl_distro_fallback_reaches_unc_output() -> None:
    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    with tempfile.NamedTemporaryFile() as f, _mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": ""}, clear=False), _mock.patch.object(
        _utils_mod.subprocess,
        "check_output",
        return_value="TestDistro\n",
        create=True,
    ):
        result = browser_upload_path(
            Path(f.name).resolve(),
            owner,
            launch_info={"provider_metadata": {"browser_os": "windows"}},
        )
    check(
        "upload path: wsl.exe 回退结果真正进入最终 UNC 输出",
        result.startswith("\\\\wsl$\\TestDistro\\"),
        repr(result),
    )


def test_browser_upload_path_windows_browser_requires_distro_for_posix_path() -> None:
    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    with tempfile.NamedTemporaryFile() as f, _mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": ""}, clear=False), _mock.patch.object(
        _utils_mod.subprocess,
        "check_output",
        side_effect=RuntimeError("missing wsl.exe"),
        create=True,
    ):
        try:
            browser_upload_path(
                Path(f.name).resolve(),
                owner,
                launch_info={"provider_metadata": {"browser_os": "windows"}},
            )
        except RuntimeError:
            check("upload path: 缺 distro 时直接失败", True)
        else:
            check("upload path: 缺 distro 时直接失败", False, "expected RuntimeError")
```

再新增一个签名测试，要求 `download_file` 不再有 `new_tab` 参数：

```python
def test_download_file_signature_removes_new_tab() -> None:
    params = inspect.signature(download_file).parameters
    check("download_file: 签名中不再出现 new_tab", "new_tab" not in params, repr(list(params)))
```

- [ ] **Step 3: Add failing tests for download correlation safety and `by_js`**

新增受限 Fetch 行为测试，直接锁住 review 中的误伤点：

```python
def test_download_interceptor_skips_non_download_response() -> None:
    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    interceptor = _download_corr.prepare_download_interceptor(
        owner,
        _download_corr.DownloadIntent(
            target_name="report.txt",
            rename_requested=True,
            href="https://example.com/report.txt",
            download_attr="report.txt",
        ),
    )
    interceptor.enable()
    owner.driver_callbacks["Fetch.requestPaused"](
        requestId="req-css",
        request={"url": "https://example.com/app.css"},
        responseStatusCode=200,
        responseHeaders=[{"name": "Content-Type", "value": "text/css"}],
    )
    check(
        "download corr: 非下载响应不注入 Content-Disposition",
        not any(
            method == "Fetch.continueResponse"
            and "Content-Disposition" in _json.dumps(kwargs, ensure_ascii=False)
            for method, kwargs in owner.page_cdp_calls
        ),
        repr(owner.page_cdp_calls),
    )
```

再新增：

- 命中一次后第二个 response 不再改写
- 无 rename/suffix 时不启用 interceptor
- `download_file(by_js=True)` 走 JS click 分支

- [ ] **Step 4: Run tests and verify RED**

Run:

```bash
python scripts/test_helpers.py
```

Expected:

- 新增 download correlation / WSL fallback / `new_tab` 删除相关测试 FAIL
- 失败信息能直接指向缺失模块、错误签名或错误行为

### Task 2: Build the Download Correlation Runtime Layer

**Files:**
- Create: `templates/download_correlation.py`
- Modify: `templates/utils.py`
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Create the failing module interface**

新增 `templates/download_correlation.py`，最小骨架先满足导入和主要类型：

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class DownloadIntent:
    target_name: str
    rename_requested: bool
    href: str | None
    download_attr: str | None


class DownloadMatcher:
    def __init__(self, intent: DownloadIntent):
        self._intent = intent

    def matches_response(self, event: Mapping[str, Any]) -> bool:
        return False


class ScopedDownloadInterceptor:
    def __init__(self, owner, intent: DownloadIntent, matcher: DownloadMatcher):
        self._owner = owner
        self._intent = intent
        self._matcher = matcher
        self._matched = False
        self._enabled = False

    @property
    def matched(self) -> bool:
        return self._matched

    def enable(self) -> None:
        self._enabled = True

    def cleanup(self) -> None:
        self._enabled = False


def prepare_download_interceptor(owner, intent: DownloadIntent):
    return None
```

- [ ] **Step 2: Run focused tests to keep them failing for the right reason**

Run:

```bash
python scripts/test_helpers.py
```

Expected:

- 不再是 `ImportError`
- 仍然 FAIL 在 matcher / interceptor 行为断言

- [ ] **Step 3: Implement minimal matcher and scoped interceptor**

在 `templates/download_correlation.py` 实现：

- `_header_value()` / `_looks_like_download_response()` / `_response_url()` 这类小 helper
- `DownloadMatcher.matches_response()`：
  - 没下载语义 -> `False`
  - 有下载语义但与 `href` 明显不匹配 -> `False`
  - 足够强匹配 -> `True`
- `ScopedDownloadInterceptor.enable()`：
  - `Fetch.enable(patterns=[{"requestStage": "Response"}])`
  - 注册 callback
- callback：
  - 未匹配 -> 原样 `Fetch.continueResponse`
  - 首次匹配 -> 改写 `Content-Disposition`
  - 后续响应 -> 原样透传
- `cleanup()`：
  - `Fetch.disable`
  - callback 清理
  - 幂等

目标代码形状：

```python
def _rewrite_download_response_headers(headers: list[dict[str, Any]], target_name: str) -> list[dict[str, Any]]:
    ...


def _looks_like_download_response(event: Mapping[str, Any]) -> bool:
    ...


def _response_matches_href(event: Mapping[str, Any], href: str | None) -> bool:
    ...
```

- [ ] **Step 4: Integrate the new module into `templates/utils.py`**

在 `templates/utils.py`：

- 删除 `_rewrite_download_response_headers()` / `_prepare_download_request_rename()`
- 改为：

```python
from download_correlation import DownloadIntent, prepare_download_interceptor
```

在 `download_file()` 内部构造：

```python
intent = DownloadIntent(
    target_name=target_name,
    rename_requested=bool(rename or suffix is not None),
    href=href or None,
    download_attr=(ele.attr("download") or None),
)
interceptor = prepare_download_interceptor(_owner, intent)
if interceptor is not None:
    interceptor.enable()
...
finally:
    if interceptor is not None:
        interceptor.cleanup()
```

- [ ] **Step 5: Run tests and verify GREEN for correlation behavior**

Run:

```bash
python scripts/test_helpers.py
```

Expected:

- 新增的 correlation safety 测试 PASS
- 既有 raw download / remote fail-fast 测试继续 PASS

### Task 3: Close Path Semantics and Remove `new_tab`

**Files:**
- Modify: `templates/utils.py`
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Remove `new_tab` from the public helper contract**

把 `templates/utils.py::download_file()` 签名改成：

```python
def download_file(
    ele: ChromiumElement,
    save_path: str | Path,
    rename: str | None = None,
    suffix: str | None = None,
    by_js: bool = False,
    timeout: int | None = None,
    launch_info: Mapping[str, Any] | None = None,
):
```

同步删除：

- `_set_browser_download_path(..., new_tab=...)` 的死参数
- 所有内部透传 `new_tab` 的代码

- [ ] **Step 2: Restore `by_js` as a truthful click-layer escape hatch**

在 `templates/utils.py` 新增：

```python
def _trigger_download_click(ele: ChromiumElement, *, timeout: int, by_js: bool = False) -> None:
    if by_js:
        ele.click(by_js=True)
        return
    native_click(ele, timeout=timeout)
```

并在 `download_file()` 中改成：

```python
_trigger_download_click(ele, timeout=max(10, int(timeout)), by_js=by_js)
```

- [ ] **Step 3: Close the WSL distro fallback chain**

在 `templates/utils.py`：

- 删除 `_to_windows_browser_path()` 对 `WSL_DISTRO_NAME` 的隐式依赖
- 在 `_resolve_windows_browser_path()` 的 POSIX 分支直接使用 `_get_wsl_distro_name()` 结果
- 拿不到 distro 时抛 `RuntimeError`
- 不再 warning 后 fallback 为 POSIX 原路径

目标代码形状：

```python
if kind == "posix-absolute":
    distro = _get_wsl_distro_name()
    if not distro:
        raise RuntimeError(...)
    if host_os == "windows":
        target = _windows_unc_from_posix(raw, distro)
        ...
        return target
    _resolve_local_path(raw)
    return _windows_unc_from_posix(raw, distro)
```

- [ ] **Step 4: Refresh tests to reflect deletion, not compatibility**

在 `scripts/test_helpers.py`：

- 删除/改写仍然假设 `new_tab` 透传的断言
- 保留 `by_js` 的正向测试
- 保留“不重新回到 DP download manager”的约束

- [ ] **Step 5: Run tests and verify GREEN for helper behavior**

Run:

```bash
python scripts/test_helpers.py
```

Expected:

- WSL fallback 测试 PASS
- `download_file: 签名中不再出现 new_tab` PASS
- `download_file(by_js=True)` PASS

### Task 4: Update Workspace Contract, Docs, and Installed Copy

**Files:**
- Modify: `scripts/doctor.py`
- Modify: `scripts/validate_bundle.py`
- Modify: `scripts/test_helpers.py`
- Modify: `SKILL.md`
- Modify: `evals/evals.json`
- Modify: `evals/smoke-checklist.md`
- Modify: `references/workflows.md`
- Modify: `README.md`
- Modify: `README_EN.md`

- [ ] **Step 1: Sync the new managed runtime asset in `doctor.py`**

在 `scripts/doctor.py`：

- `_required_source_assets()` 增加 `templates/download_correlation.py`
- lib 同步列表从 4 个文件扩到 5 个
- `evaluate_workspace()` 的 managed lib completeness 检查增加 `.dp/lib/download_correlation.py`
- `_write_workspace_docs()` 如列举 lib 说明，补新模块名

- [ ] **Step 2: Harden validator for the new asset and preflight token**

在 `scripts/validate_bundle.py`：

- `REQUIRED_FILES` 增加 `templates/download_correlation.py`
- `validate_python()` 编译列表增加新模块
- `validate_rule_markers()` 的 preflight managed lib token 增加 `.dp/lib/download_correlation.py`

- [ ] **Step 3: Update prose to the single-target contract**

更新：

- `SKILL.md`
  - preflight 增加 `.dp/lib/download_correlation.py`
  - 下载描述保持单目标下载 helper 语义
- `references/workflows.md`
  - `download_file()` 描述里写明：
    - 单次调用管理一个目标下载
    - 尽量在任务创建时改名，失败则回退最终落盘 rename
    - `by_js` 仅影响点击触发方式
  - 不出现 `new_tab`
- `evals/evals.json`
  - 下载 expected_output 保持单目标 contract
- `evals/smoke-checklist.md`
  - Preflight 增加新 managed lib
  - 下载行为不再提 `new_tab`
- `README.md` / `README_EN.md`
  - `templates/` 结构加 `download_correlation.py`

- [ ] **Step 4: Bump versions and sync installed copy**

由于会修改 `templates/utils.py`，按仓库约束必须 bump：

在 `SKILL.md`：

```yaml
bundle-version: "2026-04-01.3"
runtime-lib-version: "2026-04-01.3"
```

然后同步安装副本：

```bash
python /mnt/g/program/dpskill/dp-skill-source/scripts/install.py --target <installed-skill-dir>
```

- [ ] **Step 5: Re-run tests and validator**

Run:

```bash
python scripts/test_helpers.py
python scripts/validate_bundle.py
```

Expected:

- 全绿
- validator 不再遗漏新 runtime 资产

### Task 5: Refresh Outer Workspace and Verify End-to-End State

**Files:**
- Runtime output only: `/mnt/g/program/dpskill/.dp/lib/*`, `/mnt/g/program/dpskill/.dp/state.json`

- [ ] **Step 1: Re-run doctor from the installed skill against the outer workspace**

Run from outer workspace root:

```bash
cd /mnt/g/program/dpskill
python <installed-skill-dir>/scripts/doctor.py
```

Expected:

- `.dp/lib/download_correlation.py` 已同步
- `.dp/lib/utils.py` 已刷新
- `.dp/state.json` 的 `bundle_version` / `runtime_lib_version` 更新为 `2026-04-01.3`

- [ ] **Step 2: Spot-check the refreshed workspace**

Run:

```bash
cd /mnt/g/program/dpskill
python <installed-skill-dir>/scripts/doctor.py --check
```

Expected:

- exit 0
- managed lib 列表包含 `download_correlation.py`

- [ ] **Step 3: Final verification**

Run:

```bash
python /mnt/g/program/dpskill/dp-skill-source/scripts/test_helpers.py
python /mnt/g/program/dpskill/dp-skill-source/scripts/validate_bundle.py
cd /mnt/g/program/dpskill && python <installed-skill-dir>/scripts/doctor.py --check
```

Expected:

- tests PASS
- bundle validator PASS
- outer workspace doctor PASS

- [ ] **Step 4: Review final diff before completion**

Run:

```bash
git -C /mnt/g/program/dpskill/dp-skill-source diff -- \
  templates/download_correlation.py \
  templates/utils.py \
  scripts/test_helpers.py \
  scripts/doctor.py \
  scripts/validate_bundle.py \
  SKILL.md \
  evals/evals.json \
  evals/smoke-checklist.md \
  references/workflows.md \
  README.md \
  README_EN.md \
  docs/superpowers/specs/2026-04-01-download-correlation-runtime-design.md \
  docs/superpowers/specs/2026-04-01-file-helper-path-and-compat-closure-design.md \
  docs/superpowers/specs/2026-04-01-download-contract-and-regression-closure-design.md \
  docs/superpowers/plans/2026-04-01-single-target-download-runtime-closure.md
```

Expected:

- diff 只包含本轮单目标下载内核 closure
- 不包含 batch contract
- `new_tab` 已从 `download_file()` 公开签名、tests 和 canonical docs 中移除
