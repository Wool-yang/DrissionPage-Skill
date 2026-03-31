# Preflight Prose Drift Closure Design

**Status:** Draft
**Date:** 2026-03-31
**Scope:** `dp` source bundle preflight prose / validator closure

## Goal

补齐 `2026-03-31 workspace-contract-unification` 之后仍然残留的两处公开 prose contract 漂移，
让 `SKILL.md`、`evals/smoke-checklist.md` 与 `doctor.evaluate_workspace()` 的真实语义重新闭环。

本次设计只解决 review 中确认的两个问题：

- 文档把“`.dp/lib/` 存在”写成可跳过 preflight 的充分条件，但真实 readiness 还要求 managed lib 文件完整且工作区 Python 可导入 `DrissionPage`
- 文档把 `default_provider` 的“未初始化”与“显式非法配置”混成同一种 `doctor` 修复路径，违背 conservative repair

## Non-Goals

本次设计明确不做以下事项：

- 不修改 `doctor.py` / `smoke.py` 的 readiness 判定代码
- 不修改 provider-first runtime API
- 不引入新的 provider、state 字段或工作区结构
- 不把 `SKILL.md` 改成由脚本自动生成

## Problem Statement

### 1. Skip-Preflight Prose Is Still Weaker Than Runtime Readiness

当前 `SKILL.md` 与 smoke checklist 都写成：

- `.dp/.venv/` 存在且工作区 Python 可执行
- `.dp/lib/` 存在

但 `doctor.evaluate_workspace()` 的真实判定更严格：

- Python 不只要“可执行”，还必须能从该 venv 成功 `import DrissionPage`
- `.dp/lib/` 不只要目录存在，还必须至少包含：
  - `connect.py`
  - `output.py`
  - `utils.py`
  - `_dp_compat.py`

这意味着客户端若严格遵循当前 prose，仍可能在缺 managed lib 文件或缺依赖的工作区上跳过 doctor，
从而重新制造“文档允许跳过，runtime 实际不可用”的旧问题。

### 2. Config Repair Prose Is Not Truthful

当前 `SKILL.md` 把以下情况写在同一个“需要运行 preflight”分支里：

- `.dp/config.json` 缺失 / 损坏
- `default_provider` 为空
- `default_provider` 不合法

同时操作步骤又统一写成：

1. `doctor.py --check`
2. 若失败则运行 `doctor.py` 修复

但真实 contract 不是这样：

- 缺失、空值、纯空白属于未初始化，doctor 可以自愈到 `cdp-port`
- 非空但非法的 provider 名属于显式配置错误，doctor 必须报错并停止，不能猜测式改写

如果 prose 不区分这两类状态，调用方就会误把“非法配置”当成普通 repair path，
这直接违背 `workspace-contract-unification` 中的 `Conservative repair` 原则。

### 3. Validator Guards Presence, Not the Missing Meaning

`validate_bundle.py` 当前已经确保 preflight 章节提到：

- `.dp/config.json`
- `.dp/providers/cdp-port.py`
- `.dp/state.json`
- `default_provider`
- 版本字段

但它还不能拦住以下误导性 prose：

- 只写 `.dp/lib/`，不写 managed lib 文件与 `DrissionPage`
- 写了 `default_provider` 和“不合法”，却没有写“非法值不会自动修复”

因此 token-level 校验仍不足以覆盖这次 review 暴露的问题。

## Design Principles

1. Truthful public contract  
   公开 prose 必须和 `doctor.evaluate_workspace()` 的真实 ready / repair 语义一致，不能只写“接近”的近似说法。

2. Conservative repair must be explicit  
   “可自动修复”与“必须停下来修配置”必须在 prose 中显式分开，不能让调用方自行脑补。

3. Validator should guard the reviewed failure modes  
   既然这两类漂移已经出现过，就应新增针对性的 validator / tests，避免下次再次漏回去。

4. Minimal change surface  
   只收口 `SKILL.md`、`evals/smoke-checklist.md` 与 validator/tests，不额外扩展 runtime 代码。

## Proposed Changes

### 1. Strengthen the Skip-Preflight Contract

`SKILL.md` 与 `evals/smoke-checklist.md` 的 preflight prose 统一改为：

