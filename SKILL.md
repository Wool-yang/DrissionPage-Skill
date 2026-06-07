---
name: dp
description: >
  当用户需要用浏览器完成网页截图、页面快照、数据抓取、内容提取、自动登录、填写表单、点击按钮、上传下载、新标签页，或需要创建、修复、判断、复用某个站点 workflow 且依赖 DOM、真实登录态、页面渲染结果或当前浏览器会话状态时使用。即使用户没有明确提到 DrissionPage，也应主动触发此 skill。
compatibility: >
  需要宿主客户端能够读取此 skill、运行本地 Python 与 shell 命令、读取 bundled scripts/references，并在目标工作区写文件。默认假设 Python 3.10+、可写文件系统、以及可连接本地 Chromium 调试地址的环境。若客户端要接入自定义 browser provider，应在工作区提供 `.dp/providers/<name>.py` 实现，并能访问它依赖的本地 API 或 launcher；若最终使用 fallback `cdp-port`，则必须显式提供测试端口。
metadata:
  bundle-version: "2026-06-08.2"
  runtime-lib-version: "2026-04-27.1"
---

# 浏览器自动化与站点 Workflow

`dp` 是面向 Skill 客户端的浏览器自动化与站点 workflow 沉淀能力包。它基于
DrissionPage，通过工作区 browser provider 获取可接管的 Chromium 调试地址，
再执行页面动作、探索未知流程、复用或修复已沉淀脚本。

这个文件是渐进式披露入口：这里保留触发条件、preflight、分流规则和安全边界；
脚本头、runner、action templates、provider contract、接口细节按需读取 `references/`。
不要在每个任务里一次性展开所有参考文档。

## 何时使用

在以下任一情况下使用本 skill：

- 用户需要截图、页面快照、抓取、内容提取、登录、表单填写、点击、滚动、上传、下载或新标签页
- 用户明确要求“用浏览器做这件事”
- 任务依赖 DOM、JS 渲染、真实登录态、浏览器 profile、cookies 或当前浏览器会话状态
- 用户需要创建、修复、判断或复用某个站点的可重复 workflow

若任务只是纯 HTTP 请求，且明确不需要浏览器、DOM、JS 渲染或已登录浏览器 cookies，
可以在本 skill 内选择 `SessionPage`；否则默认按浏览器任务处理。

## 执行流程

### 1. Preflight（工作区检测）

`.dp/` 是目标工作区的持久运行时目录。dp 默认以宿主 `cwd` 作为工作区根；
运行 `scripts/doctor.py` 前，必须确认 `cwd` 是目标项目根，而不是 skill 安装目录或子目录。

可以跳过 doctor 的条件（必须全部满足）：

- `.dp/.venv/` 存在，工作区 Python 可执行并可导入 `DrissionPage`
- `.dp/lib/connect.py`、`.dp/lib/download_correlation.py`、`.dp/lib/output.py`、
  `.dp/lib/utils.py`、`.dp/lib/_dp_compat.py` 全部存在
- `.dp/providers/cdp-port.py` 存在
- `.dp/config.json` 存在，且 `default_provider` 规范化后是非空合法 provider 名
- 当前默认 provider 不是 `cdp-port` 时，对应 `.dp/providers/<name>.py`
  或等价 snake_case provider 文件也必须存在
- `.dp/state.json` 存在，且其中 `runtime_lib_version` 匹配本 skill 的
  `runtime-lib-version`，`bundle_version` 匹配本 skill 的 `bundle-version`

需要运行 `scripts/doctor.py --check` 并视情况运行 `scripts/doctor.py`：

- `.dp/`、venv、DrissionPage、managed lib、`.dp/providers/cdp-port.py` 或 state 缺失 / 损坏
- `.dp/config.json` 缺失、损坏，或 `default_provider` 缺失 / 非字符串 / 空字符串 / 纯空白
- `runtime_lib_version` 或 `bundle_version` 不一致
- 用户显式要求初始化、修复或刷新工作区

显式配置错误要 fail fast：

- `default_provider` 非空但不合法时，这是配置错误；doctor 不做猜测式修复，
  需用户或客户端修正 `.dp/config.json`
- 当前默认 provider 非 `cdp-port` 但对应 provider 文件不存在时，这是配置错误；
  doctor 不会自动发明实现，需用户或客户端补齐 `.dp/providers/<name>.py`
  或等价 snake_case 文件，或修正配置

