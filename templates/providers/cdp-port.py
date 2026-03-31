"""Runtime-managed fallback provider for explicit CDP port attachment."""
from __future__ import annotations

from typing import Any, Mapping


def start_profile(
    profile: Mapping[str, Any] | None = None,
    *,
    base_url: str | None = None,
    timeout: int = 60,
    extra_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a debug address for an already-running browser on an explicit port."""
    if base_url:
        raise ValueError("cdp-port provider 不使用 base_url。")

    payload = dict(profile or {})
    if not payload.get("port"):
        raise ValueError("cdp-port provider 需要显式 port。")
    port = str(payload["port"]).strip()
    if not port:
        raise ValueError("cdp-port provider 需要显式 port。")
    return {
        "debug_address": f"127.0.0.1:{port}",
        "port": port,
    }


def extract_debug_address(start_result: Mapping[str, Any]) -> str:
    """Extract the explicit debug address from the fallback provider result."""
    try:
        return str(start_result["debug_address"])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"cdp-port 启动结果中缺少 debug_address：{start_result}") from exc


def extract_metadata(start_result: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return safe metadata for workflow persistence."""
    port = start_result.get("port")
    if not port:
        return None
    return {"port": str(port)}
