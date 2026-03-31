# Workspace Contract Unification Design

**Status:** Draft
**Date:** 2026-03-31
**Scope:** `dp` source bundle workspace readiness / provider resolution contract

## Goal

把 `dp` 当前分散在 `doctor.py`、`smoke.py`、`SKILL.md`、`smoke-checklist.md`
里的“工作区是否就绪”判定收口成单一 contract，避免同一个工作区在不同入口上得出不同结论。

本次设计要解决的核心问题：

- `doctor.py`、`smoke.py`、文档对 preflight / readiness 的定义不一致
- `smoke.py` 不校验 `state.json` 版本，无法阻止旧 `.dp/lib` 在 bundle 升级后继续被验收
- `default_provider` 的规范化与修复逻辑分散，`smoke.py` 与 runtime 对同一配置可能得出不同语义
- `doctor.py` 在 runtime-managed provider 模板缺失时仍可能写 state 并报告“工作空间就绪”
- `validate_bundle.py` 只校验了部分 prose token，没有把新的 preflight contract 硬化成可回归约束

## Non-Goals

本次设计明确不做以下事项：

- 不修改 `templates/connect.py` 的公开 provider-first API
- 不新增新的 browser provider
- 不把 `doctor.py` 改造成完整的 runtime 公共库
- 不重构整个 `dp` 安装/发布流程
- 不为错误的显式 provider 名自动猜测或发明修复规则

## Problem Statement

### 1. Readiness Logic Is Duplicated

当前 readiness 判断至少存在四份语义：

- `SKILL.md` 的 preflight 章节
- `evals/smoke-checklist.md`
- `scripts/doctor.py::check()`
- `scripts/smoke.py::_check_workspace()`

它们目前并不完全一致。最严重的例子是：

- 文档要求 `state.json` 版本与当前 skill 一致才可跳过 doctor
- `smoke.py::_check_workspace()` 却完全不检查 `state.json`

这会导致 smoke 在旧 workspace 上继续通过，从而失去“验证当前 bundle 已生效”的意义。

### 2. Default Provider Semantics Are Not Closed

当前 `default_provider` 的规则存在三层分裂：

- 文档要求它是非空字符串
- `smoke.py` 只做 `strip()`，不做 kebab-case 规范化
- `templates/connect.py` 会做完整规范化

结果是同一个配置值（例如 `" CDP-PORT "`）在 smoke 与 runtime 中可能触发不同分支。

### 3. Doctor Repair Semantics Are Not Truthful

`doctor.py` 目前会报告：

- 缺少 `.dp/providers/cdp-port.py` 是 preflight 失败
- 缺少 `default_provider` 是 preflight 失败

但对应的修复逻辑并不完整：

- `_write_default_config()` 对空字符串 `default_provider` 无法修复
- managed provider 模板缺失时，`init()` 会静默跳过复制并继续成功

这意味着 doctor 可能在没有真正完成修复时仍然宣称 workspace healthy。

### 4. Validator Does Not Fully Guard the New Contract

当前 `validate_bundle.py` 已开始检查新的 provider-first prose，
但还没有把 preflight contract 的关键资产和字段写成硬校验：

- `.dp/config.json`
- `.dp/providers/cdp-port.py`
- `.dp/state.json`
- `default_provider`
- `runtime_lib_version`
- `bundle_version`

如果后续文档再次漂移，现有 validator 不一定能及时拦住。

## Design Principles

1. Single source of truth
   工作区 readiness 的正式判定只允许在一个地方实现，其它入口只能复用，不再复制规则。

2. Truthful repair
   doctor 只能在工作区真的被修好后才写 state 并报告成功；缺关键源资产时必须失败。

3. Canonical provider semantics
   scripts-side 对 `default_provider` 的解释必须与 runtime 保持同一语义，至少在 trim / lowercase / kebab-case 合法性上完全一致。

4. Conservative repair
   缺失、空值、明显未初始化状态可以自动修复；显式但非法的 provider 名属于配置错误，不做猜测式修复。

5. Bundle-verifiable contract
   只要某条规则出现在公开文档中，就应该尽量有 validator 或测试覆盖，防止 prose 漂移。

6. Minimal change surface
   本次只收口 workspace contract，不借机重做 runtime API 或安装架构。

## Proposed Architecture

### 1. Doctor Becomes the Scripts-Side Readiness Authority

在 `scripts/doctor.py` 中新增一个结构化 workspace 评估入口，例如：

```python
def evaluate_workspace(workspace: Path = WORKSPACE) -> dict[str, Any]:
    return {
        "issues": [...],
        "default_provider": "cdp-port",
        "runtime_lib_version": "...",
        "bundle_version": "...",
        "state_runtime_lib_version": "...",
        "state_bundle_version": "...",
    }
```

约束：

- `check()` 退化为 `evaluate_workspace(... )["issues"]`
- `evaluate_workspace()` 必须覆盖：
  - `.dp/.venv/` 可执行性
  - `.dp/lib/*`
  - `.dp/providers/cdp-port.py`
  - `.dp/config.json`
  - `default_provider`
  - `.dp/state.json`
  - `runtime_lib_version`
  - `bundle_version`
