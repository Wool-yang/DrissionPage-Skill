# Provider Contract Closure Design

**Status:** Draft
**Date:** 2026-03-30
**Scope:** `dp` source bundle public contract

## Goal

收口 `dp` 的 browser provider 机制，把当前“方向正确但 contract 仍偏松”的实现整理为可长期维护的公开接口。

本次设计要解决的核心问题：

- provider 的正式加载路径过多，主路径不够明确
- provider 命名规则在“列出”和“加载”之间不一致
- provider 返回值 contract 过宽，raw 启动结果容易被上层误当成稳定接口或直接落盘
- 文档只说明“支持 provider”，还没有把工作区 provider contract 规范化

## Non-Goals

本次设计明确不做以下事项：

- 不新增任何新的 browser provider
- 不引入 provider 注册中心、插件市场、远程下载或自动发现机制
- 不把宿主客户端的私有安装流程写成公开 contract
- 不在 source bundle 中记录任何本地测试仓库、机器路径、私有脚本、私有运行时状态

## Public Boundary

`dp` 开源仓库只描述公开 source bundle 与通用工作区 contract。

允许公开描述的内容：

- `.dp/providers/<name>.py` 这一类工作区相对路径
- provider 文件的接口、命名规则、错误处理和输出约束
- runtime 如何从工作区加载 provider 并接管返回的调试地址

禁止进入开源仓库的内容：

- 任意本地测试仓库名称、目录结构、绝对路径
- 任意宿主客户端的私有目录约定、安装副本位置或注入细节
- 任意本机运行产物、浏览器 profile、临时输出、调试文件

这条边界是长期规则，而不只是本次改造的临时要求。

## Current Problems

### 1. Provider Source Is Not Fully Closed

当前 runtime 同时支持：

- 工作区 `.dp/providers/<name>.py`
- `DP_PROVIDER_FILE[_<NAME>]`
- `DP_PROVIDER_MODULE[_<NAME>]`

这会带来三个问题：

- 公开 contract 有多条主路径，文档和测试难以收口
- provider 的来源优先级会变成长期维护负担
- 宿主客户端的私有注入手段被暴露成 source bundle 的长期接口

### 2. Naming Contract Is Inconsistent

当前实现中，provider 列表展示会把下划线文件名转换成 kebab-case，但加载逻辑按规范名拼接文件路径时只查单一路径。

结果是：

- `anti_detect.py` 可能被展示为 `anti-detect`
- 用户按展示名加载时，不一定能命中实际文件

这属于公开 contract 级别的漏洞。

### 3. Return Contract Is Too Loose

当前高层 helper 把 `start_profile()` 的返回结果作为公开返回值暴露给调用方，同时要求该返回值必须是 `dict`。

这存在两个问题：

- 对 runtime 来说，真正需要的最小能力只是“能从结果里解析出 debug address”，而不是“必须是 dict”
- 对工作流来说，raw `start_result` 容易被误用为稳定结构，进一步被直接写入输出目录

### 4. Documentation Is Not Yet a Formal Workspace Contract

现有文档已经表达了“provider 可注入”的方向，但还没有正式规定：

- provider 文件的唯一正式位置
- 必需函数与可选函数
- 参数签名
- 命名规则
- 错误处理规范
- 持久化边界
- 最小模板

## Design Principles

本次收口遵循以下原则：

1. 单一路径优先
   provider 只保留一条正式主路径，避免长期并存多套来源。

2. 工作区优先
   provider 是工作区 contract，不是 runtime 内置实现，也不是宿主私有注入细节。

3. Provider-neutral
   通用 runtime 和通用工作流只知道 provider 名与抽象参数，不知道具体 provider 默认 URL 或私有 API 细节。

4. Opaque start result
   provider 启动结果属于 provider 私有内部数据；runtime 只消费它，不把它提升为公开稳定模型。

5. Safe persistence
   输出目录和工作流状态只能保存规范化、安全、可预期的字段，不能直接写 raw provider response。

## Proposed Architecture

### 1. Single Official Provider Path

唯一正式 provider 路径定义为：

```text
.dp/providers/<name>.py
```

这条路径是唯一公开、推荐、长期支持的 provider 接入方式。

宿主客户端如果需要提供 provider，实现方式应当是：

- 安装 skill
- 初始化工作区 `.dp/`
- 在 `.dp/providers/` 下创建或更新 provider 文件

runtime 不再支持通过环境变量直接注入 provider 文件或模块。

### 2. Remove Environment Injection

以下能力从公开 contract 中移除：