doctor 只负责工作区环境：venv、runtime-managed lib、runtime-managed provider、
config 与版本一致性。浏览器是否打开、调试端口是否可连、页面是否正确、会话是否已登录，
属于任务运行时检查。

修复后工作区 Python 固定为：

- Windows：`.dp/.venv/Scripts/python.exe`
- macOS / Linux：`.dp/.venv/bin/python`

版本刷新语义：

- `runtime-lib-version` 变化：同步 `.dp/lib/` 与 runtime-managed provider，更新 `.dp/state.json`
- 仅 `bundle-version` 变化：刷新工作区文档和 `.dp/state.json`，不重建 venv，不重装依赖，
  不同步 runtime-managed 代码

### 2. 识别意图和对象

先从用户请求、当前页面和已有脚本上下文提取：

- `site-name`：小写连字符格式，例如 `hacker-news`
- action intent：`screenshot` / `scrape` / `login` / `form` / `upload` /
  `download` / `newtab` / `web-page-sync` / `session-page` / `custom`
- 站点 workflow 信号：入口页面、前置状态、关键步骤、状态验证、输出契约、是否已有脚本

对象选择按 `references/mode-selection.md`：

- 需要点击、输入、截图、DOM、页面渲染：`ChromiumPage`（默认）
- 已登录浏览器，需要同步 cookies 后高效请求：`WebPage`
- 纯请求、无需浏览器交互：`SessionPage`

选不准时用 `ChromiumPage`。

### 2b. 站点名规范化

`site-name` 必须满足 `[a-z0-9-]+`，优先级如下：

1. 复用已有 `.dp/projects/<site>/` 目录名
2. 使用调用方显式提供的站点名
3. 从目标 URL hostname 推导

hostname 推导由 `normalize_site_name()` 实现：转小写、去 `www.`、连续非
`[a-z0-9]` 字符合并为 `-`、去首尾 `-`、空值回退 `site`。不做主域截断。

### 3. 端口与连接策略

dp 是 provider-first：先解析 browser provider，再接管 provider 返回的调试地址。
普通远程调试端口也被收编为 runtime-managed `cdp-port` provider。

- 通用脚本默认通过 `get_default_browser_provider()` 继承 `.dp/config.json` 的 `default_provider`
- 只有任务明确依赖某个 provider 时，脚本才固定 provider 名
- 若当前默认 provider 是 `cdp-port`，必须显式传入 `--port <port>` 或 `browser_profile.port`
- `cdp-port` 不启动浏览器，只接管显式 port 对应的已运行浏览器
- provider 实现放在 `.dp/providers/<name>.py`，同时兼容等价 snake_case 文件名
- provider 模式保持 `existing_only(True)`；skill 负责启动或定位浏览器并接管，不负责关闭浏览器
- 高层 workflow 只消费规范化 `launch_info`，不直接依赖 raw provider start result

Provider contract 细节见 `references/provider-contract.md`。

### 4. 交互与节奏约束

交互默认走 DrissionPage / CDP 原生能力。JS 点击、直接改 `value`、手动派发事件只能作为最后兜底。

- 点击 / 输入优先使用 bundled `native_click()` / `native_input()`
- 上传优先 `upload_file()`，下载优先 `download_file()`
- 新标签页优先 `click.for_new_tab()` / `wait.new_tab()`
- JS 只用于只读探测、辅助定位、临时打标；`by_js=True` 仅最后兜底
- 节奏保持保守，避免高频刷新、无间隔重试、短时间打开过多 tab

文件 helper 的边界必须写清楚：

- `upload_file()` 默认处理跨平台路径
- workflow 传入 `launch_info` 时，`upload_file()` / `download_file()` 会结合 provider hints
  判断本地文件访问能力
- 若 provider 明确声明 `remote` 或不支持本地文件访问，helper 必须直接报错，
  不继续盲猜路径
- `download_file()` 是单目标下载 helper；复杂导出、二级菜单、弹窗、range modal
  或后台任务先做 Workflow Discovery

完整浏览器 action 脚本 runner、脚本头和 action templates 见 `references/action-templates.md`。

### 5. 复用 / 修复 / Discovery 优先

先找已有脚本，只有找不到合适脚本时才生成新脚本。

1. 用 bundled `scripts/list-scripts.py` 枚举已有 workflow
2. 若客户端运行时 `cwd` 不在目标项目树内，显式传入项目根：
   `scripts/list-scripts.py --root <project-root>`
