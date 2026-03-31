# Download Correlation Runtime Design

**Status:** Draft
**Date:** 2026-04-01
**Scope:** `dp` source bundle runtime download interception / request correlation internals

## Goal

把当前内联在 `templates/utils.py` 里的下载拦截逻辑，重构成一个独立的、下载专用的 correlation 子层，
解决“下载改名增强会污染所有响应”的结构性问题，同时保持对外 contract 仍然收口在 `download_file()`。

本次设计要解决的核心问题：

- `download_file()` 里的 Fetch hook 没有目标请求相关性判断，会改写所有 paused response
- 下载拦截的启用、命中、降级、清理都埋在 helper 里，职责边界不清
- 当前代码缺少“一次下载意图”这个显式对象，导致无法稳定表达“我们想改的是哪一个响应”
- 后续若继续演进下载链路，`utils.py` 会继续膨胀

本次设计默认前提：

- `download_file()` 是**单目标下载内核**
- 一次调用只管理一个目标下载
- 不承担批量下载、下载队列、或“一次点击触发多个文件”的编排职责

## Non-Goals

本次设计明确不做以下事项：

- 不把 correlation 抽成通用网络拦截框架
- 不把该层公开到 `SKILL.md` / README / workflow prose
- 不修改 `templates/connect.py` 的公开 API
- 不新增新的公开 helper 名称给业务脚本直接调用
- 不解决上传、跳转、新标签页等非下载场景的相关性问题
- 不为 `download_file()` 保留与 tab 生命周期有关的历史参数
- 不把 batch download orchestration 纳入本轮 runtime contract

## Problem Statement

### 1. Current Fetch Hook Has No Target Identity

当前 `_prepare_download_request_rename()` 只要启用了 `Fetch.enable(patterns=[{"requestStage": "Response"}])`，
所有进入 callback 的 response 都会被写入 `Content-Disposition: attachment; filename=...`。

这意味着：

- CSS / XHR / image / iframe 响应也可能被错误改写
- 下载触发期间的并发请求越多，污染概率越高
- “增强下载文件名”变成了“劫持整个页面的响应头”

这不是小 bug，而是缺失“目标请求身份”的架构问题。

### 2. Download Intent Is Implicit Instead of Explicit

当前 `download_file()` 只有零散变量：

- `ele`
- `rename`
- `suffix`
- `href`

但没有一个显式对象来表达：

- 本次下载的目标文件名是什么
- 我们有哪几个可用线索来识别目标响应
- 什么情况下允许改写响应头
- 命中一次之后是否应立即停用拦截

没有这个中间层，任何“只改目标响应”的逻辑都会继续散落在 helper 里。

### 3. Interceptor Lifecycle Is Not Isolated

下载拦截现在由 `download_file()` 自己：

- enable Fetch
- 注册 callback
- 执行点击
- 关闭 Fetch

但这些步骤没有被封装成一个作用域明确的对象或上下文。
一旦中途异常、点击前后行为变化、后续需要加超时/命中状态，就会继续把 `download_file()` 变成流程脚本。

## Design Principles

1. Download-specific, not prematurely generic  
   这是下载内部子层，不是未来所有网络场景的基础框架。

2. Single-target per call  
   一次 `download_file()` 调用只对应一个下载意图和一个目标结果。

3. Intent first  
   先显式建模“本次下载意图”，再决定是否启用拦截和如何匹配。

4. Non-target responses must remain transparent  
   未命中的响应必须原样继续，不允许被副作用污染。

5. Scoped lifecycle  
   拦截器必须具有清晰的 enable -> match/skip -> cleanup 生命周期。

6. One-shot by default  
   对于文件名增强，命中一次后应立即停用或至少不再改写后续响应。

7. No public API expansion  
   对业务脚本的正式入口仍然只有 `download_file()`。

## Proposed Architecture

### 1. Add a Dedicated Runtime Module

新增独立 runtime 模块：

- `templates/download_correlation.py`

职责只包含：

- 建模下载意图
- 基于点击前可见信息构造 matcher
- 管理 Fetch lifecycle
- 在命中目标响应时改写下载相关响应头

它不负责：

- 路径规范化
- 下载目录设置
- 最终落盘等待
- 业务脚本交互

### 2. Introduce an Explicit Download Intent Model

新增内部数据模型，例如：

```python
@dataclass(frozen=True)
class DownloadIntent:
    target_name: str
    rename_requested: bool
    href: str | None
    download_attr: str | None
```

作用：

- 表达“本次下载的目标文件名”
- 表达“这次是否真的需要 header rename 增强”
- 提供最基础的 request correlation 线索
- 固定“一次调用只对应一个目标下载”的内部边界

约束：

- 若未显式 `rename` 且也没有 `suffix` 导致文件名变化，则不必启用拦截增强
- `DownloadIntent` 只描述目标，不持有 driver/page/browser 这些运行态对象

