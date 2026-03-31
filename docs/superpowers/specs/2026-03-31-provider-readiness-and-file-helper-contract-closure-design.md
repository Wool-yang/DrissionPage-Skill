# Provider Readiness and File Helper Contract Closure Design

**Status:** Draft
**Date:** 2026-03-31
**Scope:** `dp` source bundle workspace readiness / top-level SKILL contract

## Goal

补齐当前内层 source bundle 里仍残留的两处 public contract 缺口，让 `doctor.py`、`smoke.py`、`SKILL.md`、`evals/smoke-checklist.md` 与现有 runtime 语义重新闭环：

- `default_provider` 名称合法但对应 provider 文件缺失时，当前 scripts-side readiness 仍可能误判为 ready
- `upload_file()` / `download_file()` 已实现 provider-aware fail-fast，但 top-level `SKILL.md` 仍未把 `remote` provider 的失败边界说透

## Non-Goals

本次设计明确不做以下事项：

- 不修改 `templates/connect.py` 的公开 provider-first API
- 不引入新的 provider 注册或自动发现机制
- 不修改 `templates/utils.py` 的现有 file helper 行为
- 不扩展到 provider 命名冲突检测、provider metadata schema 新字段等额外议题

## Problem Statement

### 1. Default Provider Readiness Is Still Weaker Than Runtime Reality

当前 `SKILL.md` 与 `doctor.evaluate_workspace()` 已经检查：

- `default_provider` 是否存在且合法
- runtime-managed `cdp-port.py` 是否存在

但这还不等于“当前默认 provider 真的可用”。

如果 `.dp/config.json` 中显式写入：

```json
{"default_provider": "adspower"}
```

而 `.dp/providers/adspower.py` 不存在，那么：

- `doctor.py --check` 目前可能不报错
- `smoke.py` 通过复用 doctor 结果，同样可能放行
- 第一个真正调用 `load_browser_provider("adspower")` 的浏览器任务才会失败

这违反了已经确立的 truthful preflight contract：文档与 scripts-side readiness 不应把 runtime 实际还依赖的 provider 文件遗漏掉。

### 2. Missing Custom Provider File Is Not a Repairable State

自定义 provider 文件不是 runtime-managed 资产。

因此当默认 provider 指向一个不存在的自定义实现时，doctor 不应：

- 猜测式改写到别的 provider
- 继续写 `state.json`
- 打印“工作空间就绪”

它应把这类状态视为显式配置错误：需要用户或客户端提供对应的 `.dp/providers/<name>.py`，或改回已有 provider。

### 3. File Helper Fail-Fast Boundary Is Buried Below Top-Level SKILL

`templates/utils.py` 已经实现：

- `launch_info.provider_metadata.file_access_mode == "remote"` 时直接报错

`references/provider-contract.md` 与 `references/workflows.md` 也已经表达了这个边界。

但 top-level `SKILL.md` 仍只写成“提供 `launch_info` 时会做更安全的本地文件访问判断”，这会让宿主或读者误把 contract 理解成：

- “传 `launch_info` 只是更稳”

而不是：

- “某些 provider 明确不具备本地文件访问能力，helper 必须 fail fast”

## Design Principles

1. Truthful readiness must include the selected provider implementation  
   只要 runtime 真正依赖当前默认 provider 的实现文件，scripts-side readiness 就必须把它纳入判断。

2. Conservative repair for custom provider absence  
   缺失的自定义 provider 文件属于显式配置问题，不属于 doctor 可自动发明的工作区资产。

3. Top-level SKILL must carry hard boundaries  
   关键失败边界不能只埋在 reference 文档里；`SKILL.md` 必须足够准确，避免宿主在顶层就做错分支。

4. Validator should guard reviewed failure modes  
   既然这两个缺口已经在 review 中出现，就应把它们固化进 validator/tests，避免再次回归。

## Proposed Changes

### 1. Extend Doctor Readiness with Selected Provider Presence

在 `scripts/doctor.py` 中加入 scripts-side helper，用于判断一个规范化 provider 名是否在 `.dp/providers/` 下拥有实现文件。

规则：

- 公开 provider 名仍使用 kebab-case
- 文件存在性检查与 runtime loader 保持一致，接受：
  - `.dp/providers/<name>.py`
  - `.dp/providers/<name_with_underscores>.py`
- `cdp-port` 继续由现有 managed asset 检查覆盖

`evaluate_workspace()` 新增规则：

