# Connect API Consolidation Design

**Status:** Draft
**Date:** 2026-03-30
**Scope:** `dp` source bundle public runtime API

## Goal

在完成 provider contract 收口后，继续收口 `templates/connect.py` 的公开 API，
移除 legacy `connect_*` 兼容包装器，统一到 provider-first 的单一正式入口模型。

本次设计要解决的核心问题：

- `connect.py` 同时暴露 legacy 包装器和 provider-first 高层 API，公开入口重复
- `connect_browser()` 一类名称过于宽泛，无法体现其真实依赖的 provider 语义
- 当前实现把 legacy 包装器绑定到工作区 `default_provider`，导致同名调用在不同工作区行为不稳定
- 文档、spec、测试对 `connect_*` 的定位不一致，已经出现 contract 漂移

## Non-Goals

本次设计明确不做以下事项：

- 不引入新的 browser provider
- 不修改 provider contract 本身
- 不保留对历史脚本的向后兼容承诺
- 不新增第二套“默认 provider 便捷入口”命名

## Problem Statement

在 provider-first 改造完成后，`dp` 实际上已经形成了两套公开连接路径：

1. provider-first 正式路径
   - `get_default_browser_provider()`
   - `build_default_browser_profile()`
   - `start_profile_and_connect_browser()`
   - `start_profile_and_connect_web_page()`

2. legacy 包装路径
   - `connect_browser()`
   - `connect_browser_fresh_tab()`
   - `connect_web_page()`

这带来三个结构性问题：

### 1. Public Surface Duplication

两套入口都能“连接浏览器”，但参数形状、返回值和配置来源不同。
调用方需要先猜“哪套才是正式 contract”，这会持续制造文档和实现漂移。

### 2. Hidden Runtime State

如果 `connect_browser()` 跟随工作区 `default_provider`，则：

- 同一段代码在不同工作区行为不同
- 调用点无法从函数签名看出依赖了 provider 解析
- legacy 名称被提升成了新的正式默认入口

这违背了最小惊讶原则。

### 3. Signature Mismatch

provider-first 模型的正式输入是：

- `provider`
- `browser_profile`
- `base_url`
- `extra_params`

而 legacy 包装器只接受：

- `port`
- `mode`
- `url`

旧包装器天然装不下 provider-first 的完整语义。继续保留只会让共享 runtime
长期维护一层职责不清的 facade。

## Design Principles

本次收口遵循以下原则：

1. Single recommended path
   对同一种核心能力，只保留一条正式推荐入口。

2. Names must reveal semantics
   API 名称必须表达它依赖的是 provider-first 连接，还是显式 debug address 连接。

3. No hidden default-provider magic
   任何会读取工作区 `default_provider` 的高层入口，都应在名称和文档中明确体现其 provider-first 语义。

4. No compatibility theater
   既然本次明确不兼容历史，就不保留“看起来像旧接口、实际上已变成新语义”的过渡层。

5. Keep explicit low-level escape hatches
   显式 `debug_address` 连接仍然是合理的低层能力，但必须与 provider-first 高层入口严格分层。

## Proposed Runtime API

`templates/connect.py` 的公开 API 分成三层：

### 1. Provider Discovery / Resolution

保留：

- `list_browser_providers()`
- `load_browser_provider(name)`
- `get_default_browser_provider()`
- `build_default_browser_profile(provider, port=None)`

职责：

- 枚举 provider
- 加载 provider
- 解析工作区默认 provider
- 为默认 provider 构造最小 profile

这些函数只负责“决定用谁、用什么参数”，不直接返回 page。

### 2. Provider-First High-Level Entry

保留并作为唯一正式高层入口：

- `start_browser_profile(...)`
- `get_debug_address(provider, start_result)`
- `get_provider_metadata(provider, start_result)`
- `build_launch_info(...)`
- `start_profile_and_connect_browser(...)`
- `start_profile_and_connect_web_page(...)`

职责：

- 启动或定位 provider profile
- 规范化 provider 启动结果
- 返回 `launch_info + page`

这组 API 是 workflow、smoke、文档模板、mode-selection 的唯一正式主路径。

### 3. Explicit Address Attachment

保留：

- `build_chromium_options(address)`
- `connect_browser_by_address(address)`
- `connect_browser_by_address_fresh_tab(address, url="about:blank")`
- `connect_web_page_by_address(address, mode="d")`
- `connect_browser_from_start_result(...)`
- `connect_browser_from_start_result_fresh_tab(...)`
- `connect_web_page_from_start_result(...)`