- `DP_PROVIDER_FILE`
- `DP_PROVIDER_FILE_<NAME>`
- `DP_PROVIDER_MODULE`
- `DP_PROVIDER_MODULE_<NAME>`

删除理由：

- 它们不是工作区 contract 的必要组成部分
- 它们会把宿主实现细节暴露成长期公开接口
- 它们与工作区 provider 文件形成并行来源，增加排障和维护成本

删除后的公开模型更简单：

- provider 模式：从 `.dp/providers/` 加载 provider
- 非 provider 模式：直接连接普通 CDP 浏览器

两者并列存在，但不互为 fallback。

### 3. Provider Naming Contract

公开 provider 名统一使用 kebab-case。

示例：

- `adspower`
- `anti-detect`
- `custom-browser`

工作区文件名兼容两种形式：

- `anti-detect.py`
- `anti_detect.py`

但无论文件名采用哪一种形式，公开名始终是：

```text
anti-detect
```

runtime 需要满足：

- `list_browser_providers()` 返回 kebab-case 名称
- `load_browser_provider("anti-detect")` 同时尝试 kebab-case 与 snake_case 文件名
- 如果两个文件归一化后映射到同一个公开名，直接报错，不做隐式覆盖

冲突示例：

```text
.dp/providers/anti-detect.py
.dp/providers/anti_detect.py
```

这两者指向同一个公开名，属于非法状态，应抛出明确异常。

### 4. Provider Contract

provider 文件的最小 contract 如下：

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

contract 要求：

- `start_profile()` 负责启动目标 browser profile，并返回 provider 私有结果对象
- `extract_debug_address()` 必须能从该结果对象中提取非空调试地址
- `extract_metadata()` 如果存在，返回可安全持久化的 provider 元数据；如果不存在，上层视为无 metadata

明确不要求：

- `start_profile()` 返回值必须是 `dict`
- `start_profile()` 返回值必须可 JSON 序列化
- `start_profile()` 返回值结构在 provider 之间统一

### 5. Opaque Start Result

`start_result` 被正式定义为 opaque provider result。

runtime 对它只做两件事：

- 在内存中把它传给 `extract_debug_address()`
- 如果 provider 实现了 `extract_metadata()`，再把它传给 `extract_metadata()`

除此之外，runtime 和工作流都不应依赖其内部字段。

这意味着调用方不应再假设以下内容稳定存在：

- `start_result["data"]`
- `start_result["debug_address"]`
- `start_result["profile"]`
- `start_result["base_url"]`
- `start_result["extra_params"]`

这些都只能视为具体 provider 的私有实现细节。

### 6. Normalized Launch Info

高层 helper 不再把 raw `start_result` 作为公开长期接口返回给工作流层。

高层公开模型应收敛为规范化后的 launch info：

```python
{
    "provider": "...",
    "provider_url": "...",         # 可为空
    "browser_profile": {...},      # 规范化后的 profile 参数
    "debug_address": "127.0.0.1:9222",
    "provider_metadata": {...},    # 可为空
}
```

约束如下：

- `provider` 为公开名，使用 kebab-case
- `provider_url` 仅表示工作流侧传入或规范化后的 provider 地址；默认允许为空
- `browser_profile` 仅表示工作流提交给 provider 的抽象 profile 参数
- `debug_address` 必须是最终连接用的调试地址
- `provider_metadata` 只来自显式提取，不能默认回填整个启动结果

raw `start_result` 可以在 runtime 内部短暂存在，但不能成为输出目录或调用方状态管理的默认载体。

### 7. Provider-Neutral Rule

通用层保持 provider-neutral，具体含义如下：

- 通用 runtime 可以知道 provider 名
- 通用 runtime 可以接收抽象的 `base_url` / `provider_url`
- 通用 runtime 不定义任何具体 provider 的默认地址
- 具体 provider 的默认 base URL 必须只存在于 provider 文件内部

例如：

- `provider="adspower"` 可以是调用方默认选择
- 但 `provider_url="http://localhost:50325"` 不能作为通用层默认值存在

这条规则保证工作流只知道“选了哪个 provider”，而不耦合 provider 私有实现细节。

### 8. Persistence Rule

工作流输出、状态文件和执行结果中禁止直接落 raw `start_result`。

允许保存的字段仅限于规范化后的 launch info，以及业务脚本自己的站点输出。

以下内容禁止直接写入输出目录：

- provider 原始 API 响应
- 启动结果中的复杂对象
- provider 返回但未审查的敏感字段
- provider 私有调试信息

如果某个 provider 需要暴露额外信息，必须通过 `extract_metadata()` 主动筛选后再进入 `provider_metadata`。

