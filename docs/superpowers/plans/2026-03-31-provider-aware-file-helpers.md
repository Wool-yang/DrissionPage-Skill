# Provider-Aware File Helpers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 upload/download helper 从纯多端路径转换模型升级为 provider-aware 的本地文件访问模型，并统一下载主路径，移除对 DrissionPage 下载管理器分支的依赖。

**Architecture:** 在 `templates/utils.py` 中引入 file helper context，允许 `launch_info` 与 provider metadata hints 参与路径决策。upload helper 修复路径命名空间问题；download helper 统一走浏览器下载目录 + 原生点击 + 完成等待的 CDP 主路径，并在支持的 `chrome-cdp + Chrome` 链路上尝试通过 `Fetch` 改写响应头实现任务创建时改名。workflow 和 smoke 模板同步传递 `launch_info`。由于会修改 `templates/utils.py`，必须 bump `SKILL.md` 的 `runtime-lib-version` 与 `bundle-version`，再同步安装副本并重跑 doctor。

**Tech Stack:** Python 3.10+, source bundle templates/docs/tests, smoke runner

**Execution Note:** 当前在用户确认的脏工作区中执行；不回滚既有未提交改动，只做增量修改。

---

## File Map

- Create: `docs/superpowers/specs/2026-03-31-provider-aware-file-helpers-design.md`
- Create: `docs/superpowers/plans/2026-03-31-provider-aware-file-helpers.md`
- Modify: `templates/utils.py`
- Modify: `references/workflows.md`
- Modify: `references/provider-contract.md`
- Modify: `scripts/smoke.py`
- Modify: `scripts/test_helpers.py`
- Modify: `SKILL.md`

### Task 1: Lock Provider-Aware File Context with Failing Tests

**Files:**
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Add failing tests for provider metadata consumption**

Add tests like:

```python
def test_browser_upload_path_prefers_launch_info_browser_os_hint() -> None:
    owner = _FakeOwner("Mozilla/5.0 (X11; Linux x86_64)")
    launch_info = {
        "provider": "chrome-cdp",
        "provider_metadata": {"browser_os": "windows"},
    }
    src = Path(__file__).resolve()
    result = browser_upload_path(src, owner, launch_info=launch_info)
    check("upload path: launch_info browser_os hint 生效", result.startswith("G:/") or result.startswith("\\\\wsl$\\"), repr(result))


def test_browser_upload_path_rejects_remote_file_access_mode() -> None:
    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    launch_info = {
        "provider": "remote-grid",
        "provider_metadata": {"file_access_mode": "remote"},
    }
    with tempfile.NamedTemporaryFile() as f:
        try:
            browser_upload_path(f.name, owner, launch_info=launch_info)
        except RuntimeError as exc:
            check("upload path: remote provider 直接失败", "remote-grid" in str(exc), str(exc))
        else:
            check("upload path: remote provider 直接失败", False, "expected RuntimeError")
```

- [ ] **Step 2: Add failing tests for WSL path namespace handling**

Add tests that lock the namespace behavior:

```python
def test_browser_upload_path_wsl_posix_to_windows_unc_via_launch_context() -> None:
    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    with tempfile.NamedTemporaryFile() as f:
        src = Path(f.name).resolve()
        with _mock.patch.object(_utils_mod, "_host_os_name", return_value="windows"), \
             _mock.patch.object(_utils_mod, "_get_wsl_distro_name", return_value="TestDistro"), \
             _mock.patch.object(_utils_mod, "_path_exists_local", return_value=True):
            result = browser_upload_path(src.as_posix(), owner)
        check("upload path: Windows host 接收 WSL /tmp 路径时转 UNC", result.startswith("\\\\wsl$\\TestDistro\\"), repr(result))
```

- [ ] **Step 3: Add failing tests for launch_info passthrough**

Add tests like:

```python
def test_upload_file_passes_launch_info_to_browser_upload_path() -> None:
    ele = _FakeElement("input", "file", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    launch_info = {"provider": "chrome-cdp", "provider_metadata": {"browser_os": "windows"}}
    captured = {}
    with tempfile.NamedTemporaryFile() as f, _mock.patch.object(
        _utils_mod,
        "browser_upload_path",
        side_effect=lambda path, obj=None, launch_info=None: captured.setdefault("launch_info", launch_info) or str(path),
    ):
        upload_file(ele, f.name, launch_info=launch_info)
    check("upload: launch_info 已透传", captured.get("launch_info") == launch_info, repr(captured))
```

- [ ] **Step 4: Run tests and verify RED**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- New provider-aware upload tests FAIL
- Existing upload/download tests continue to exercise current multi-end behavior

### Task 2: Upgrade `templates/utils.py` to Provider-Aware Context

**Files:**
- Modify: `templates/utils.py`
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Add optional launch context helpers**

Implement internal helpers in `templates/utils.py`:

```python
def _provider_metadata(launch_info) -> dict[str, object]: ...
def _provider_name(launch_info) -> str | None: ...
def _normalize_os_name(raw: str | None) -> str | None: ...
def _declared_file_access_mode(launch_info) -> str | None: ...
def _get_wsl_distro_name() -> str | None: ...
def _path_exists_local(path: str | Path) -> bool: ...
```

- [ ] **Step 2: Make browser OS detection consume provider hints first**

