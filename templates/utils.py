"""通用操作封装——截图、数据保存、等待、原生交互等高频操作。"""
from __future__ import annotations

import base64
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping
from urllib.parse import unquote_to_bytes, urlparse

from _dp_compat import (
    get_browser_from_page,
    get_download_path,
    get_download_path_sentinel,
    get_owner_or_self,
    get_user_agent,
    is_download_path_missing,
    run_browser_cdp,
    set_download_path,
)
from download_correlation import DownloadIntent, prepare_download_interceptor

if TYPE_CHECKING:
    from DrissionPage import ChromiumPage
    from DrissionPage._elements.chromium_element import ChromiumElement


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


def _normalize_os_name(raw: str | None) -> str | None:
    """把 provider/browser OS 名称规范化到 windows/linux/macos。"""
    key = (raw or "").strip().lower()
    if not key:
        return None
    aliases = {
        "windows": "windows",
        "win": "windows",
        "win32": "windows",
        "linux": "linux",
        "mac": "macos",
        "macos": "macos",
        "darwin": "macos",
        "osx": "macos",
    }
    return aliases.get(key)


def _provider_metadata(launch_info: Mapping[str, Any] | None) -> dict[str, Any]:
    """返回 launch_info 中可选的 provider_metadata。"""
    if not isinstance(launch_info, Mapping):
        return {}
    metadata = launch_info.get("provider_metadata")
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _provider_name(launch_info: Mapping[str, Any] | None) -> str | None:
    """返回 launch_info 中的 provider 名称。"""
    if not isinstance(launch_info, Mapping):
        return None
    raw = launch_info.get("provider")
    return str(raw).strip() if raw not in (None, "") else None


def _declared_file_access_mode(launch_info: Mapping[str, Any] | None) -> str | None:
    """读取 provider 可选声明的文件访问能力。"""
    raw = _provider_metadata(launch_info).get("file_access_mode")
    if raw in (None, ""):
        return None
    return str(raw).strip().lower()


def _declared_path_namespace(launch_info: Mapping[str, Any] | None) -> str | None:
    """读取 provider 可选声明的浏览器路径命名空间。"""
    raw = _provider_metadata(launch_info).get("path_namespace")
    if raw in (None, ""):
        return None
    value = str(raw).strip().lower()
    return value if value in {"windows", "posix", "wsl-posix"} else None


def _ensure_local_file_access_supported(operation: str, launch_info: Mapping[str, Any] | None) -> None:
    """provider 若显式声明 remote/unsupported，本地文件 helper 直接失败。"""
    mode = _declared_file_access_mode(launch_info)
    if mode not in {"remote", "unsupported"}:
        return
    provider = _provider_name(launch_info) or "unknown"
    raise RuntimeError(
        f"[dp] provider {provider!r} 未声明本地文件{operation}能力（file_access_mode={mode}）。"
    )


