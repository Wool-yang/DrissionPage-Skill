# File Helper Path and Compatibility Closure Design

**Status:** Draft
**Date:** 2026-04-01
**Scope:** `dp` source bundle file helper runtime behavior

## Goal

在引入下载 correlation 子层的同时，收口 `templates/utils.py` 里仍然存在的两个行为缺口：

- WSL `/tmp/...` 路径到 Windows 浏览器路径的回退链仍然不真实
- `download_file()` 的公开签名仍保留了一个不再合理的历史参数

本次设计要解决的核心问题：

- `browser_upload_path()` 对 `wsl.exe` 回退出来的 distro 没有真正用于 UNC 生成
- spec 要求“无法确定 distro 时明确报错”，当前实现仍会 warning 后回退为原始 POSIX 路径
- `download_file()` 统一主路径后，`by_js` 仍然应该保留在点击层，而 `new_tab` 已经不再属于合理 contract

本次设计默认前提：

- `download_file()` 继续只处理**单目标下载**
- 不把列表遍历、批量重试、结果聚合等 orchestration 逻辑并入 helper

## Non-Goals

本次设计明确不做以下事项：

- 不恢复同 OS 的 `click.to_download()` 主路径
- 不重开第二套下载策略
- 不修改 upload helper 的公开签名
- 不把路径处理抽成新的公开模块
- 不改变 `download_file()` 的对外定位
- 不为 `new_tab` 保留历史兼容层
- 不为批量下载预埋额外公开参数

## Problem Statement

### 1. WSL Distro Fallback Stops at the Helper Boundary

当前 `browser_upload_path()` 在 Windows 浏览器 + POSIX 绝对路径场景下会进入 `_resolve_windows_browser_path()`。
该函数确实会先调用 `_get_wsl_distro_name()`。

但后续真正做 UNC 转换时，又转去调用 `_to_windows_browser_path()`，
而后者只读 `WSL_DISTRO_NAME` 环境变量，不消费前一步回退得到的 distro。

结果：

- `wsl.exe` 回退明明成功
- 最终路径仍可能 warning 并返回原始 `/tmp/...`

这违背了现有 spec。

### 2. `new_tab` Is No Longer a Truthful Public Parameter

当前 `download_file()` 仍保留：

- `new_tab`
- `by_js`

但这两个参数的性质已经不同：

- `by_js` 仍然只影响“如何触发点击”，因此是合理的点击层兜底参数
- `new_tab` 则不再影响 helper 的核心输出，也不再对应当前统一下载主路径中的任何稳定语义

继续保留 `new_tab` 的问题不是“没有实现完整兼容”，而是它本身已经不再是一个真实的 helper contract。
对 `download_file()` 来说，公开职责是：

- 触发下载
- 等待文件落盘
- 返回最终文件路径

而不是：

- 管理新标签页生命周期
- 追踪 tab 切换结果
- 暴露“在新标签里打开下载”的页面行为细节

因此本次应删除 `new_tab`，而不是继续假装兼容。

## Design Principles

1. Truthful path conversion  
   路径转换链路必须真正消费回退结果，不能“检测成功但使用失败”。

2. Fail fast instead of fake compatibility  
   无法建立 Windows 浏览器可访问路径时，应明确失败，不返回看似成功但实际不可用的路径。

3. Keep unified download strategy  
   不为兼容性回归重新打开 DP native download 主路径。

4. Keep only truthful public parameters  
   公开签名中只保留仍然对应真实行为边界的参数；不再为历史遗留参数保留 facade。

5. Keep orchestration out of the helper  
   目标枚举、批量重试、结果聚合不属于 `download_file()` 的职责。

## Proposed Changes

### 1. Close the WSL UNC Conversion Chain

收口策略：