### 3. Introduce a Download Matcher

新增匹配器对象，例如：

```python
@dataclass
class DownloadMatcher:
    href: str | None

    def matches_response(self, event: Mapping[str, Any]) -> bool:
        ...
```

匹配原则按“高置信优先、保守失败”：

1. 如果 response 已带 `Content-Disposition`，且值中包含 `attachment` 或 `filename=`
   则认为它具备下载语义
2. 如果 `DownloadIntent.href` 可用，则优先要求当前 response URL 与之匹配
   - 允许 query string / redirect 后的保守宽匹配，但不能宽到“同页面所有资源都算”
3. 如果拿不到足够强的信号，则视为“未知响应”，原样放行，不做改写

本次设计刻意不做复杂的多跳 request graph 关联；原则是宁可错过增强，也不误伤非目标响应。

### 4. Introduce a Scoped Fetch Interceptor

新增作用域对象，例如：

```python
class ScopedDownloadInterceptor:
    def __init__(self, owner, intent: DownloadIntent, matcher: DownloadMatcher): ...
    def enable(self) -> None: ...
    def cleanup(self) -> None: ...
    @property
    def matched(self) -> bool: ...
```

行为：

- `enable()` 注册 `Fetch.requestPaused` callback
- callback 对每个 response 做：
  - 若已命中过：原样 continue
  - 若未命中且 matcher 不匹配：原样 continue
  - 若匹配：改写 `Content-Disposition`，标记 `matched=True`，然后 continue
- `cleanup()` 负责 `Fetch.disable` 和 callback 清理

这层要保证：

- cleanup 幂等
- 非目标响应永远透明透传
- 就算 callback 内部异常，也不能让整个浏览器停在 paused 状态

### 5. Runtime Entry Function

在新模块中提供一个内部入口，例如：

```python
def prepare_download_interceptor(ele, target_name: str, *, rename: str | None, suffix: str | None):
    ...
```

返回：

- `None`：无需启用增强
- `ScopedDownloadInterceptor`：调用方负责 `enable()` 与 `cleanup()`

启用条件：

- 只有显式 `rename` 或 `suffix` 会导致“期望文件名不同于浏览器自然建议名”时，才启用
- 若 driver / callback / CDP 能力缺失，则返回 `None`
- 不因“增强不可用”而阻塞下载主流程

### 6. Integration Boundary in `download_file()`

`download_file()` 中保留的职责：

- 规范化目录路径
- 设置浏览器下载目录
- 触发点击
- 等待最终落盘
- 恢复浏览器原始下载目录

而以下逻辑迁入新模块：

- 是否启用 Fetch rename
- 如何匹配目标响应
- 如何改写 header
- 如何 one-shot 命中
- 如何清理 Fetch callback

## File Layout

本次架构设计涉及：

- Create: `templates/download_correlation.py`
- Modify: `templates/utils.py`
- Modify: `scripts/doctor.py`
- Modify: `scripts/test_helpers.py`
- Modify: `scripts/validate_bundle.py`

`download_correlation.py` 是 runtime-managed 代码，因此属于 source bundle 资产的一部分。
这意味着它不只要进入 validator，还必须：

- 被 `doctor.py` 同步到 `.dp/lib/`
- 被 `doctor.evaluate_workspace()` 视为 managed runtime 资产的一部分
- 在后续 contract closure 中进入 preflight prose 与 smoke checklist 的就绪条件

## Testing Changes

至少新增以下回归测试：

1. 非下载响应（如 `text/css`）进入 callback 时不应被写入 `Content-Disposition`
2. 带下载语义且 URL/线索匹配的响应会被改写目标文件名
3. 命中一次后后续 response 不再继续改写
4. 没有 rename/suffix 时，不启用 Fetch interceptor
5. interceptor cleanup 会清理 callback 且关闭 Fetch
6. interceptor 内部异常不会让 `download_file()` 停在“请求已 paused 但未 continue”的状态

## Acceptance Criteria

当以下条件全部满足时，本次设计视为完成：

- 下载改名增强不再污染非目标响应
- `download_file()` 不再直接维护 Fetch callback 细节
- 新模块只服务下载链路，不扩成通用框架
- 新模块只服务单目标下载，不承担批量编排
- 增强失败时仍可回退到最终落盘 rename
- 下载主流程对业务脚本的公开入口保持不变

## Rationale

当前问题的本质不是“缺一个过滤条件”，而是下载增强缺少独立的相关性层。

把这层拆出来的价值在于：

- `utils.py` 回到“helper orchestration”角色
- 下载响应识别变成可单测、可演进的内部模块
- 本轮能把误伤响应的风险真正收口，同时不把整个 runtime 抽象成过早泛化的网络框架