def _get_wsl_distro_name() -> str | None:
    """获取当前 WSL distro 名；Windows Python 下允许通过 wsl.exe 回退获取。"""
    name = os.environ.get("WSL_DISTRO_NAME", "").strip()
    if name:
        return name
    try:
        value = subprocess.check_output(
            ["wsl.exe", "sh", "-lc", "printf %s \"$WSL_DISTRO_NAME\""],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return value or None
    except Exception:
        return None


def _path_exists_local(path: str | Path) -> bool:
    """在当前 Python 命名空间判断路径是否存在。"""
    try:
        return Path(path).expanduser().exists()
    except Exception:
        return False


def _resolve_local_path(path: str | Path) -> Path:
    """在当前 Python 命名空间解析真实存在的本地路径。"""
    return Path(path).expanduser().resolve(strict=True)


def _raw_path_kind(raw: str) -> str:
    """识别原始路径字符串所属的命名空间。"""
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        return "windows-absolute"
    if re.match(r"^/mnt/[A-Za-z]/", raw):
        return "wsl-drive-mount"
    if raw.startswith("/"):
        return "posix-absolute"
    return "relative"


def _windows_path_from_wsl_mount(raw: str) -> str:
    """把 /mnt/<drive>/... 转成 Windows 盘符路径。"""
    match = re.match(r"^/mnt/([A-Za-z])/(.*)$", raw)
    if not match:
        raise ValueError(f"不是 /mnt/<drive>/ 路径：{raw!r}")
    drive = match.group(1).upper()
    tail = match.group(2)
    return f"{drive}:/{tail}"


def _windows_unc_from_posix(raw: str, distro: str) -> str:
    """把 /tmp/foo 这类 POSIX 绝对路径转成 \\\\wsl$ UNC 路径。"""
    return f"\\\\wsl$\\{distro}" + raw.replace("/", "\\")


def _resolve_windows_browser_path(raw: str) -> str:
    """将原始路径规范化为 Windows 浏览器可访问的路径。"""
    kind = _raw_path_kind(raw)
    host_os = _host_os_name()

    if kind == "windows-absolute":
        if not _path_exists_local(raw):
            raise FileNotFoundError(raw)
        return str(raw).replace("\\", "/")

    if kind == "wsl-drive-mount":
        target = _windows_path_from_wsl_mount(raw)
        if host_os == "windows":
            if not _path_exists_local(target):
                raise FileNotFoundError(target)
        else:
            _resolve_local_path(raw)
        return target

    if kind == "posix-absolute":
        distro = _get_wsl_distro_name()
        if not distro:
            raise RuntimeError(f"[dp] 无法确定 WSL distro，不能把 POSIX 路径转换给 Windows 浏览器：{raw!r}")
        if host_os == "windows":
            target = _windows_unc_from_posix(raw, distro)
            if not _path_exists_local(target):
                raise FileNotFoundError(target)
            return target
        _resolve_local_path(raw)
        return _windows_unc_from_posix(raw, distro)

    resolved = _resolve_local_path(raw)
    return _resolve_windows_browser_path(resolved.as_posix())


def _resolve_posix_browser_path(raw: str) -> str:
    """将原始路径规范化为 POSIX 浏览器可访问的路径。"""
    if _raw_path_kind(raw) == "windows-absolute":
        if not _path_exists_local(raw):
            raise FileNotFoundError(raw)
        return str(raw).replace("\\", "/")
    return _resolve_local_path(raw).as_posix()


def _browser_os_name(obj, launch_info: Mapping[str, Any] | None = None) -> str:
    """从 provider hint 或当前浏览器 UA 推断浏览器所在 OS。"""
    hinted = _normalize_os_name(_provider_metadata(launch_info).get("browser_os"))
    if hinted:
        return hinted

    page = get_owner_or_self(obj)
    ua = get_user_agent(page)

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


def _browser_path_style(obj, launch_info: Mapping[str, Any] | None = None) -> str:
    """决定浏览器更接近 Windows 还是 POSIX 路径命名空间。"""
    hinted = _declared_path_namespace(launch_info)
    if hinted == "windows":
        return "windows"
    if hinted in {"posix", "wsl-posix"}:
        return "posix"
    if obj is None:
        browser_os = _normalize_os_name(_provider_metadata(launch_info).get("browser_os"))
        if not browser_os:
            if os.name == "nt":
                browser_os = "windows"
            elif platform.system() == "Darwin":
                browser_os = "macos"
            else:
                browser_os = "linux"
        return "windows" if browser_os == "windows" else "posix"
    return "windows" if _browser_os_name(obj, launch_info=launch_info) == "windows" else "posix"


def browser_upload_path(
    file_path: str | Path,
    obj=None,
    launch_info: Mapping[str, Any] | None = None,
) -> str:
    """
    将上传文件路径规范化为浏览器所在 OS 可直接访问的路径。

    重点覆盖 WSL Python 接管 Windows Chromium 的场景：
    - /mnt/g/foo.txt -> G:/foo.txt
    - /tmp/foo.txt   -> \\\\wsl$\\<distro>\\tmp\\foo.txt
    """
    _ensure_local_file_access_supported("上传", launch_info)
    raw = str(file_path)
    path_style = _browser_path_style(obj, launch_info=launch_info)
    if path_style == "windows":
        return _resolve_windows_browser_path(raw)
    return _resolve_posix_browser_path(raw)


def browser_download_path(
    save_path: str | Path,
    obj=None,
    launch_info: Mapping[str, Any] | None = None,
) -> str:
    """将下载目录规范化为浏览器所在 OS 可直接写入的路径。"""
    _ensure_local_file_access_supported("下载", launch_info)
    local_dir = Path(save_path).expanduser().resolve()
    local_dir.mkdir(parents=True, exist_ok=True)
    browser_path = browser_upload_path(local_dir, obj, launch_info=launch_info)
    if _browser_path_style(obj, launch_info=launch_info) == "windows":
        return browser_path.replace("/", "\\")
    return browser_path


def _host_os_name() -> str:
    """返回当前 Python 所在宿主 OS。"""
    if os.name == "nt":
        return "windows"
    if platform.system() == "Darwin":
        return "macos"
    return "linux"


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


def upload_file(
    ele: ChromiumElement,
    file_path: str | Path,
    timeout: int = 10,
    launch_info: Mapping[str, Any] | None = None,
) -> ChromiumElement:
    """
    上传文件，兼容直接 file input 与“点击后弹 chooser”的两类元素。

    - 直接 input[type=file]：优先走 DOM.setFileInputFiles，并补发 input/change 事件
    - 其他触发 chooser 的元素：走 set.upload_files() + 原生点击
    """
    normalized = browser_upload_path(file_path, ele, launch_info=launch_info)
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


def _set_browser_download_path(ele: ChromiumElement, browser_path: str) -> None:
    """
    直接设置浏览器下载目录，绕过 DrissionPage 在 WSL 下对路径的本地二次 Path() 处理。
    私有 API 访问已隔离到 _dp_compat.py。
    """
    owner = get_owner_or_self(ele)
    browser = get_browser_from_page(owner)
    set_download_path(browser, browser_path)
    set_download_path(owner, browser_path)
    run_browser_cdp(
        browser,
        "Browser.setDownloadBehavior",
        downloadPath=browser_path,
        behavior="allow",
        eventsEnabled=True,
    )


def _trigger_download_click(ele: ChromiumElement, *, timeout: int, by_js: bool = False) -> None:
    """触发下载点击；默认原生点击，必要时显式走 JS click。"""
    if by_js:
        ele.click(by_js=True)
        return
    native_click(ele, timeout=timeout)


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
    by_js: bool = False,
    timeout: int | None = None,
    launch_info: Mapping[str, Any] | None = None,
):
    """
    下载文件并将保存目录规范化到浏览器所在 OS。

    策略按优先级分两层：
    1. `data:` 直链：直接本地保存，不依赖浏览器下载管理器
    2. 统一走浏览器下载目录 + 原生点击 + 完成等待的 CDP 路径

    设计目的：
    - 避免同一 helper 维护两套下载主路径
    - 对支持的 Chrome/provider 链路，尽量在下载任务创建时改写目标文件名
    - 对 WSL 接管 Windows Chromium 这类跨 OS 场景避免路径被本地 `Path()` 改坏
    """
    _ensure_local_file_access_supported("下载", launch_info)
    href = ele.attr("href") or ""
    local_dir = Path(save_path).expanduser().resolve()
    target_name = _download_target_name(ele, rename=rename, suffix=suffix)
    if href.startswith("data:"):
        final_path = _save_data_url(href, local_dir / target_name)
        print(f"[dp] download strategy=data-url target={final_path}")
        return final_path

    local_dir.mkdir(parents=True, exist_ok=True)
    known_names = {p.name for p in local_dir.iterdir()}
    timeout = 30 if timeout is None else timeout
    browser_os = _browser_os_name(ele, launch_info=launch_info)

    print(
        "[dp] download plan:"
        f" browser_os={browser_os}"
        f" dir={local_dir}"
        f" name={target_name}"
    )

    browser_path = browser_download_path(save_path, ele, launch_info=launch_info)
    print(f"[dp] download strategy=raw-cdp browser_path={browser_path}")
    _owner = get_owner_or_self(ele)
    _browser = get_browser_from_page(_owner)
    _orig_browser_path = get_download_path(_browser)
    _orig_owner_path = get_download_path_sentinel(_owner)
    intent = DownloadIntent(
        target_name=target_name,
        rename_requested=bool(rename or suffix is not None),
        href=href or None,
        download_attr=(ele.attr("download") or None),
    )
    interceptor = None
    try:
        try:
            interceptor = prepare_download_interceptor(_owner, intent)
            if interceptor is not None:
                interceptor.enable()
        except Exception as e:
            print(f"[dp] download rename strategy=fetch-header failed={type(e).__name__}: {e}")
        _set_browser_download_path(ele, browser_path)
        _trigger_download_click(ele, timeout=max(10, int(timeout)), by_js=by_js)
        final_path = _wait_download_complete(local_dir, known_names, target_name, timeout)
        print(f"[dp] download strategy=raw-cdp done={final_path}")
    finally:
        if interceptor is not None:
            try:
                interceptor.cleanup()
            except Exception:
                pass
        # 恢复浏览器原始下载目录，避免持久污染用户会话
        if _orig_browser_path is not None:
            set_download_path(_browser, _orig_browser_path)
            if not is_download_path_missing(_orig_owner_path):
                set_download_path(_owner, _orig_owner_path)
            try:
                run_browser_cdp(
                    _browser,
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