- `_get_wsl_distro_name()` 仍作为唯一“获取 distro 名”的入口
- Windows 浏览器 + POSIX 路径转换时，真正生成 UNC 路径的函数必须显式接收该 distro 值
- 不再允许某个 helper 先拿到 distro，后一个 helper 又重新去读环境变量

推荐做法：

- 删除 `_to_windows_browser_path()` 中对 `WSL_DISTRO_NAME` 的隐式读取职责
- 要么改为 `_to_windows_browser_path(path, distro=None)`
- 要么直接由 `_resolve_windows_browser_path()` 调用 `_windows_unc_from_posix(raw, distro)`

行为边界：

- 若 `distro` 可得，返回 `\\wsl$\\<distro>\\...`
- 若不可得，直接抛 `RuntimeError`
- 不再打印 warning 后返回 POSIX 路径

### 2. Remove `new_tab`, Keep `by_js` as the Only Click Escape Hatch

本次明确收口为：

- `by_js` 保留在 `download_file()` 的公开签名中
  - 它只表示“点击如何触发”
  - `False` 时走 `native_click()`
  - `True` 时走显式 `ele.click(by_js=True)` 分支

- `new_tab` 从 `download_file()` 公开签名中彻底移除
  - 不保留 deprecated 参数
  - 不提供兼容 wrapper
  - 不在 helper 内部继续透传给无意义的调用链

原因：

- `by_js` 是触发层参数，不改变下载主路径
- `new_tab` 已不对应当前 helper 的稳定职责边界，保留只会制造误导
- 批量控制也不属于 helper 的稳定职责边界，因此不在本次签名中引入

新增一个内部触发函数，例如：

```python
def _trigger_download_click(ele, *, timeout: int, by_js: bool = False):
    ...
```

`download_file()` 只负责调用它，不再直接内联点击策略。

### 3. Keep Unified Download Path Semantics

本次明确保持：

- 下载目录设置仍统一走 raw/CDP 路径
- 最终完成判断仍通过落盘等待
- 即使 `by_js` 生效，也不意味着重新走 `click.to_download()`

换句话说，保留的是“如何触发下载”的最小兜底参数，
不是“恢复旧下载管理器主路径”或“保留历史 tab 行为参数”。

## File Layout

本次行为收口涉及：

- Modify: `templates/utils.py`
- Modify: `scripts/test_helpers.py`
- Modify: `references/workflows.md`
- Modify: `evals/evals.json`
- Modify: `evals/smoke-checklist.md`
- Optional Modify: `SKILL.md`

## Testing Changes

至少新增以下回归测试：

1. `browser_upload_path()` 在 `WSL_DISTRO_NAME` 为空、但 `wsl.exe` 可返回 distro 时，最终输出 UNC 路径
2. 上述场景下不再 fallback 为原始 POSIX 路径
3. 无法获取 distro 时，Windows 浏览器路径转换直接失败
4. `download_file(by_js=True)` 走 JS click 分支
5. `download_file()` 的公开签名中不再出现 `new_tab`
6. canonical docs / examples 不再引用 `download_file(..., new_tab=...)`
7. 即使保留 `by_js` 兜底，下载主路径仍不回到 DP download manager

## Acceptance Criteria

当以下条件全部满足时，本次设计视为完成：

- `/tmp/...` 在 Windows 浏览器场景下不再“回退成功但最终失效”
- 无法确定 distro 时路径 helper 明确失败
- `download_file()` 公开签名只保留真实有效的参数
- `new_tab` 不再作为历史参数继续存在
- `download_file()` 仍然保持单目标 helper 边界
- 统一 raw/CDP 下载主路径不被重新分叉

## Rationale

这次 closure 的目标不是回退架构，而是把“路径语义”和“点击兼容语义”都说真、做真。

当前实现最大的风险不是直接报错，而是：

- 看起来支持 WSL 回退，实际上没把回退值用到底
- 看起来还支持 `new_tab`，实际上它已不再对应真实 helper 语义

这两类问题都必须收口成可验证的真实行为。