Change `_browser_os_name()` to:

```python
def _browser_os_name(obj, launch_info=None) -> str:
    hinted = _normalize_os_name(_provider_metadata(launch_info).get("browser_os"))
    if hinted:
        return hinted
    ...
```

- [ ] **Step 3: Replace eager `resolve(strict=True)` in upload path handling**

Refactor `browser_upload_path()` so it:

```python
def browser_upload_path(file_path, obj=None, launch_info=None) -> str:
    _ensure_local_file_access_supported("upload", launch_info)
    browser_os = _browser_os_name(obj, launch_info=launch_info)
    raw = str(file_path)
    ...
```

Required behavior:

- Windows browser + `/mnt/<drive>/...` -> `X:/...`
- Windows browser + `/tmp/...` -> `\\wsl$\\<distro>\\tmp\\...`
- Linux/macOS browser retains POSIX path behavior
- provider declares `remote` -> fail fast

- [ ] **Step 4: Upgrade download path handling to use the same context**

Change:

```python
def browser_download_path(save_path, obj=None, launch_info=None) -> str: ...
def download_file(..., launch_info=None): ...
```

and make `download_file()` pass `launch_info` through to `browser_download_path()`.

- [ ] **Step 5: Re-run tests and verify GREEN for helper logic**

Run:

```bash
python scripts/test_helpers.py
```

Expected:
- New provider-aware upload tests PASS
- Existing upload/download regression tests still PASS

### Task 3: Pass Launch Context Through Workflows and Smoke

**Files:**
- Modify: `references/workflows.md`
- Modify: `scripts/smoke.py`
- Modify: `scripts/test_helpers.py`

- [ ] **Step 1: Update canonical workflow examples**

In `references/workflows.md`, change upload/download examples to:

```python
upload_file(page.ele(FILE_INPUT_SEL), FILE_PATH, launch_info=launch_info)
saved = download_file(ele, run, rename=FILENAME, launch_info=launch_info)
```

Also update the form section’s file upload snippet to pass `launch_info`.

- [ ] **Step 2: Update smoke upload/download cases**

In `scripts/smoke.py`, change generated case scripts to pass `launch_info` into helper calls:

```python
upload_file(page.ele("#file-input"), r"{upload_file}", launch_info=launch_info)
mission = download_file(page.ele("#download-btn"), run, rename="smoke-test.txt", launch_info=launch_info)
```

Also change `_lib_loader()` to retain `launch_info` instead of discarding it.

- [ ] **Step 3: Run smoke upload case to verify the original failure is fixed**

Run:

```bash
python scripts/smoke.py --case upload
```

Expected:
- PASS
- `result.png` exists in the upload run-dir

### Task 4: Publish Optional Provider File Access Hints

**Files:**
- Modify: `references/provider-contract.md`
- Modify: `SKILL.md`

- [ ] **Step 1: Extend provider contract doc with optional metadata hints**

Add a new section describing optional `extract_metadata()` hints:

```python
{
    "browser_os": "...",
    "file_access_mode": "local" | "local-cross-namespace" | "remote" | "unknown",
    "path_namespace": "...",
}
```

Clarify that these are recommended hints, not mandatory contract fields.

- [ ] **Step 2: Update SKILL-level upload/download wording**

Keep the existing helper recommendation, but clarify:

- `upload_file()` / `download_file()` handle multi-end paths by default
- when workflow passes `launch_info`, helper may also consume provider hints
- provider 明确声明不支持本地文件访问时，helper 会直接报错

- [ ] **Step 3: Bump bundle and runtime-lib versions**

Because `templates/utils.py` changes, update `SKILL.md` metadata:

```yaml
metadata:
  bundle-version: "2026-03-31.2"
  runtime-lib-version: "2026-03-31.1"
```

### Task 5: Full Verification and Local Sync

**Files:**
- Modify: working tree only as required by earlier tasks

- [ ] **Step 1: Self-review the spec and plan**

Run:

```python
from pathlib import Path

paths = [
    Path("docs/superpowers/specs/2026-03-31-provider-aware-file-helpers-design.md"),
    Path("docs/superpowers/plans/2026-03-31-provider-aware-file-helpers.md"),
]
patterns = ["TO" + "DO", "TB" + "D", "implement" + " later", "fill in" + " details"]
for path in paths:
    text = path.read_text(encoding="utf-8")
    for pattern in patterns:
        if pattern in text:
            raise SystemExit(f"{path}: found placeholder pattern {pattern!r}")
```

Expected:
- no output

- [ ] **Step 2: Run full verification**

Run:

```bash
python scripts/test_helpers.py
python scripts/validate_bundle.py
python scripts/smoke.py --case upload
python scripts/smoke.py --case download
```

Expected:
- tests pass
- validator passes
- upload and download smoke cases both PASS

- [ ] **Step 3: Sync installed skill and refresh outer workspace**

Run:

```bash
python scripts/install.py --target <installed-skill-dir>
python <installed-skill-dir>/scripts/doctor.py
python <installed-skill-dir>/scripts/doctor.py --check
```

Expected:
- installed copy updated
- outer `.dp/lib/utils.py` refreshed
- outer `.dp/state.json` updated to `bundle-version 2026-03-31.2` and `runtime-lib-version 2026-03-31.1`
