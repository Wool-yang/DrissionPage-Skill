"""通用操作封装——截图、数据保存、等待、原生交互等高频操作。"""
from __future__ import annotations

import base64
import json
import os
import platform
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote_to_bytes, urlparse

if TYPE_CHECKING:
    from DrissionPage import ChromiumPage
    from DrissionPage._elements.chromium_element import ChromiumElement

_MISSING = object()  # 哨兵：区分"属性不存在"与"属性值为 None"


def _is_wsl() -> bool:
    """判断当前 Python 是否运行在 WSL。"""
    if os.name == "nt":
        return False
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    for probe in ("/proc/version", "/proc/sys/kernel/osrelease"):
        try:
            if "microsoft" in Path(probe).read_text(encoding="utf-8").lower():
                return True
        except OSError:
            continue
    return False


def _browser_os_name(obj) -> str:
    """从当前浏览器 UA 推断浏览器所在 OS。"""
    page = getattr(obj, "owner", obj)
    ua = ""
    try:
        ua = page.run_js("navigator.userAgent", as_expr=True) or ""
    except TypeError:
        try:
            ua = page.run_js("navigator.userAgent") or ""
        except Exception:
            ua = ""
    except Exception:
        ua = ""

    if "Windows NT" in ua:
        return "windows"
    if "Mac OS X" in ua or "Macintosh" in ua:
        return "macos"
    if "Linux" in ua or "X11" in ua:
        return "linux"

    if os.name == "nt":
        return "windows"
    if platform.system() == "Darwin":
        return "macos"
    return "linux"


def _to_windows_browser_path(path: Path) -> str:
    """将本地路径转换为 Windows Chrome 可访问的路径。"""
    posix = path.as_posix()
    mounted = re.match(r"^/mnt/([a-zA-Z])/(.*)$", posix)
    if mounted:
        return f"{mounted.group(1).upper()}:/{mounted.group(2)}"

    distro = os.environ.get("WSL_DISTRO_NAME", "").strip()
    if distro and path.is_absolute():
        win_tail = posix.replace("/", "\\")
        return f"\\\\wsl$\\{distro}{win_tail}"

    if _is_wsl():
        print(
            f"[dp] warning: WSL_DISTRO_NAME not set, cannot build UNC path for {path!r}; "
            "falling back to POSIX (may fail in Windows Chromium)",
            file=sys.stderr,
        )
    return path.as_posix()


def browser_upload_path(file_path: str | Path, obj=None) -> str:
    """
    将上传文件路径规范化为浏览器所在 OS 可直接访问的路径。

    重点覆盖 WSL Python 接管 Windows Chromium 的场景：
    - /mnt/g/foo.txt -> G:/foo.txt
    - /tmp/foo.txt   -> \\\\wsl$\\<distro>\\tmp\\foo.txt
    """
    path = Path(file_path).expanduser().resolve(strict=True)
    if obj is None:
        if os.name == "nt":
            browser_os = "windows"
        elif platform.system() == "Darwin":
            browser_os = "macos"
        else:
            browser_os = "linux"
    else:
        browser_os = _browser_os_name(obj)
    if browser_os == "windows":
        return _to_windows_browser_path(path) if _is_wsl() or os.name == "nt" else str(path)
    return path.as_posix()


def browser_download_path(save_path: str | Path, obj=None) -> str:
    """将下载目录规范化为浏览器所在 OS 可直接写入的路径。"""
    local_dir = Path(save_path).expanduser().resolve()
    local_dir.mkdir(parents=True, exist_ok=True)
    browser_path = browser_upload_path(local_dir, obj)
    if _browser_os_name(obj) == "windows":
        return browser_path.replace("/", "\\")
    return browser_path


def _host_os_name() -> str:
    """返回当前 Python 所在宿主 OS。"""
    if os.name == "nt":
        return "windows"
    if platform.system() == "Darwin":
        return "macos"
    return "linux"


def _prefer_dp_download(obj) -> bool:
    """同 OS 场景优先使用 DrissionPage 自带下载管理。"""
    browser_os = _browser_os_name(obj)
    host_os = _host_os_name()
    if browser_os != host_os:
        return False
    if host_os == "linux" and _is_wsl():
        return False
    return True


def _download_target_name(
    ele: ChromiumElement,
    rename: str | None = None,
    suffix: str | None = None,
) -> str:
    """推导下载文件名。"""
    if rename:
        base = Path(rename).name or "download"
    else:
        base = Path((ele.attr("download") or "")).name
        if not base:
            href = ele.attr("href") or ""
            base = Path(urlparse(href).path).name or "download"

    if suffix is None:
        return base

    stem = Path(base).stem
    return f"{stem}.{suffix}" if suffix else stem