- 若 `default_provider == "cdp-port"`，沿用现有 `cdp-port.py` 检查
- 若 `default_provider != "cdp-port"` 且对应 provider 文件不存在，加入 issue

### 2. Make `init()` Fail Fast on Missing Selected Provider

`_write_default_config()` 之后、写 `state.json` 之前，`init()` 需要再次校验当前选中的默认 provider 是否有实现文件。

若缺失：

- 打印明确错误
- 返回 `False`
- 不写新的 `state.json`
- 不打印“工作空间就绪”

这样 `doctor.py` 的 repair 语义才与“自定义 provider 文件是用户/客户端职责”一致。

### 3. Strengthen Preflight Prose for Selected Provider Presence

`SKILL.md` 与 `evals/smoke-checklist.md` 的 preflight prose 统一补上：

- `default_provider` 合法只是第一层
- 若当前默认 provider 不是 `cdp-port`，则其对应的 `.dp/providers/<name>.py`（或等价 snake_case 文件）也必须存在，才算可跳过 doctor

同时明确声明：

- 若默认 provider 指向不存在的自定义 provider 文件，属于显式配置错误
- doctor 不会自动发明该 provider
- 需要用户或客户端提供实现，或修正配置

### 4. Lift File Helper Fail-Fast Boundary Into `SKILL.md`

在 `SKILL.md` 的 upload/download 说明中，把当前表达：

> 提供 `launch_info` 时会做更安全的本地文件访问判断

升级为：

- helper 默认处理跨平台路径
- 若提供 `launch_info`，会结合 provider hints 判断本地文件访问能力
- 若 provider 明确声明 `file_access_mode == "remote"` 或等价不支持状态，`upload_file()` / `download_file()` 必须直接报错

目标不是重复 reference 文档的全部细节，而是把“可直接失败”这一条顶层边界写清楚。

### 5. Harden Validator Around Both Reviewed Gaps

`scripts/validate_bundle.py::validate_rule_markers()` 新增两类检查：

1. **selected default provider presence boundary**
   Preflight 章节必须表达：
   - 当前默认 provider 若不是 `cdp-port`
   - 则需要对应 provider 文件/实现存在
   - 缺失时属于配置错误，非自动修复路径

2. **file helper remote fail-fast boundary**
   upload/download 所在章节必须表达：
   - `launch_info`
   - provider hints / file access
   - `remote` 或“不支持本地文件访问”
   - 直接报错 / fail fast

validator 不要求逐字匹配，但要拦住把硬边界弱化成“更安全”这种近似说法。

## Testing Changes

至少新增以下回归测试：

1. `doctor.evaluate_workspace()` 在默认 provider 指向缺失的自定义 provider 文件时返回 issue
2. `doctor.init()` 在默认 provider 指向缺失的自定义 provider 文件时返回 `False` 且不写 state
3. `validate_rule_markers()` 在 preflight 未声明“当前默认 provider 对应实现文件必须存在”时失败
4. `validate_rule_markers()` 在 upload/download prose 未声明 remote fail-fast 时失败
5. 新的等价 prose 仍能通过，避免 validator 过拟合

## Documentation Changes

需要同步更新：

- `SKILL.md`
- `evals/smoke-checklist.md`
- 对应 spec / implementation plan

由于本次会修改 `SKILL.md` 与 scripts-side contract，需 bump `SKILL.md` 中的 `bundle-version`；
`runtime-lib-version` 保持不变，因为 `.dp/lib/*` runtime 文件未修改。

## Acceptance Criteria

当以下条件全部满足时，本次设计视为完成：

- `doctor.py --check` 不再把“默认 provider 文件缺失”的工作区视为 ready
- `doctor.py` 在该场景下不会继续写 state 或宣称 workspace ready
- `smoke.py` 通过复用 doctor 结果，自动继承这一失败边界
- `SKILL.md` 与 `evals/smoke-checklist.md` 明确写出默认 provider 实现存在性要求
- `SKILL.md` 明确写出 remote file helper fail-fast 边界
- validator/tests 能阻止这两类 prose / readiness 漂移再次回归

## Rationale

这次补丁不是扩设计，而是把已经存在的内层语义真正说清楚并测清楚：

- provider-first 模型下，“默认 provider 的实现文件存在”本来就是 runtime 真实依赖
- provider-aware file helper 模型下，“remote provider 直接失败”本来就是 runtime 已有行为

如果 scripts-side readiness 与 top-level SKILL 不把这两点说透，宿主仍会在最关键的分支点做出错误判断。
