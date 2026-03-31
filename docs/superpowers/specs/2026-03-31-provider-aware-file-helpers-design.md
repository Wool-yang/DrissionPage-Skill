# Provider-Aware File Helpers Design

**Status:** Draft
**Date:** 2026-03-31
**Scope:** `dp` source bundle file upload/download helper semantics

## Goal

把 `templates/utils.py` 中的文件上传/下载 helper，从“只按宿主 OS 与浏览器 OS 做路径转换”的旧模型，
升级为能同时兼顾 provider-first 运行模式与多端路径差异的正式设计。

本次设计要解决的核心问题：

- `upload_file()` / `download_file()` 仍然沿用 pre-provider 时代的多端心智模型
- helper 只知道 `host_os × browser_os`，不知道 provider 带来的路径命名空间和文件访问能力差异
- workflow 已经拿到 `launch_info`，但没有把 provider 上下文继续传给文件 helper
- `browser_upload_path()` 默认先在当前 Python 命名空间里 `resolve(strict=True)`，会在 Windows Python + WSL 路径字符串场景提前失败
- 当前 contract 没有表达“某些 provider 不具备本地文件访问能力”，导致 helper 只能盲猜

## Non-Goals

本次设计明确不做以下事项：

- 不修改 `templates/connect.py` 的公开 provider-first 连接 API
- 不要求所有 provider 都实现统一的重型文件系统 schema
- 不支持真正远端浏览器文件桥接（例如自动上传到远端容器或虚拟机）
- 不把 `utils.py` 改造成 provider-specific 的条件分支集合
- 不重写 `upload_file()` / `download_file()` 的业务语义（仍然保留原 helper 名称与主流程）

## Audit Summary

### 1. 旧设计的主轴是“多端路径”，不是“provider 上下文”

`templates/utils.py` 当前的核心判断是：

- 当前 Python 运行在哪个宿主 OS
- 浏览器 UA 看起来属于哪个 OS

代表性实现：

- `_browser_os_name()`
- `browser_upload_path()`
- `browser_download_path()`

这些函数从未读取 provider 名，也不消费 `launch_info`。

### 2. 旧设计故意把 provider 抽象掉了

这并不是实现遗漏，而是当时的设计边界：

> provider 负责“把你带到一个可用浏览器”；从那之后，文件 helper 只负责处理跨平台路径。

这个边界在以下场景下还能成立：

- Linux Python -> Linux Chromium
- macOS Python -> macOS Chromium
- Windows Python -> Windows Chromium
- WSL Python -> Windows Chromium（且原始路径本身仍能先被 WSL Python 正确解析）

### 3. 现在的真实问题是“路径命名空间”，不只是 OS

本次 smoke 失败表明，真正的输入维度至少有四个：

- 原始路径字符串属于哪个命名空间
- 当前 Python 解释器运行在哪个命名空间
- 浏览器所在 OS / 命名空间
- provider 是否声明本地文件访问能力

旧 helper 只建模了后两个中的一部分，因此在：

- Windows Python
- 浏览器为 Windows Chromium
- 调用方传入 WSL `/tmp/...` 路径字符串

时，会在 `Path(file_path).resolve(strict=True)` 这里提前崩掉。

## Design Principles

1. Provider-aware, not provider-specific
   helper 应能消费 provider 上下文，但不能硬编码某个 provider 名的特殊逻辑。

2. Namespace-first
   路径处理的第一判断不再是“当前 OS”，而是“原始路径字符串属于哪个命名空间”。

3. Capability hints are optional
   provider 可以提供文件访问能力 hints；不提供时 helper 退回到保守 heuristics。

4. Fail fast on unsupported file access
   如果 provider 明确声明不支持本地文件访问，helper 应直接报错，而不是盲猜路径。

5. Backward compatibility by default
   `upload_file()` / `download_file()` 保持原有主签名与默认行为；新增上下文字段必须是可选的。

6. Workflow should pass context forward
   既然高层已经拿到 `launch_info`，workflow 模板就不应再把它丢掉。

## Proposed Architecture

### 1. File Helpers Accept Launch Context

将以下 helper 升级为可选消费 `launch_info`：

```python
def browser_upload_path(file_path, obj=None, launch_info=None) -> str: ...
def browser_download_path(save_path, obj=None, launch_info=None) -> str: ...
def upload_file(ele, file_path, timeout=10, launch_info=None): ...
def download_file(ele, save_path, ..., launch_info=None): ...
```

约束：

- `launch_info` 为空时保持现有兼容行为
- `launch_info` 存在时，helper 优先读取：
  - `provider`
  - `provider_metadata`
  - `browser_os` hint
  - `file_access_mode` hint

### 2. Split “Path Namespace” from “Browser OS”

新增内部概念：

- `path_namespace`
  - `windows-absolute`
  - `wsl-drive-mount`
  - `posix-absolute`
  - `relative`
- `browser_os`
  - `windows`
  - `linux`
  - `macos`

新流程：

1. 先识别原始路径字符串属于哪种 namespace
2. 再结合 `browser_os` 与 provider hints 决定转换策略
3. 最后才做存在性检查与浏览器可访问路径输出

