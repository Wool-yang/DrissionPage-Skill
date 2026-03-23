"""通用操作封装——截图、数据保存、等待、原生交互等高频操作。"""
import json
import re
import sys
from datetime import date
from pathlib import Path
from DrissionPage import ChromiumPage
from DrissionPage._elements.chromium_element import ChromiumElement


def screenshot(page: ChromiumPage, path: Path, full_page: bool = True) -> Path:
    """等待页面加载后截图，返回保存路径。"""
    page.wait.doc_loaded()
    page.get_screenshot(path=str(path.parent), name=path.name, full_page=full_page)
    print(f"[dp] screenshot -> {path}")
    return path


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
        today = date.today().isoformat()
        text = re.sub(r'last_run:[ \t]*\S*', f'last_run: {today}', text)
        text = re.sub(r'status:[ \t]*\S*', f'status: {status}', text)
        script.write_text(text, encoding="utf-8")
    except Exception:
        pass  # 回写失败不影响主流程
