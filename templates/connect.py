"""浏览器连接 helper——默认只接管已有浏览器；纯 SessionPage 属于少数例外路径。"""
import argparse
import sys

from DrissionPage import Chromium, ChromiumOptions, ChromiumPage, WebPage

DEFAULT_PORTS = ["9222", "9333", "9444", "9111"]


def _iter_existing_browser_options(port: str | None = None):
    """按候选端口依次生成“只接管已有浏览器”的配置。"""
    for p in ([port] if port else DEFAULT_PORTS):
        co = ChromiumOptions(read_file=False)
        co.set_address(f"127.0.0.1:{p}")
        co.existing_only(True)
        yield p, co


def _exit_no_browser(port: str | None = None) -> None:
    """统一输出连接失败提示。"""
    port_hint = port or "/".join(DEFAULT_PORTS)
    sys.exit(
        "[dp] 未找到可连接的浏览器。\n"
        f"[dp] 已尝试端口：{port_hint}\n"
        "[dp] 请先手动启动带远程调试端口的 Chromium 浏览器，"
        "例如：chrome --remote-debugging-port=9222"
    )


def connect_browser(port: str | None = None) -> ChromiumPage:
    """扫描常用调试端口，连接已有浏览器实例。"""
    for p, co in _iter_existing_browser_options(port):
        try:
            page = ChromiumPage(co)
            print(f"[dp] connected @ {p}")
            return page
        except Exception:
            continue
    _exit_no_browser(port)


def connect_browser_fresh_tab(port: str | None = None, url: str = "about:blank") -> ChromiumPage:
    """连接已有浏览器并新建一个标签页，避免复用可能异常的旧 tab。

    实现说明：
    - Chromium(co) 连接已有浏览器实例（existing_only=True）
    - browser.new_tab() 创建新标签页并返回 tab 对象（含 tab_id）
    - ChromiumPage(co, tab_id=tab.tab_id) 绑定到该 tab_id

    设计风险：ChromiumPage 构造时以 co（配置）而非 browser 对象作为入口，
    若 DrissionPage 内部存在单例缓存，有可能忽略传入的 tab_id 而绑定到默认 tab。
    当前在 DrissionPage 4.1.1.x 下通过 monkeypatch 测试验证，传入 tab_id 被正确使用。
    若升级 DrissionPage 后行为异常，应改用 browser.get_tab(tab_id) 替代 ChromiumPage(co, tab_id=...)。
    """
    for p, co in _iter_existing_browser_options(port):
        try:
            browser = Chromium(co)
            tab = browser.new_tab(url=url)
            page = ChromiumPage(co, tab_id=tab.tab_id)
            print(f"[dp] connected fresh tab @ {p} ({tab.tab_id})")
            return page
        except Exception:
            continue
    _exit_no_browser(port)


def connect_web_page(port: str | None = None, mode: str = "d") -> WebPage:
    """连接已有浏览器并返回 WebPage，便于浏览器/requests 混合模式切换。"""
    for p, co in _iter_existing_browser_options(port):
        try:
            page = WebPage(mode=mode, chromium_options=co)
            print(f"[dp] connected WebPage @ {p} ({page.mode})")
            return page
        except Exception:
            continue
    _exit_no_browser(port)


def parse_port() -> str | None:
    """从命令行解析可选的 --port 参数。"""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--port", default=None)
    return parser.parse_known_args()[0].port
