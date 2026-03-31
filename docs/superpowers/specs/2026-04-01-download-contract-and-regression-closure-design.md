# Download Contract and Regression Closure Design

**Status:** Draft
**Date:** 2026-04-01
**Scope:** `dp` source bundle download helper contract / regression coverage

## Goal

在完成下载 correlation 子层与 file helper 行为收口后，把新的内部实现与公开 contract 重新对齐，
防止再次出现“实现换了、文档没说清、回归网也没拦住”的状态。

本次设计要解决的核心问题：

- 现有测试主要覆盖 happy path，没有锁住非目标响应污染、WSL fallback 断链、点击兼容失效这些负向场景
- source bundle validator 还不知道新的 runtime 资产
- `doctor.py` / preflight prose 还不知道新的 managed lib 资产
- 下载 contract 文案需要跟“统一 raw/CDP 主路径 + 安全增强 + 保留 `by_js` / 删除 `new_tab`”保持一致

本次 contract 收口默认前提：

- `download_file()` 是单目标下载 helper
- batch download 不进入本轮 SKILL 顶层 contract

## Non-Goals

本次设计明确不做以下事项：

- 不新增公开下载 API
- 不把内部 correlation 术语抬升到 `SKILL.md` / README
- 不修改 provider contract 本身
- 不扩展到与下载无关的文档回归
- 不新增 batch download 的公开 contract 文案

## Problem Statement

### 1. Existing Tests Prefer Positive Proof Over Failure Boundaries

当前测试已经证明：

- download raw path 能跑
- Fetch rename 能触发
- remote provider 会 fail fast

但还没有证明：

- 非目标响应不会被污染
- WSL distro fallback 真正贯通到最终路径
- 公开保留的参数没有静默失效

这正是本轮 review 发现问题却没被测试拦住的原因。

### 2. New Runtime Asset Must Become Bundle-Visible

如果新增 `templates/download_correlation.py`，它就属于 source bundle contract 的一部分。

否则会出现：

- 本地实现依赖它
- validator 却不校验它
- doctor/bundle sync 也可能遗漏它
- preflight 仍把旧的 4 个 managed lib 文件写成完整 ready 条件

这会重演此前 provider template 缺失时出现过的 contract 漂移。

### 3. Public Prose Must Reflect the New Internal Shape Without Leaking Internals

对外文档不需要介绍 “request correlation” 这个词。
但它必须准确表达：

- 下载主路径仍统一走浏览器下载目录 + 原生/JS 触发点击 + 完成等待
- 文件名增强是“尽量在任务创建时改名，失败时降级”
- 非下载响应不会被拦截污染
- `by_js` 仍是点击层兜底参数
- `new_tab` 已从 helper contract 中移除
- `download_file()` 仍只表达单目标下载，不承诺批量能力

## Design Principles

1. Regression tests must encode reviewed failure modes  
   review 已经暴露的问题必须进入回归网。

2. Bundle-visible assets must be validator-visible  
   新 runtime 文件不能只存在于实现层。

3. Keep external prose behavior-focused  
   对外讲行为，不讲内部 correlation 细节。

4. Negative-path coverage over marketing coverage  
   与其增加更多“能跑”的示例，不如先锁住“不会误伤”的边界。

5. No premature batch contract  
   在单目标下载内核收口前，不把批量编排提升到顶层 skill contract。

## Proposed Changes

### 1. Expand Unit Tests Around Negative Paths

在 `scripts/test_helpers.py` 中新增以下组别：

- download correlation safety
  - 非附件响应不改写
  - 非匹配 URL/线索响应不改写
  - 命中一次后后续 response 不再改写
  - interceptor cleanup 正确执行

- WSL path closure
  - `wsl.exe` fallback 贯通到最终 UNC 输出
  - distro 缺失直接失败

- click compatibility
  - `by_js=True` 保持语义
  - `new_tab` 已从签名与 canonical docs 中消失
  - 不重新走 DP native download manager

### 2. Harden Bundle Validation

`scripts/validate_bundle.py` 至少补上：

- `templates/download_correlation.py` 进入 `REQUIRED_FILES`
- 进入 `validate_python()` 编译检查
- 如有必要，进入 cross-file consistency 检查，确认 `templates/utils.py` 已引用新模块

同时 `scripts/doctor.py` 与公开 preflight contract 也要收口：

- `doctor.py` 初始化时同步 `.dp/lib/download_correlation.py`
- `doctor.evaluate_workspace()` 把 `.dp/lib/download_correlation.py` 纳入 managed lib completeness 检查
- `SKILL.md` / `evals/smoke-checklist.md` 的 preflight 章节把它纳入 ready 条件

目标是让新 runtime 资产从第一天起就成为 scripts-side 和 prose-side 共同认可的 bundle contract。

### 3. Align Behavior Prose

对外文档只做行为级更新，不引入 internal wording：

- `references/workflows.md`
  - 明确 `download_file()` 的增强是“尽量在任务创建时改名，失败时回退到最终落盘 rename”
  - 明确统一主路径仍然成立
  - 若 `by_js` 仍保留在 helper contract 中，应补一句“仅影响点击触发方式，不改变下载主路径”
  - 不再出现 `download_file(..., new_tab=...)` 之类示例

- `evals/evals.json`
  - 保持对统一下载主路径与 rename 降级语义的描述一致

- `evals/smoke-checklist.md`
  - 保持与 workflow prose 一致
  - 不引入 “correlation” 术语

`SKILL.md` 如无必要不解释内部子层，但若 preflight 已显式列出 managed lib 文件集合，则必须把新资产写进去。
README 如无必要不改；若改，也只改行为表述，不暴露内部子层名称。
同时不在这些对外文档中把 batch download 提升为正式公开能力。

## File Layout

本次 contract closure 涉及：

- Modify: `scripts/test_helpers.py`
- Modify: `scripts/validate_bundle.py`
- Modify: `scripts/doctor.py`
- Modify: `references/workflows.md`
- Modify: `evals/evals.json`
- Modify: `evals/smoke-checklist.md`
- Optional Modify: `SKILL.md`

## Acceptance Criteria

当以下条件全部满足时，本次设计视为完成：

- review 中暴露的 3 类问题都有对应的负向回归测试
- 新 runtime 资产进入 bundle validator
- 新 runtime 资产进入 doctor sync / readiness / preflight prose
- workflow / eval / checklist 对下载行为的描述重新一致
- `new_tab` 从 helper contract、tests、canonical docs 中彻底移除
- 对外文档仍把下载能力表述为单目标下载内核，而非 batch contract
- 对外 contract 仍以 `download_file()` 行为为中心，不泄漏内部 correlation 术语

## Rationale

这次如果只改实现，不补 contract closure，几周后很容易再次回到同一种状态：

- 代码已经换成新架构
- 文档还在描述旧心智模型
- 回归网仍然只证明 happy path 能跑

因此这份 spec 的目的不是扩功能，而是把“正确的失败边界”和“正确的行为描述”一起固定下来。