这取代当前“一上来直接 `Path(...).resolve(strict=True)`”的流程。

### 3. Introduce Optional Provider File Access Hints

在 `references/provider-contract.md` 中新增推荐但非强制的 metadata hints：

```python
{
    "browser_os": "windows" | "linux" | "macos",
    "file_access_mode": "local" | "local-cross-namespace" | "remote" | "unknown",
    "path_namespace": "windows" | "posix" | "wsl-posix",
}
```

含义：

- `browser_os`
  provider 已知浏览器所在 OS 时可显式声明，helper 不必再只靠 UA 猜
- `file_access_mode`
  provider 是否具备本地文件访问能力
- `path_namespace`
  provider 若知道浏览器更接近哪种路径命名空间，可作为转换 hint

这些字段都是 optional：

- runtime 不强制 provider 提供
- helper 仅在存在时优先使用

### 4. Local File Access Gate

在 upload/download helper 入口增加正式 gate：

- 若 `provider_metadata.file_access_mode == "remote"`，直接报错
- 若 `provider_metadata.file_access_mode == "unknown"` 或缺失，走 heuristic
- 若 `provider_metadata.file_access_mode` 为本地能力，则继续路径转换

这样可以避免以后出现 remote provider 时，helper 继续拿本地路径乱试。

### 5. Windows Browser Upload Path Resolution

针对 `browser_os == "windows"` 的上传路径，策略改为：

1. `windows-absolute`
   - 保持原样
   - 在当前 Python 命名空间校验存在性

2. `wsl-drive-mount` (`/mnt/<drive>/...`)
   - 转成 `X:/...`
   - 在当前命名空间中校验源文件存在性
   - 如果当前 Python 本身是 Windows，则对转换后的 `X:/...` 做存在性校验

3. `posix-absolute` (`/tmp/...`, `/home/...`)
   - 视为 WSL/Unix 风格本地路径
   - 转成 `\\wsl$\\<distro>\\...`
   - WSL distro 优先从环境变量取；缺失时尝试通过 `wsl.exe` 获取
   - 无法确定 distro 时，明确报错而不是 silent fallback

4. `relative`
   - 先在当前 Python 命名空间里解析为绝对路径
   - 再按上述规则继续转换

### 6. Download Strategy Becomes Context-Aware

`download_file()` 的主路径收口为：

- `data:` 直链仍优先本地保存
- 其它下载统一走浏览器下载目录 + 原生点击 + 完成等待的 CDP 下载路径

增强规则：

- provider 明确声明 `remote` 时直接失败
- 对支持的 Chrome/provider 链路，helper 可在下载响应阶段改写 `Content-Disposition`
- 若响应头改名增强失败，仍回退到最终落盘 rename
- workflow 应显式传 `launch_info`

### 7. Workflow and Smoke Must Forward Launch Info

`references/workflows.md` 与 `scripts/smoke.py` 中的 upload/download 示例统一改成：

```python
upload_file(page.ele(FILE_INPUT_SEL), FILE_PATH, launch_info=launch_info)
download_file(ele, run, rename=FILENAME, launch_info=launch_info)
```

原因：

- helper 现在具备 provider-aware 能力
- 但如果 workflow 不传 `launch_info`，这些能力永远无法生效

## Testing Changes

至少新增或调整以下测试：

1. `browser_upload_path()` 能消费 `launch_info.provider_metadata.browser_os`
2. `browser_upload_path()` 对 `file_access_mode == "remote"` 直接报错
3. Windows 浏览器上传场景下，`/mnt/<drive>/...` 可转成盘符路径
4. Windows 浏览器上传场景下，`/tmp/...` 可转成 `\\wsl$\\<distro>\\...`
5. `upload_file()` / `download_file()` 会把 `launch_info` 透传到底层路径 helper
6. smoke upload case 使用 `launch_info` 后通过

## Documentation Changes

需要同步更新：

- `references/provider-contract.md`
- `references/workflows.md`
- `SKILL.md` 中 upload/download 的语义说明（必要时）

核心表达要从：

> helper 处理跨平台路径

升级为：

> helper 默认处理跨平台路径；若调用方提供 `launch_info`，则会结合 provider hints 做更安全的本地文件访问判断。

## Acceptance Criteria

当以下条件全部满足时，本次设计视为完成：

- upload/download helper 接口支持 `launch_info`
- workflow 与 smoke 模板把 `launch_info` 向下传递
- `/tmp/...` 与 `/mnt/<drive>/...` 在 Windows Chromium 场景下都能被正式处理
- provider 可选声明文件访问能力；helper 对 `remote` 明确 fail fast
- 旧调用方式仍可继续工作

## Rationale

这次升级的本质，不是给 `utils.py` 加几个 provider 条件分支，而是把文件 helper 的正式心智模型改成：

> 文件 I/O 不只是“浏览器在哪个 OS 上”，还取决于路径字符串从哪里来、当前 Python 运行在哪个命名空间、以及 provider 是否声明本地文件访问能力。

只有把这三个维度一起纳入 contract，`dp` 的 provider-first 设计与多端可用目标才不会继续互相打架。
