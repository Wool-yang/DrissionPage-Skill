# Workspace Provider Contract

当任务需要接入指纹浏览器、本地 launcher、客户端自带 browser manager，
或任何不是“直接给一个调试端口”的浏览器来源时，读取本文。

`dp` 的 provider 设计目标是把“如何启动或定位浏览器”限制在工作区 provider 内部，
让 workflow 只消费标准化的调试地址和 metadata。普通远程调试端口也被收编为
runtime-managed `cdp-port` provider，因此业务脚本不需要维护两套连接逻辑。

## 核心模型

- runtime 只认工作区 provider 文件
- provider 负责启动或定位目标浏览器
- provider 返回可连接的 `host:port`
- runtime 用 DrissionPage 接管该调试地址
- 高层 workflow 只消费标准化 `launch_info`
- raw provider result 是 provider 私有对象，不写入输出目录或状态文件

## 目录与命名

- 工作区 provider 的唯一正式位置：`.dp/providers/<name>.py`
- 公开 provider 名统一使用 kebab-case，例如 `adspower`、`chrome-cdp`
- 文件名兼容 kebab-case 与 snake_case：
  - `chrome-cdp.py`
  - `chrome_cdp.py`
- 如果两个文件归一化后映射到同一个公开名，runtime 直接报错

## 默认 provider

工作区默认 provider 存放在 `.dp/config.json` 的 `default_provider`。
`doctor.py` 首次初始化时会写入：

```json
{
  "default_provider": "cdp-port"
}
```

用户或客户端可以把它改成别的工作区 provider，例如 `chrome-cdp`。
通用 workflow 模板默认通过 `get_default_browser_provider()` 继承这个值；
只有任务明确依赖某个 provider 时，脚本才应固定 provider 名。

如果默认 provider 最终为 `cdp-port`，必须显式提供测试端口。`dp` 不扫描默认端口列表。

## 最小接口

每个 provider 至少实现两个函数：

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

可选 metadata 接口：

```python
def extract_metadata(start_result: Any) -> Mapping[str, Any] | None:
    ...
```

## Contract 语义

- `start_profile()` 负责启动或定位目标浏览器，并返回 provider 私有结果对象
- `extract_debug_address()` 从该结果对象中提取可连接的 `host:port`
- `extract_metadata()` 只返回可安全持久化、可给 helper 消费的字段；不需要时可以省略
- `start_result` 是 opaque result，不要求是 `dict`，也不要求可 JSON 序列化
- provider 可以通过本地 API、本地 launcher、已有调试端口或客户端能力获取浏览器
- provider 内部可以有自己的默认 `base_url` 或 launcher 配置；通用 runtime 不替具体 provider 设默认值

## 文件访问 hints

如果 provider 希望正式兼容 `upload_file()` / `download_file()` 这类本地文件 helper，
应在 `extract_metadata()` 中返回文件访问 hints：

```python
{
    "browser_os": "windows" | "linux" | "macos",
    "file_access_mode": "local" | "local-cross-namespace" | "remote" | "unknown",
    "path_namespace": "windows" | "posix" | "wsl-posix",
}
```

这些字段不是最小连接 contract 的必填项。只做“连接浏览器”的 provider 可以不提供。
但如果 provider 要声明自己与本地上传/下载 helper 正式兼容，就应提供这些 hints。

helper 行为：

- workflow 传入 `launch_info` 时，`upload_file()` / `download_file()` 优先消费 provider hints
- `file_access_mode == "remote"` 表示 provider 不具备本地文件访问能力，helper 直接报错
- 未提供 hints 时，helper 只能退回到保守 heuristics
- 保守 heuristics 对本机浏览器通常够用，但不等于 provider 已声明正式兼容文件 helper

## Runtime-Managed `cdp-port`

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
- 业务脚本不要直接调用 provider 私有 API；使用 runtime 的 provider-first helper

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

禁止把 raw `start_result` 直接写入输出目录或状态文件。它可能包含 provider 私有结构、
临时凭据、进程对象、不可序列化对象或无稳定兼容承诺的字段。

## API Provider 模板

适用于通过本地 HTTP API 或客户端 API 启动/定位浏览器的 provider：

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

适用于 provider 负责调用本地 launcher，或包装已有启动脚本的场景：

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
