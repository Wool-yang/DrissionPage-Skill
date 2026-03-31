"""浏览器连接 helper——默认先解析 provider；普通 CDP 端口接入由 cdp-port provider 承担。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections.abc import Mapping as MappingABC
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

from DrissionPage import Chromium, ChromiumOptions, ChromiumPage, WebPage

DEFAULT_FALLBACK_PROVIDER = "cdp-port"
DEFAULT_PROVIDER_TIMEOUT = 60


def _normalize_provider_name(name: str) -> str:
    key = (name or "").strip().lower()
    if not key:
        raise ValueError("browser provider 不能为空。")
    if not re.fullmatch(r"[a-z0-9-]+", key):
        raise ValueError(f"browser provider 名称不合法：{name!r}")
    return key


def _normalize_provider_file_stem(stem: str) -> str:
    key = (stem or "").strip().lower().replace("_", "-")
    if not key:
        raise ValueError("browser provider 文件名不能为空。")
    if not re.fullmatch(r"[a-z0-9-]+", key):
        raise ValueError(f"browser provider 文件名不合法：{stem!r}")
    return key


def _iter_workspace_dp_roots() -> list[Path]:
    """返回可用于查找 .dp/providers 的候选 .dp 根目录列表。"""
    roots: list[Path] = []
    seen: set[Path] = set()

    connect_file = Path(__file__).resolve()
    if connect_file.parent.name == "lib" and connect_file.parent.parent.name == ".dp":
        dp_root = connect_file.parent.parent
        roots.append(dp_root)
        seen.add(dp_root)

    cwd = Path.cwd().resolve()
    for base in (cwd, *cwd.parents):
        dp_root = base / ".dp"
        if dp_root.is_dir() and dp_root not in seen:
            roots.append(dp_root)
            seen.add(dp_root)
    return roots


def _provider_file_names(name: str) -> tuple[str, str]:
    normalized = _normalize_provider_name(name)
    return f"{normalized}.py", f"{normalized.replace('-', '_')}.py"


def _raise_provider_name_conflict(name: str, first: Path, second: Path) -> None:
    raise ValueError(
        f"browser provider {name!r} 存在命名冲突："
        f"{first.name} 与 {second.name} 归一化后同名。"
    )


def _read_workspace_config() -> dict[str, Any]:
    """读取当前工作区 .dp/config.json；不存在时返回空字典。"""
    for dp_root in _iter_workspace_dp_roots():
        config_path = dp_root / "config.json"
        if not config_path.is_file():
            continue
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"工作区配置损坏：{config_path}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"工作区配置格式错误：{config_path}")
        return data
    return {}


def _default_provider_from_config(raw: Any) -> str:
    """按 runtime/doctor 共享语义解析 default_provider。"""
    if not isinstance(raw, str):
        return DEFAULT_FALLBACK_PROVIDER
    value = raw.strip()
    if not value:
        return DEFAULT_FALLBACK_PROVIDER
    return _normalize_provider_name(value)


def _provider_file_candidates(name: str) -> list[Path]:
    """返回 provider 文件候选路径列表。"""
    normalized = _normalize_provider_name(name)
    kebab_name, snake_name = _provider_file_names(normalized)
    candidates: list[Path] = []
    seen: set[Path] = set()
    for dp_root in _iter_workspace_dp_roots():
        providers_dir = dp_root / "providers"
        kebab_path = (providers_dir / kebab_name).resolve()
        snake_path = (providers_dir / snake_name).resolve()
        if kebab_path != snake_path and kebab_path.is_file() and snake_path.is_file():
            _raise_provider_name_conflict(normalized, kebab_path, snake_path)
        for path in (kebab_path, snake_path):
            if path not in seen:
                candidates.append(path)
                seen.add(path)
    return candidates


def _load_module_from_file(name: str, path: Path) -> ModuleType:
    """从本地文件加载 provider 模块。"""
    if not path.is_file():
        raise FileNotFoundError(path)

    module_name = f"_dp_provider_{_normalize_provider_name(name).replace('-', '_')}_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise ImportError(f"无法为 provider 文件创建 import spec：{path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(module_name, None)
        raise


def _validate_provider_contract(name: str, module: ModuleType) -> ModuleType:
    """校验 provider 模块是否满足最小 contract。"""
    missing: list[str] = []
    for attr in ("start_profile", "extract_debug_address"):
        if not callable(getattr(module, attr, None)):
            missing.append(attr)
    if missing:
        raise TypeError(
            f"browser provider {name!r} 缺少必需接口：{', '.join(missing)}"
        )
    return module


def _discover_workspace_providers() -> dict[str, Path]:
    """发现工作区 provider，返回公开名到文件路径的映射。"""
    discovered: dict[str, Path] = {}
    for dp_root in _iter_workspace_dp_roots():
        providers_dir = dp_root / "providers"
        if not providers_dir.is_dir():
            continue
        local_seen: dict[str, Path] = {}
        for item in sorted(providers_dir.glob("*.py")):
            if item.name == "__init__.py":
                continue
            normalized = _normalize_provider_file_stem(item.stem)
            current = item.resolve()
            previous = local_seen.get(normalized)
            if previous and previous != current:
                _raise_provider_name_conflict(normalized, previous, current)
            local_seen[normalized] = current
        for name, path in local_seen.items():
            discovered.setdefault(name, path)
    return discovered


def list_browser_providers() -> list[str]:
    """列出当前工作区 `.dp/providers/` 下可见的 provider 名称。"""
    return sorted(_discover_workspace_providers())


def load_browser_provider(name: str) -> ModuleType:
    """加载 browser provider。"""
    normalized = _normalize_provider_name(name)
    attempted_files = _provider_file_candidates(normalized)

    last_error: Exception | None = None

    for path in attempted_files:
        if not path.is_file():
            continue
        try:
            return _validate_provider_contract(normalized, _load_module_from_file(normalized, path))
        except Exception as exc:
            last_error = exc
            break

    searched_files = ", ".join(str(p) for p in attempted_files) or "无"
    visible = ", ".join(list_browser_providers()) or "无"
    detail = f"；最后错误：{last_error}" if last_error else ""
    raise ValueError(
        f"未找到 browser provider {normalized!r}。"
        f" 已搜索文件：{searched_files}。"
        f" 当前工作区可见 provider：{visible}。"
        f" 请在 .dp/providers/{normalized}.py 提供实现。"
        f"{detail}"
    )


def get_default_browser_provider() -> str:
    """返回工作区默认 provider；未配置时回退到 cdp-port。"""
    config = _read_workspace_config()
    return _default_provider_from_config(config.get("default_provider"))


def build_chromium_options(address: str) -> ChromiumOptions:
    """根据调试地址构造只接管现有浏览器的 ChromiumOptions。"""
    co = ChromiumOptions(read_file=False)
    co.set_address(address)
    co.existing_only(True)
    return co


def _require_explicit_port(port: str | None) -> str:
    """回退到 cdp-port provider 时，端口必须显式提供。"""
    value = (port or "").strip()
    if value:
        return value
    raise ValueError(
        "[dp] 未提供测试端口。\n"
        f"[dp] 当前默认 provider 为 {DEFAULT_FALLBACK_PROVIDER!r}，"
        "必须显式传入 --port 或 browser_profile.port。"
    )


def build_default_browser_profile(provider: str, port: str | None = None) -> dict[str, Any]:
    """根据默认 provider 生成兼容包装器使用的最小 profile。"""
    normalized = _normalize_provider_name(provider)
    value = (port or "").strip()
    if normalized == DEFAULT_FALLBACK_PROVIDER:
        return {"port": _require_explicit_port(value)}
    return {"port": value} if value else {}


def _connect_page_by_address(
    address: str,
    *,
    fresh_tab: bool = False,
    url: str = "about:blank",
) -> ChromiumPage:
    """按调试地址接管已有浏览器，可选新开标签页。"""
    co = build_chromium_options(address)
    if not fresh_tab:
        return ChromiumPage(co)

    browser = Chromium(co)
    tab = browser.new_tab(url=url)
    return ChromiumPage(co, tab_id=tab.tab_id)


def connect_browser_by_address(address: str) -> ChromiumPage:
    """按完整调试地址接管已有浏览器。"""
    page = _connect_page_by_address(address)
    print(f"[dp] connected @ {address}")
    return page


def connect_browser_by_address_fresh_tab(address: str, url: str = "about:blank") -> ChromiumPage:
    """按完整调试地址接管已有浏览器，并新建标签页。"""
    page = _connect_page_by_address(address, fresh_tab=True, url=url)
    print(f"[dp] connected fresh tab @ {address} ({page.tab_id})")
    return page


def connect_web_page_by_address(address: str, mode: str = "d") -> WebPage:
    """按完整调试地址接管已有浏览器，并返回 WebPage。"""
    page = WebPage(mode=mode, chromium_options=build_chromium_options(address))
    print(f"[dp] connected WebPage @ {address} ({page.mode})")
    return page


def start_browser_profile(
    provider: str,
    profile: Mapping[str, Any] | None = None,
    *,
    base_url: str | None = None,
    timeout: int = DEFAULT_PROVIDER_TIMEOUT,
    extra_params: Mapping[str, Any] | None = None,
) -> Any:
    """通过指定 provider 启动一个浏览器 profile，并返回原始响应。"""
    module = load_browser_provider(provider)
    return module.start_profile(
        dict(profile or {}),
        base_url=base_url,
        timeout=timeout,
        extra_params=dict(extra_params or {}),
    )


def get_debug_address(provider: str, start_result: Any) -> str:
    """从 provider 启动响应中提取调试地址。"""
    module = load_browser_provider(provider)
    address = module.extract_debug_address(start_result)
    if not isinstance(address, str) or not address.strip():
        raise ValueError(f"browser provider {provider!r} 返回了空 debug_address：{address!r}")
    return address.strip()


def get_provider_metadata(provider: str, start_result: Any) -> dict[str, Any] | None:
    """从 provider 启动响应中提取可安全持久化的 metadata。"""
    module = load_browser_provider(provider)
    extractor = getattr(module, "extract_metadata", None)
    if extractor is None:
        return None
    metadata = extractor(start_result)
    if metadata is None:
        return None
    if not isinstance(metadata, MappingABC):
        raise TypeError(
            f"browser provider {provider!r} 的 extract_metadata() 必须返回 mapping 或 None，"
            f"实际为 {type(metadata).__name__}"
        )
    return dict(metadata)


def build_launch_info(
    provider: str,
    profile: Mapping[str, Any] | None,
    *,
    base_url: str | None,
    start_result: Any,
) -> dict[str, Any]:
    """把 provider 启动结果规范化为对工作流安全的 launch_info。"""
    return {
        "provider": _normalize_provider_name(provider),
        "provider_url": base_url,
        "browser_profile": dict(profile or {}),
        "debug_address": get_debug_address(provider, start_result),
        "provider_metadata": get_provider_metadata(provider, start_result),
    }


def connect_browser_from_start_result(provider: str, start_result: Any) -> ChromiumPage:
    """根据 provider 启动结果连接浏览器。"""
    return connect_browser_by_address(get_debug_address(provider, start_result))


def connect_browser_from_start_result_fresh_tab(
    provider: str,
    start_result: Any,
    url: str = "about:blank",
) -> ChromiumPage:
    """根据 provider 启动结果连接浏览器，并新建标签页。"""
    return connect_browser_by_address_fresh_tab(get_debug_address(provider, start_result), url=url)


def connect_web_page_from_start_result(
    provider: str,
    start_result: Any,
    mode: str = "d",
) -> WebPage:
    """根据 provider 启动结果连接 WebPage。"""
    return connect_web_page_by_address(get_debug_address(provider, start_result), mode=mode)


def start_profile_and_connect_browser(
    provider: str,
    profile: Mapping[str, Any] | None = None,
    *,
    base_url: str | None = None,
    timeout: int = DEFAULT_PROVIDER_TIMEOUT,
    extra_params: Mapping[str, Any] | None = None,
    fresh_tab: bool = False,
    url: str = "about:blank",
) -> tuple[dict[str, Any], ChromiumPage]:
    """通过 provider 启动 profile，然后返回 launch_info 与 ChromiumPage。"""
    start_result = start_browser_profile(
        provider,
        profile,
        base_url=base_url,
        timeout=timeout,
        extra_params=extra_params,
    )
    launch_info = build_launch_info(
        provider,
        profile,
        base_url=base_url,
        start_result=start_result,
    )
    if fresh_tab:
        page = connect_browser_by_address_fresh_tab(launch_info["debug_address"], url=url)
    else:
        page = connect_browser_by_address(launch_info["debug_address"])
    return launch_info, page


def start_profile_and_connect_web_page(
    provider: str,
    profile: Mapping[str, Any] | None = None,
    *,
    base_url: str | None = None,
    timeout: int = DEFAULT_PROVIDER_TIMEOUT,
    extra_params: Mapping[str, Any] | None = None,
    mode: str = "d",
) -> tuple[dict[str, Any], WebPage]:
    """通过 provider 启动 profile，然后返回 launch_info 与 WebPage。"""
    start_result = start_browser_profile(
        provider,
        profile,
        base_url=base_url,
        timeout=timeout,
        extra_params=extra_params,
    )
    launch_info = build_launch_info(
        provider,
        profile,
        base_url=base_url,
        start_result=start_result,
    )
    page = connect_web_page_by_address(launch_info["debug_address"], mode=mode)
    return launch_info, page


def parse_port() -> str | None:
    """从命令行解析可选的 --port 参数。"""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--port", default=None)
    return parser.parse_known_args()[0].port
