"""DrissionPage 兼容层。

本文件集中封装所有对 DrissionPage 的版本敏感访问，分两类：
- 私有 API 访问：对 DrissionPage 内部属性 / 方法的直接访问
- API 版本差异：不同版本 DrissionPage 的签名或行为差异

原则：只要是 DrissionPage 的版本兼容逻辑，都应先想到往本文件收，不要散落在 utils.py 等业务文件中。

每个函数都标注了所依赖的私有实现，便于版本升级时定向验证。
若需升级 DrissionPage，请先逐一检查本文件。

已验证的 DrissionPage 版本范围：>=4.1.1,<4.2
"""
from __future__ import annotations

_MISSING = object()  # 哨兵：区分"属性不存在"与"属性值为 None/空"


def get_owner_or_self(obj):
    """返回元素所属的 page，若 obj 本身是 page 则返回自身。

    依赖 DrissionPage 私有属性：element.owner
    语义等价于 utils.py 原始写法 getattr(obj, "owner", obj)。
    """
    return getattr(obj, "owner", obj)


def get_browser_from_page(page):
    """从 page 对象取底层 Browser 实例。

    依赖 DrissionPage 私有属性：page._browser
    """
    return page._browser


def get_download_path(obj):
    """读取 browser 或 page 的当前下载目录；属性不存在时返回 None。

    依赖 DrissionPage 私有属性：obj._download_path
    """
    return getattr(obj, "_download_path", None)


def get_download_path_sentinel(obj):
    """读取 browser 或 page 的当前下载目录；属性不存在时返回 _MISSING 哨兵。

    用于需要区分"属性不存在"与"属性值为 None"的恢复场景。
    依赖 DrissionPage 私有属性：obj._download_path
    """
    return getattr(obj, "_download_path", _MISSING)


def is_download_path_missing(val) -> bool:
    """判断 get_download_path_sentinel() 的返回值是否为哨兵（属性不存在）。"""
    return val is _MISSING


def set_download_path(obj, path: str) -> None:
    """设置 browser 或 page 的下载目录（仅当属性存在时才设置）。

    依赖 DrissionPage 私有属性：obj._download_path
    """
    if hasattr(obj, "_download_path"):
        obj._download_path = path


def run_browser_cdp(browser, method: str, **kwargs):
    """在 browser 上执行 CDP 命令。

    依赖 DrissionPage 私有方法：browser._run_cdp(method, **kwargs)
    """
    return browser._run_cdp(method, **kwargs)


def get_user_agent(page) -> str:
    """从 page 获取浏览器 User-Agent 字符串，兼容 DrissionPage API 差异。

    API 版本差异：
    - 4.1.x 部分版本：run_js(expr, as_expr=True) 签名
    - 4.1.x 其他版本：run_js(expr) 签名（as_expr 参数不存在）
    空值或异常时返回空字符串。
    """
    try:
        ua = page.run_js("navigator.userAgent", as_expr=True)
        return ua or ""
    except TypeError:
        try:
            ua = page.run_js("navigator.userAgent")
            return ua or ""
        except Exception:
            return ""
    except Exception:
        return ""