def _save_data_url(data_url: str, path: Path) -> Path:
    """将 data: URL 内容保存到本地文件。"""
    header, sep, payload = data_url.partition(",")
    if not sep:
        raise ValueError("invalid data url")
    data = base64.b64decode(payload) if ";base64" in header else unquote_to_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def screenshot(page: ChromiumPage, path: Path, full_page: bool = True) -> Path:
    """等待页面加载后截图，返回保存路径。
    首次截图若超时（Chrome GPU 合成器冷启动），自动重试一次。
    """
    page.wait.doc_loaded()
    for attempt in range(2):
        try:
            page.get_screenshot(path=str(path.parent), name=path.name, full_page=full_page)
            print(f"[dp] screenshot -> {path}")
            return path
        except Exception as e:
            if attempt == 0 and "timeout" in str(e).lower():
                print("[dp] screenshot 超时（GPU 冷启动），重试中...")
                continue
            raise
    return path  # unreachable


def save_json(data: list | dict, path: Path) -> Path:
    """将数据保存为格式化 JSON，返回保存路径。"""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    count = len(data) if isinstance(data, list) else "dict"
    print(f"[dp] saved {count} items -> {path}")
    return path


def wait_and_find(page: ChromiumPage, selector: str, timeout: int = 10) -> list:
    """等待元素加载后返回列表，超时返回空列表（不抛异常）。"""
    page.wait.eles_loaded(selector, timeout=timeout, raise_err=False)
    return page.eles(selector)


def native_click(ele: ChromiumElement, timeout: int = 10) -> ChromiumElement:
    """
    原生点击：等待可点击 → 滚动到可见 → 等待停止移动 → 等待不被遮挡 → 点击。
    优先使用此函数，避免直接调用 ele.click(by_js=True)。
    """
    ele.wait.clickable(timeout=timeout)
    ele.scroll.to_see()
    ele.wait.stop_moving(timeout=timeout)
    ele.wait.not_covered(timeout=timeout)
    ele.click(by_js=False)
    return ele


def native_input(
    ele: ChromiumElement,
    value: str,
    timeout: int = 10,
    clear_first: bool = True,
) -> ChromiumElement:
    """
    原生输入：滚动到可见 → 等待可点击 → 聚焦 → 清空 → 输入。
    优先使用此函数，避免直接设置 value 属性或派发键盘事件。
    """
    ele.scroll.to_see()
    ele.wait.clickable(timeout=timeout)
    ele.focus()
    if clear_first:
        ele.clear(by_js=False)
    ele.input(value, clear=False, by_js=False)
    return ele


def upload_file(ele: ChromiumElement, file_path: str | Path, timeout: int = 10) -> ChromiumElement:
    """
    上传文件，兼容直接 file input 与“点击后弹 chooser”的两类元素。

    - 直接 input[type=file]：优先走 DOM.setFileInputFiles，并补发 input/change 事件
    - 其他触发 chooser 的元素：走 set.upload_files() + 原生点击
    """
    normalized = browser_upload_path(file_path, ele)
    if ele.tag == "input" and (ele.attr("type") or "").lower() == "file":
        ele.input(normalized)
        ele.run_js(
            "this.dispatchEvent(new Event('input', {bubbles: true}));"
            "this.dispatchEvent(new Event('change', {bubbles: true}));"
        )
        return ele

    ele.owner.set.upload_files(normalized)
    native_click(ele, timeout=timeout)
    ele.owner.wait.upload_paths_inputted()
    return ele


def _set_browser_download_path(ele: ChromiumElement, browser_path: str, new_tab: bool | None = None) -> None:
    """
    直接设置浏览器下载目录，绕过 DrissionPage 在 WSL 下对路径的本地二次 Path() 处理。
    """
    owner = ele.owner
    browser = owner._browser
    browser._download_path = browser_path
    if hasattr(owner, "_download_path"):
        owner._download_path = browser_path
    browser._run_cdp(
        "Browser.setDownloadBehavior",
        downloadPath=browser_path,
        behavior="allow",
        eventsEnabled=True,
    )


