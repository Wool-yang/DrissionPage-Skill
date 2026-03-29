"""DrissionPage 私有 API 兼容层。

所有对 DrissionPage 内部属性 / 方法的直接访问都在本文件集中封装。
当 DrissionPage 升级后若有 breaking change，只需修改本文件。

每个函数都标注了所依赖的私有实现，便于版本升级时定向验证。
若需升级 DrissionPage，请先逐一检查本文件中标注"私有"的函数。

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