职责：

- 针对“调用方已经拿到明确 debug address”的场景，提供直接接管能力
- 这些函数不读取工作区 `default_provider`
- 这些函数不承担 provider 解析职责

## Removed API

从公开 runtime API 中移除：

- `connect_browser(port: str | None = None)`
- `connect_browser_fresh_tab(port: str | None = None, url: str = "about:blank")`
- `connect_web_page(port: str | None = None, mode: str = "d")`

删除原因：

- 与 provider-first 高层入口语义重复
- 无法在名称上表达 provider 语义
- 继续保留会制造“第二套默认入口”
- 不兼容历史已是本次明确决策，不再保留 facade

## Canonical Usage Patterns

### 1. Default Provider Browser Task

```python
provider = get_default_browser_provider()
browser_profile = build_default_browser_profile(provider, parse_port())
launch_info, page = start_profile_and_connect_browser(provider, browser_profile)
```

### 2. Default Provider WebPage Task

```python
provider = get_default_browser_provider()
browser_profile = build_default_browser_profile(provider, parse_port())
launch_info, page = start_profile_and_connect_web_page(
    provider,
    browser_profile,
    mode="d",
)
```

### 3. Explicit Address Attachment

```python
page = connect_browser_by_address("127.0.0.1:9222")
```

### 4. Fresh Tab with Provider-First

```python
launch_info, page = start_profile_and_connect_browser(
    provider,
    browser_profile,
    fresh_tab=True,
    url="about:blank",
)
```

`fresh tab` 不再有单独的 legacy 包装入口。

## Contract Updates

### SKILL.md

需要明确：

- 推荐脚本连接方式只有 provider-first 正式入口
- `connect_*` 不再作为公开推荐函数出现
- 如果业务依赖 browser provider，应优先复用
  `get_default_browser_provider()` / `build_default_browser_profile()` /
  `start_profile_and_connect_browser()`

### references/workflows.md

需要保证：

- 所有模板只展示 provider-first 入口
- 不再通过对比或说明文字暗示 `connect_browser()` / `connect_web_page()` 仍是合法推荐路径
- `fresh tab` 示例统一改为 `start_profile_and_connect_browser(..., fresh_tab=True)`

### references/mode-selection.md

需要保证：

- ChromiumPage / WebPage 示例只展示 provider-first 入口
- 不再把 `connect_web_page()` 当作概念锚点

### evals/smoke-checklist.md

需要保证：

- 手工验收不再引用 `connect_browser_fresh_tab()`
- `fresh tab` 验收改为针对 provider-first 正式入口的 `fresh_tab=True`

## Testing Changes

测试需要从“legacy 包装器仍可工作”切换为“公开 API 已收口”：

1. 删除 `connect_browser()` / `connect_web_page()` / `connect_browser_fresh_tab()` 相关单测
2. 新增或调整 provider-first 正式入口测试：
   - `start_profile_and_connect_browser(..., fresh_tab=True)` 正确绑定 tab_id
   - `start_profile_and_connect_browser()` 读取明确 provider，不依赖 legacy facade
   - `start_profile_and_connect_web_page()` 保持现有模式语义
3. 文档/验收测试不再引用 removed API
4. 若有引用 removed API 的 smoke/manual checklist，应视为 contract 漂移并修复

## Migration Rule

从本设计起：

- source bundle 不再为历史脚本兼容负责
- 任何仍依赖 removed API 的脚本，都需要自行迁移到 provider-first 正式入口
- 本次迁移不提供 runtime shim、不提供 deprecation warning 过渡期

## Acceptance Criteria

当以下条件全部满足时，本次 API 收口视为完成：

- `templates/connect.py` 中不再存在 `connect_browser()` / `connect_browser_fresh_tab()` / `connect_web_page()`
- workflow、mode-selection、smoke 文档只展示 provider-first 正式入口
- `fresh tab` 的公开示例与验收全部改为 `start_profile_and_connect_browser(..., fresh_tab=True)`
- 单元测试不再依赖 removed API
- `SKILL.md`、workflow 文档、验收文档与实现表述一致
- `connect.py` 的公开层次可清晰分为 provider discovery、provider-first high-level、explicit address attachment 三层

## Rationale

这次改动不是“删除几个旧函数”，而是把 `dp` runtime 的公开心智模型收敛成一句话：

> 浏览器类任务默认走 provider-first；如果调用方已经拿到明确 debug address，则走 by-address 低层入口。

除此之外，不再保留第三套 facade。