def _wait_download_complete(
    local_dir: Path,
    known_names: set[str],
    target_name: str,
    timeout: float,
) -> Path:
    """等待下载文件真正落盘并稳定。"""
    deadline = time.monotonic() + timeout
    temp_suffixes = (".crdownload", ".tmp", ".part")

    while time.monotonic() < deadline:
        if (local_dir / target_name).is_file():
            return local_dir / target_name

        current = sorted(
            [p for p in local_dir.iterdir() if p.name not in known_names],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        completed = [p for p in current if p.is_file() and not p.name.endswith(temp_suffixes)]
        if completed:
            newest = completed[0]
            if newest.name != target_name:
                target = local_dir / target_name
                newest.rename(target)
                return target
            return newest
        time.sleep(0.25)

    raise TimeoutError(f"download timed out: {local_dir}")


def download_file(
    ele: ChromiumElement,
    save_path: str | Path,
    rename: str | None = None,
    suffix: str | None = None,
    new_tab: bool | None = None,
    by_js: bool = False,
    timeout: int | None = None,
):
    """
    下载文件并将保存目录规范化到浏览器所在 OS。

    策略按优先级分三层：
    1. `data:` 直链：直接本地保存，不依赖浏览器下载管理器
    2. 同 OS 场景：优先尝试 DrissionPage 自带 `click.to_download()`
    3. 跨 OS 场景，或 DP 下载失败：fallback 到 raw CDP 下载目录策略

    设计目的：
    - 对同构环境尽量保留 DrissionPage 原生能力
    - 对 WSL 接管 Windows Chromium 这类跨 OS 场景避免路径被本地 `Path()` 改坏
    """
    href = ele.attr("href") or ""
    local_dir = Path(save_path).expanduser().resolve()
    target_name = _download_target_name(ele, rename=rename, suffix=suffix)
    if href.startswith("data:"):
        final_path = _save_data_url(href, local_dir / target_name)
        print(f"[dp] download strategy=data-url target={final_path}")
        return final_path

    known_names = {p.name for p in local_dir.iterdir()}
    timeout = 30 if timeout is None else timeout
    browser_os = _browser_os_name(ele)
    host_os = _host_os_name()
    prefer_dp = _prefer_dp_download(ele)

    print(
        "[dp] download plan:"
        f" host_os={host_os}"
        f" browser_os={browser_os}"
        f" prefer_dp={prefer_dp}"
        f" dir={local_dir}"
        f" name={target_name}"
    )

    if prefer_dp:
        try:
            print("[dp] download strategy=dp-native")
            ele.click.to_download(
                save_path=str(local_dir),
                rename=rename,
                suffix=suffix,
                new_tab=new_tab,
                by_js=by_js,
                timeout=timeout,
            )
            final_path = _wait_download_complete(local_dir, known_names, target_name, timeout)
            print(f"[dp] download strategy=dp-native done={final_path}")
            return final_path
        except Exception as e:
            print(f"[dp] download strategy=dp-native failed={type(e).__name__}: {e}")

    browser_path = browser_download_path(save_path, ele)
    print(f"[dp] download strategy=raw-cdp browser_path={browser_path}")
    _owner = ele.owner
    _browser = _owner._browser
    _orig_browser_path = getattr(_browser, "_download_path", None)
    _orig_owner_path = getattr(_owner, "_download_path", _MISSING)
    try:
        _set_browser_download_path(ele, browser_path, new_tab=new_tab)
        native_click(ele, timeout=max(10, int(timeout)))
        final_path = _wait_download_complete(local_dir, known_names, target_name, timeout)
        print(f"[dp] download strategy=raw-cdp done={final_path}")
    finally:
        # 恢复浏览器原始下载目录，避免持久污染用户会话
        if _orig_browser_path is not None:
            _browser._download_path = _orig_browser_path
            if _orig_owner_path is not _MISSING:
                _owner._download_path = _orig_owner_path
            try:
                _browser._run_cdp(
                    "Browser.setDownloadBehavior",
                    downloadPath=_orig_browser_path,
                    behavior="allow",
                    eventsEnabled=True,
                )
            except Exception:
                pass  # 恢复失败不阻塞主流程
    return final_path


def _rewrite_header_fields(text: str, status: str, today: str) -> str:
    """只在脚本头 docstring 内替换 last_run/status 字段，防止误改正文。"""
    m = re.search(r'(\'\'\'|""")(.*?)\1', text, re.DOTALL)
    if not m:
        return text
    quotes, inner = m.group(1), m.group(2)
    inner = re.sub(r'^(last_run:)[ \t]*\S*', f'\\g<1> {today}', inner, flags=re.MULTILINE)
    inner = re.sub(r'^(status:)[ \t]*\S*', f'\\g<1> {status}', inner, flags=re.MULTILINE)
    return text[:m.start()] + quotes + inner + quotes + text[m.end():]


def mark_script_status(status: str = "ok") -> None:
    """
    回写调用脚本的 last_run 和 status 字段到脚本头 docstring。
    在脚本末尾调用：mark_script_status("ok") 或 mark_script_status("broken")。
    不依赖 git，直接改文件——在无版本控制的 .dp/ 目录下也能持久化状态。
    """
    script = Path(sys.argv[0]).resolve()
    if not script.exists() or script.suffix != ".py":
        return
    try:
        text = script.read_text(encoding="utf-8")
        text = _rewrite_header_fields(text, status, date.today().isoformat())
        script.write_text(text, encoding="utf-8")
    except Exception:
        pass  # 回写失败不影响主流程