- `smoke.py` 不再自写第二套 readiness 规则，而是复用这个结构化结果

### 2. Canonical Scripts-Side Provider Normalization

在 `doctor.py` 中增加 scripts-side canonical helper，例如：

```python
def normalize_provider_name(raw: str) -> str:
    ...
```

规则与 runtime 保持一致：

- `strip()`
- `lower()`
- 公开名只接受 kebab-case：`[a-z0-9-]+`

配套行为：

- `" CDP-PORT "` 规范化后是 `"cdp-port"`
- `""`、全空白、缺失值视为未初始化
- `"ads power"`、`"adspower!"` 这类无法无损规范化的值视为显式非法配置

### 3. Explicit Config Repair Policy

`doctor.py` 对 `.dp/config.json` 的处理规则收口如下：

- 文件缺失、JSON 损坏、根对象不是 `dict`：
  重建为 `{"default_provider": "cdp-port"}`
- `default_provider` 缺失、非字符串、空字符串、纯空白：
  修复为 `"cdp-port"`
- `default_provider` 只存在大小写/首尾空白差异：
  重写为规范化后的 kebab-case 名称
- `default_provider` 为非空但非法名称：
  `check()` 报错，`init()` 失败，不做猜测式修复

理由：

- 对“未初始化”状态应保证 doctor 可自愈
- 对“有明确意图但值非法”的状态应显式暴露问题，而不是替用户改写到别的 provider

### 4. Fail-Fast Managed Asset Sync

`doctor.py::init()` 在开始同步 workspace 前，必须先验证 source bundle 中的 managed 资产存在：

- `templates/connect.py`
- `templates/output.py`
- `templates/utils.py`
- `templates/_dp_compat.py`
- `templates/providers/cdp-port.py`

约束：

- 任一文件缺失都直接失败
- 失败时不写新的 `state.json`
- 失败时不打印“工作空间就绪”
- 不允许“缺 managed provider 模板但继续成功”的半初始化状态

### 5. Smoke Reuses Doctor Contract

`scripts/smoke.py` 做两层分工：

1. readiness / version / provider config 由 `doctor.evaluate_workspace()` 判定
2. smoke 自己只补充“浏览器是否可连接”这一层运行时检查

因此：

- `_check_workspace()` 只返回 `doctor.evaluate_workspace()` 的首个 issue
- `_get_default_provider()` 只消费 doctor 返回的规范化 provider
- `default_provider == "cdp-port"` 时，`--port <port>` 必须显式传入
- 不再允许 smoke 和 runtime 对同一 `default_provider` 得出不同解释

### 6. Validator Hardening

`scripts/validate_bundle.py` 需要把新的 preflight contract 写成硬检查。

至少新增以下要求：

- `SKILL.md` 的 Preflight 章节必须同时提到：
  - `.dp/config.json`
  - `.dp/providers/cdp-port.py`
  - `.dp/state.json`
  - `default_provider`
  - `runtime_lib_version`
  - `bundle_version`
- 现有“章节内 token”检查保持同类策略，避免 token 散落在别处伪装通过

如果需要，也可拆成新的 `validate_preflight_contract_markers()`，但目标是不让 prose contract 再次失守。

## Testing Changes

至少新增或调整以下测试：

1. `doctor.init()` 遇到空字符串 `default_provider` 时会修复为 `cdp-port`
2. `doctor.init()` 遇到大小写/空白变体时会写回规范化 provider
3. `doctor.init()` 遇到缺失 managed provider 模板时返回 `False` 且不写 state
4. `smoke._check_workspace()` 对旧 `state.json` 版本返回错误
5. `smoke` 读取 `" CDP-PORT "` 时，主流程仍要求显式 `--port`
6. validator 在 preflight 章节缺失 `.dp/config.json` / `default_provider` / `.dp/providers/cdp-port.py` / `.dp/state.json` / 版本字段时失败

## Documentation Changes

需要同步更新：

- `SKILL.md`
- `evals/smoke-checklist.md`
- 如有必要，`README.md` / `README_EN.md`

重点不是增加新概念，而是让三处文档与 `doctor.evaluate_workspace()` 表达完全一致。

## Acceptance Criteria

当以下条件全部满足时，本次收口视为完成：

- `smoke.py` 不再维护独立的 workspace readiness 语义
- stale `state.json` 会阻止 smoke 继续验收当前 bundle
- `default_provider` 在 doctor / smoke 中使用同一套规范化规则
- doctor 能修复“未初始化 config”，但会拒绝“显式非法 provider 名”
- 缺少 `templates/providers/cdp-port.py` 时，doctor init 失败且不写新 state
- validator 能阻止 preflight prose 再次遗漏 `.dp/config.json`、`.dp/providers/cdp-port.py`、`.dp/state.json` 与版本字段

## Rationale

这次改动的本质不是“补几个条件判断”，而是把 `dp` 的 scripts-side contract 收敛成一句话：

> 工作区 readiness 由 doctor 单点判定；smoke 与文档只复用这套结论，不再各自解释一遍。

只有这样，`bundle-version` / `runtime-lib-version` / `default_provider` / managed provider 这些字段才真正具有可验证、可维护的语义。