- `.dp/.venv/` 存在，且工作区 Python 可执行并可导入 `DrissionPage`
- `.dp/lib/connect.py`、`.dp/lib/output.py`、`.dp/lib/utils.py`、`.dp/lib/_dp_compat.py` 全部存在
- `.dp/providers/cdp-port.py` 存在
- `.dp/config.json` 存在且 `default_provider` 经规范化后为合法 provider 名
- `.dp/state.json` 存在且版本匹配

明确禁止继续使用“`.dp/lib/` 存在即可”的宽松表达。

### 2. Split Recoverable vs Non-Recoverable Config States

preflight prose 需要把 config 问题拆成两类：

- **可自动修复**
  - `.dp/config.json` 缺失
  - `.dp/config.json` 损坏
  - `default_provider` 缺失 / 非字符串 / 空字符串 / 纯空白
- **不可自动修复**
  - `default_provider` 非空但不合法
  - 这属于显式配置错误
  - `doctor.py` 不做猜测式修复，应报错并要求用户/客户端修正配置

这条规则不只出现在“需要运行 preflight”的条件里，也必须出现在“操作步骤”里，
避免调用方继续把所有 `--check` 失败都当成统一 repair path。

### 3. Make the Operation Branch Truthful

`SKILL.md` 的操作步骤改成两段式：

1. 先运行 `scripts/doctor.py --check`
2. 若问题属于缺失/空白/版本不一致等可修复问题，则运行 `scripts/doctor.py`
3. 若报错指向 `default_provider` 非法等显式配置错误，则停止自动修复，改由用户/客户端修正 `.dp/config.json`

目标不是把每种错误都列成流程图，而是明确“不是所有 preflight failure 都能自动 repair”。

### 4. Harden Validator Around These Two Drift Classes

`validate_bundle.py::validate_rule_markers()` 增加两类硬检查：

1. **ready-state completeness markers**
   Preflight 章节必须同时提到：
   - `DrissionPage`
   - `.dp/lib/connect.py`
   - `.dp/lib/output.py`
   - `.dp/lib/utils.py`
   - `.dp/lib/_dp_compat.py`

2. **illegal-provider repair boundary markers**
   Preflight 章节必须表达：
   - `default_provider` 非法值是配置错误
   - doctor 不会自动修复 / 不做猜测式修复
   - 需要用户或客户端修正配置

validator 不要求固定逐字文案，但必须要求这些语义 marker 在 preflight 章节内出现。

## Testing Changes

至少新增以下回归测试：

1. `validate_rule_markers()` 在 preflight 缺少 `DrissionPage` 时失败
2. `validate_rule_markers()` 在 preflight 只写 `.dp/lib/`、不写四个 managed lib 文件时失败
3. `validate_rule_markers()` 在 preflight 未声明非法 `default_provider` 不能自动修复时失败
4. `validate_rule_markers()` 对新的等价 prose 仍能通过，避免把 validator 写成逐字匹配

## Documentation Changes

需要同步更新：

- `SKILL.md`
- `evals/smoke-checklist.md`
- 对应 spec / implementation plan

若本次修改 `SKILL.md` frontmatter 中的 `bundle-version`，还需要同步安装副本的 `SKILL.md`，
并在工作区重跑 doctor 以刷新 `.dp/state.json`。

## Acceptance Criteria

当以下条件全部满足时，本次设计视为完成：

- `SKILL.md` 的 skip-preflight 条件不再弱于 `doctor.evaluate_workspace()`
- `SKILL.md` 明确区分 recoverable config 与 illegal provider config
- `SKILL.md` 的操作步骤不再暗示“所有 check 失败都可自动 repair”
- `evals/smoke-checklist.md` 与 `SKILL.md` 对上述语义保持一致
- `validate_bundle.py` 与 `scripts/test_helpers.py` 能阻止这两类 prose drift 再次回归

## Rationale

`workspace-contract-unification` 已经把 scripts-side contract 收口到了 `doctor.evaluate_workspace()`，
但如果公开 prose 仍然允许两种常见误读：

- “目录在就算 ready”
- “非法 provider 也只是 repair 一下”

那么调用方还是会在真正执行前做出错误分支判断。

这次补丁的目标不是扩设计，而是把已经成立的 contract 真正说清楚、测清楚、拦清楚。
