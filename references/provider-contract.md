# Workspace Provider Contract

`dp` runtime 只认工作区 provider 文件。普通远程调试端口接入也被收编为工作区 provider `cdp-port.py`。

## 目录与命名

- 工作区 provider 的唯一正式位置：`.dp/providers/<name>.py`
- 公开 provider 名统一使用 kebab-case，例如 `adspower`、`chrome-cdp`
- 文件名兼容 kebab-case 与 snake_case：
  - `chrome-cdp.py`
  - `chrome_cdp.py`
- 如果两个文件归一化后映射到同一个公开名，runtime 直接报错

## 默认 provider

- 工作区默认 provider 存放在 `.dp/config.json` 的 `default_provider`
- `doctor.py` 首次初始化时会写入：

```json
{
  "default_provider": "cdp-port"
}
```

- 用户或客户端可以把它改成别的工作区 provider，例如 `chrome-cdp`
- 通用 workflow 模板默认通过 `get_default_browser_provider()` 继承这个值；只有任务明确依赖某个 provider 时才应在脚本里固定 provider 名
- 如果默认 provider 最终为 `cdp-port`，则必须显式提供测试端口

## 最小接口

```python
from typing import Any, Mapping


def start_profile(
    profile: Mapping[str, Any] | None = None,
    *,
    base_url: str | None = None,
    timeout: int = 60,
    extra_params: Mapping[str, Any] | None = None,
) -> Any:
    ...


def extract_debug_address(start_result: Any) -> str:
    ...
```

可选接口：

```python
def extract_metadata(start_result: Any) -> Mapping[str, Any] | None:
    ...
```

## 文件访问 hints（对文件 helper 兼容性为条件必需）

如果某个 provider 希望正式兼容 `upload_file()` / `download_file()` 这类本地文件 helper，
则应在 `extract_metadata()` 中返回以下 hints：

```python
{
    "browser_os": "windows" | "linux" | "macos",
    "file_access_mode": "local" | "local-cross-namespace" | "remote" | "unknown",
    "path_namespace": "windows" | "posix" | "wsl-posix",
}
```

说明：

- 这些字段不是 provider 最小连接 contract 的必填项；provider 只做“连接浏览器”时可以不提供
- 但如果 provider 要声称自己与 `upload_file()` / `download_file()` 正式兼容，就应提供这些 hints
- `dp` 的 upload/download helper 在 workflow 传入 `launch_info` 时，会优先消费这些 hints
- `file_access_mode == "remote"` 表示 provider 不具备本地文件访问能力，helper 应直接报错
- 未提供 hints 时，helper 只能退回到保守 heuristics；这对本机浏览器通常够用，但不应被视为 provider 已正式声明文件 helper 兼容性

## Contract 语义

- `start_profile()` 负责启动目标浏览器，并返回 provider 私有结果对象
- `extract_debug_address()` 负责从该结果对象中提取可连接的 `host:port`
- `extract_metadata()` 只返回可安全持久化的字段；不需要时可以省略
- `start_result` 是 opaque result，不要求是 `dict`，也不要求可 JSON 序列化

## Runtime-Managed `cdp-port` Provider

`cdp-port` 是 runtime-managed fallback provider：

- 由 source bundle 模板提供
- 由 `doctor.py` 同步到 `.dp/providers/cdp-port.py`
- 不负责启动浏览器
- 只负责把显式 `port` 转成 `debug_address`

最小 profile：

```python
{"port": "<explicit-port>"}
```

如果没有显式 `port`，必须直接报错，不允许再扫描默认端口列表。

## Provider-Neutral 规则

- runtime 知道 provider 名，但不知道 provider 私有 API 细节
- 通用层允许传入 `base_url`，但不为任何具体 provider 提供默认值
- 具体 provider 的默认 base URL 只能写在 provider 文件内部
- launcher-style provider 可以完全不使用 `base_url`

## 持久化边界

高层 workflow 只消费规范化后的 `launch_info`：

```python
{
    "provider": "...",
    "provider_url": "...",
    "browser_profile": {...},
    "debug_address": "127.0.0.1:PORT",
    "provider_metadata": {...},
}
```

禁止把 raw `start_result` 直接写入输出目录或状态文件。

## API Provider 模板

```python
from __future__ import annotations

from typing import Any, Mapping


DEFAULT_BASE_URL = "http://localhost:50325"


def start_profile(
    profile: Mapping[str, Any] | None = None,
    *,
    base_url: str | None = None,
    timeout: int = 60,
    extra_params: Mapping[str, Any] | None = None,
) -> Any:
    endpoint = (base_url or DEFAULT_BASE_URL).rstrip("/")
    params = dict(profile or {})
    params.update(dict(extra_params or {}))
    return {
        "endpoint": endpoint,
        "params": params,
        "debug_address": "127.0.0.1:PORT",
    }


def extract_debug_address(start_result: Any) -> str:
    return str(start_result["debug_address"])


def extract_metadata(start_result: Any) -> Mapping[str, Any] | None:
    return {"endpoint": start_result["endpoint"]}
```

## Launcher Provider 模板

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def start_profile(
    profile: Mapping[str, Any] | None = None,
    *,
    base_url: str | None = None,
    timeout: int = 60,
    extra_params: Mapping[str, Any] | None = None,
) -> Any:
    port = dict(profile or {}).get("port")
    if not port:
        raise ValueError("launcher provider 需要显式 port")
    launcher = Path(dict(extra_params or {}).get("launcher", "launch-browser"))
    return {
        "launcher": str(launcher),
        "port": port,
        "debug_address": f"127.0.0.1:{port}",
    }


def extract_debug_address(start_result: Any) -> str:
    return str(start_result["debug_address"])


def extract_metadata(start_result: Any) -> Mapping[str, Any] | None:
    return {
        "launcher": start_result["launcher"],
        "port": start_result["port"],
    }
```