## Runtime Changes

### Loader

runtime 需要改为：

- 仅扫描 `.dp/providers/`
- 加载时支持 kebab-case / snake_case 文件名兼容
- 检测并拒绝归一化命名冲突
- 错误提示只指向工作区 provider 路径，不再提到环境变量注入

### Validation

provider 校验逻辑需要满足：

- `start_profile` 必须存在且可调用
- `extract_debug_address` 必须存在且可调用
- `extract_metadata` 可选

对 `start_profile()` 返回值的校验应从“必须为 dict”改为：

- 调用 `extract_debug_address(start_result)`
- 若返回空字符串、非字符串或无效值，则报错

### High-Level Helpers

高层 helper 的公开返回值需要同步收口。

推荐方向：

- 保留底层 API，可返回 opaque `start_result` 给 runtime 内部链路使用
- 对工作流和公开模板暴露的高层 API 改为返回 `launch_info + page`

如果出于兼容性需要保留旧函数，也应：

- 明确标记为兼容层
- 文档不再推荐
- 新模板全部切到规范化 launch info

## Documentation Changes

内层仓库文档需要做以下调整：

### SKILL.md

- 删除环境变量注入说明
- 明确 provider 唯一正式路径为 `.dp/providers/<name>.py`
- 明确 provider 模式与普通 CDP 直连模式并列
- 明确 provider 结果为 opaque，不得直接落盘

### references/workflows.md

- provider 示例改为基于工作区 provider 文件
- 不再提及 `DP_PROVIDER_FILE` / `DP_PROVIDER_MODULE`
- 示例应使用规范化 launch info，而不是鼓励依赖 raw `start_result`

### README / README_EN

- 保留“provider 可注入”的方向描述，但用词应改为“工作区 provider”
- 不描述宿主私有注入方式

### New Provider Contract Reference

新增一份正式文档，建议路径：

```text
references/provider-contract.md
```

内容至少包括：

- `.dp/providers/<name>.py` 目录约定
- 命名规则
- 最小 contract
- 可选 `extract_metadata()`
- provider-neutral 规则
- 持久化边界
- 最小 provider 模板

## Testing Changes

测试需要从“证明当前实现能跑”升级为“保护收口后的公开 contract”。

至少新增或调整以下测试：

1. 工作区 provider 可枚举
2. kebab-case 文件可加载
3. snake_case 文件可被 kebab-case 名称加载
4. kebab-case 与 snake_case 同名冲突时报错
5. 缺少 `extract_debug_address()` 时报错
6. `start_profile()` 返回非 dict 但 `extract_debug_address()` 可解析时仍然可用
7. 高层返回值不再鼓励依赖 raw `start_result`
8. 删除所有 env 注入相关测试

## Migration Strategy

本次改造按以下顺序执行：

1. 先修 loader 与命名规则
2. 再删除 env 注入路径
3. 再把返回 contract 改成 opaque result + normalized launch info
4. 最后补文档、模板和回归测试

在以上步骤完成前，不建议继续新增 provider。

## Open Questions Resolved by This Design

### Should environment injection remain supported?

结论：不保留。

理由：

- 它不是工作区 contract 的必要组成
- 它暴露宿主实现细节
- 它让 provider 来源变成长期多路径

### Should provider returns remain raw dicts?

结论：不保留这种要求。

理由：

- runtime 只需要解析 debug address
- 强制 dict 只会把 provider 私有结构误抬升为公开模型

### Should generic config define AdsPower defaults?

结论：不允许。

理由：

- 这会破坏 provider-neutral 设计
- 默认 base URL 必须属于具体 provider 自己

## Acceptance Criteria

当以下条件全部满足时，本次 contract 收口视为完成：

- runtime 只从 `.dp/providers/` 加载 provider
- 不再存在 `DP_PROVIDER_FILE` / `DP_PROVIDER_MODULE` 相关公开逻辑
- provider 公开名统一为 kebab-case
- snake_case 与 kebab-case 文件名兼容加载，但冲突会明确报错
- `start_profile()` 返回值不再要求必须是 dict
- 工作流和公开模板不再依赖 raw `start_result`
- 输出目录不再直接保存 raw provider response
- `SKILL.md`、README、workflow 文档和 provider contract 文档表述一致
- 开源仓库文档中不出现任何本地测试仓库信息

## Follow-Up Plan

本设计文档批准后，应进入实现计划阶段，拆解为：

- loader / naming
- return contract
- documentation / template
- test migration

每个阶段都应有独立验证与回归测试，不做一次性大改后再统一排障。