3. 强信号直接复用：同 site、同 intent、`status: ok`、入口与输出契约兼容
4. 部分匹配时先读旧脚本，判断复用、微调或修复；`workflow_summary` 只作人类可读摘要和低置信线索
5. `status: broken` 的脚本优先修复再复用，而不是绕过旧问题新建脚本
6. 低置信复用、页面结构不明或输出契约不明时，进入 Workflow Discovery

### 5b. Workflow Discovery

只有目标是建立、修复或判断一条可复用站点 workflow，且已有脚本、站点 README、
历史输出或页面观察无法提供高置信路径时，才先执行 Workflow Discovery。

Discovery 聚焦可复用性：

- 记录入口 URL、当前登录 / 权限 / 页面状态、关键页面区域和可操作控件
- 收集候选选择器、字段含义、表格 / 列表 / 分页 / 弹窗 / iframe 等结构线索
- 用小步交互做状态验证，保留 before / after 截图或 `state.json`
- 明确输出契约，例如 `data.json` 字段、下载文件名、截图名称或脚本参数
- 临时探测脚本写入 `.dp/tmp/`
- 探索证据写入同一次 discovery run-dir：

```text
.dp/projects/<site>/output/workflow-discovery-<intent>/YYYY-MM-DD_HHMMSS_mmm/
```

只有流程可重复执行、输出路径稳定、且沉淀脚本能回写 `status: ok` 时，
才保存到 `.dp/projects/<site>/scripts/` 并进入站点 README 托管区。
详细探测模式见 `references/workflow-discovery.md`。

### 6. 生成、执行和沉淀

- 临时脚本写入 `.dp/tmp/`；简单一次性任务可以覆盖 `.dp/tmp/_run.py`
- 多轮 discovery、调试或需要保留上下文的临时脚本使用语义化文件名，
  例如 `.dp/tmp/_workflow_discovery_<site>_<intent>.py`
- 浏览器 action 脚本的 runner、平台命令、脚本头、连接方式和 helper 导入方式，
  以 `references/action-templates.md` 为准
- 站点 action/workflow 脚本只调用 `.dp/lib` 中的通用 helper，不内联复制 helper 源码
- 纯请求 `SessionPage` 不接管浏览器，也不要求 provider 或端口
- 每次 workflow run 只能有一个 run-dir：

```text
.dp/projects/<site>/output/<script-name>/YYYY-MM-DD_HHMMSS_mmm/
```

- 独立脚本默认用 `site_run_dir(site, script_name)` 创建 run-dir
- 外层编排已创建 `run_dir` 时，子步骤必须复用该目录
- 临时测试输出保存到 `.dp/tmp/_out/`
- 值得复用的流程沉淀到 `.dp/projects/<site>/scripts/<name>.py`
- 沉淀脚本末尾用 `mark_script_status("ok")` 回写运行状态，异常时回写 `"broken"`
- 向用户宣称 workflow 已沉淀前，必须至少成功运行一次并回写 `status: ok`

只在账号密码、高风险动作（支付 / 发帖 / 删除）、或确实无法推断的多义任务上追问用户。

## 站点 README 规则

站点级 `README.md` 使用混合托管模型：`## Scripts` 区块由 Agent 自动维护，其余章节由人工维护。

- `## Scripts` 托管区必须使用 `<!-- dp:scripts:start/end -->` 标记
- 临时脚本和一次性探索脚本不写入 README
- Discovery 证据默认写入 discovery run-dir；除非用户明确要求维护 README，
  或当前任务就是 README 维护，否则不自动改写托管区之外的人工章节
- 若托管标记损坏或缺失，只输出 warning，不重写整份文件
- 骨架格式和完整规范见 `references/site-readme.md`

## 参考文档

按需读取，不要一次性展开所有参考文档：

- 对象选择不确定时读 `references/mode-selection.md`
- 写临时脚本、沉淀脚本、浏览器 action 脚本 runner、脚本头或模板时读
  `references/action-templates.md`
- 需要建立、修复或判断可复用站点 workflow 时读 `references/workflow-discovery.md`
- 接入或排查 browser provider 时读 `references/provider-contract.md`
- 查询 DrissionPage 常用接口时读 `references/interface.md`
- 维护站点 README 托管区时读 `references/site-readme.md`

## 评测与发布前检查

- 最小 smoke prompts 见 `evals/evals.json`
- 行为分流评测见 `evals/agent-behavior-evals.json`
- 人工验收步骤见 `evals/smoke-checklist.md`
- 分发前运行 bundled `scripts/validate_bundle.py`
