---
name: dp
description: >
  当用户需要用浏览器完成网页截图、页面快照、数据抓取、内容提取、自动登录、填写表单、点击按钮，或任何依赖 DOM、真实登录态、页面渲染结果的网页交互任务时使用。即使用户没有明确提到 DrissionPage，也应主动触发此 skill。
compatibility: >
  需要宿主客户端能够读取此 skill、运行本地 Python 与 shell 命令、读取 bundled scripts/references，并在目标工作区写文件。默认假设 Python 3.10+、可写文件系统、以及可连接本地 Chromium 调试地址的环境。若客户端要接入自定义 browser provider，应在工作区提供 `.dp/providers/<name>.py` 实现，并能访问它依赖的本地 API 或 launcher；若最终使用 fallback `cdp-port`，则必须显式提供测试端口。
metadata:
  bundle-version: "2026-04-27.3"
  runtime-lib-version: "2026-04-27.1"
---

# 浏览器自动化

`dp` 是一个面向 Skill 客户端的浏览器自动化能力包。它基于 DrissionPage，
通过工作区 browser provider 获取可接管的 Chromium 调试地址，再完成截图、抓取、登录、
表单、上传、下载、新标签页等任务。

这个文件是 Agent 执行 contract。它保留必须遵守的流程、边界和判断规则；
具体代码模板和接口细节按需查阅 `references/`，不要在任务中重写 bundled helper。

## 何时使用

在以下任一情况下使用本 skill：

- 用户需要截图、页面快照、抓取、内容提取、登录、表单填写、点击、滚动、上传、下载、切换标签页
- 用户明确要求“用浏览器做这件事”
- 任务必须依赖页面 DOM、真实登录态、浏览器渲染结果或当前浏览器会话状态
- 用户已经在浏览器中登录，希望复用 cookies、页面状态或当前 profile 继续工作

若任务只是纯 HTTP 请求，且明确不需要浏览器、DOM、JS 渲染、已登录浏览器 cookies，
仍可在本 skill 内选择 `SessionPage`；否则默认按浏览器任务处理。

## 执行流程

### 1. Preflight（工作区检测）

`.dp/` 是目标工作区的持久运行时目录。工作区是跨会话复用的，不需要每次新会话都重建；
但在状态不完整、版本不一致或配置显式错误时，必须先处理 preflight。

**工作区根（宿主 cwd）**

在 Claude Code 与 Codex 中，dp 默认以当前会话工作区 `cwd` 作为工作区根，
所有 `.dp/` 路径都相对该根目录解析。调用 `scripts/doctor.py` 前必须确保 `cwd`
已经切到目标工作区根，而不是 skill 安装目录或某个子目录。

**可以跳过 doctor 的条件**（必须全部满足）：

- `.dp/.venv/` 存在，且工作区 Python 可执行并可导入 `DrissionPage`
- `.dp/lib/connect.py`、`.dp/lib/download_correlation.py`、`.dp/lib/output.py`、
  `.dp/lib/utils.py`、`.dp/lib/_dp_compat.py` 全部存在
- `.dp/providers/cdp-port.py` 存在
- `.dp/config.json` 存在，且 `default_provider` 经过规范化后是非空合法 provider 名
- 若当前默认 provider 不是 `cdp-port`，则其对应的 `.dp/providers/<name>.py`
  或等价 snake_case 文件也必须存在
- `.dp/state.json` 存在
- `.dp/state.json` 中的 `runtime_lib_version` 与当前 skill 的 `runtime-lib-version` 一致
- `.dp/state.json` 中的 `bundle_version` 与当前 skill 的 `bundle-version` 一致

**需要运行 doctor 的情况**：

- `.dp/` 不存在、`.dp/.venv/` 缺失，或工作区 Python 不可执行 / 不可导入 `DrissionPage`
- `.dp/lib/connect.py`、`.dp/lib/download_correlation.py`、`.dp/lib/output.py`、
  `.dp/lib/utils.py`、`.dp/lib/_dp_compat.py` 任一缺失
- `.dp/providers/cdp-port.py` 缺失
- `.dp/config.json` 缺失、损坏，或 `default_provider` 缺失 / 非字符串 / 空字符串 / 纯空白
- `.dp/state.json` 不存在、无法解析，或版本不一致
- 任务执行时出现明确的环境错误
- 用户显式要求修复或重新初始化

**显式配置错误要 fail fast**：

- `default_provider` 非空但不合法时，这是配置错误；doctor 不做猜测式修复，
  需用户或客户端修正 `.dp/config.json`
- 当前默认 provider 非 `cdp-port` 但对应 provider 文件缺失时，这是配置错误；
  doctor 不会自动发明实现，需用户或客户端补齐 `.dp/providers/<name>.py`
  或等价 snake_case 文件，或修正 `.dp/config.json`

**操作顺序**：

1. 在目标工作区根运行 `scripts/doctor.py --check`
2. 若退出码为 1，且问题属于缺失、未初始化、空白值、版本不一致等可自动修复状态，
   运行 `scripts/doctor.py`
3. 若 doctor 报非法 `default_provider` 或当前默认 provider 对应实现文件不存在，
   停止自动修复，改由用户或客户端修正配置或提供 provider 实现
4. 修复后工作区 Python 固定为：
   - Windows：`.dp/.venv/Scripts/python.exe`
   - macOS / Linux：`.dp/.venv/bin/python`

**版本刷新语义**：

- `runtime-lib-version` 变化：同步 `.dp/lib/` 与 runtime-managed provider，更新 `.dp/state.json`
- `bundle-version` 单独变化（只有文档/脚本变更）：刷新工作区文档和 `.dp/state.json`；
  不同步 runtime-managed 代码、不重建 venv、不重装依赖

**doctor 的职责边界**：

doctor 只检测和修复工作区环境：venv、lib、runtime-managed provider、config、版本一致性。
对自定义 provider 只做存在性校验，不自动生成实现。以下属于任务运行时检查，不由 doctor 负责：

- 浏览器是否已打开
- 调试端口是否可连接
- 当前页面是否正确
- 当前会话是否已登录

### 2. 识别意图和对象

从用户请求、当前页面和已有脚本上下文提取：

- `site-name`：小写连字符格式，例如 `hacker-news`
- 意图：base 集合为 `screenshot` / `scrape` / `login` / `form` / `upload` /
  `download` / `newtab` / `web-page-sync` / `session-page` / `custom`
- 意图可用 `<base>-<qualifier>` 自然扩展，例如 `scrape-orders`、`login-sso`
- `scripts/list-scripts.py --intent` 按子串过滤，不是精确匹配

对象选择按 `references/mode-selection.md`：

- 需要点击、输入、截图、DOM、页面渲染：**ChromiumPage**（默认）
- 已登录浏览器，需要同步 cookies 后高效请求：**WebPage**
- 纯请求、无需浏览器交互：**SessionPage**

选不准时用 **ChromiumPage**。它覆盖面最完整，也更符合“浏览器自动化”任务的默认预期。

### 2b. 站点名规范化

`site-name` 必须满足 `[a-z0-9-]+`，按以下优先级确定：

1. 优先复用已有 `.dp/projects/<site>/` 目录名
2. 其次使用调用方显式提供的站点名
3. 否则从目标 URL 的 hostname 推导

hostname 推导规则由 `normalize_site_name()` 实现：

- 转小写
- 去掉 `www.` 前缀
- 连续非 `[a-z0-9]` 字符替换为单个 `-`
- 去掉首尾 `-`
- 空值回退为 `site`
- 不做主域截断：`news.ycombinator.com` -> `news-ycombinator-com`

### 3. 端口与连接策略

dp 的连接模型是 provider-first：先解析 browser provider，再接管 provider 返回的调试地址。
普通远程调试端口接入也被收编为 runtime-managed `cdp-port` provider。

- 通用 workflow 模板默认通过 `get_default_browser_provider()` 继承工作区默认 provider
- 工作区默认 provider 存放在 `.dp/config.json` 的 `default_provider`
- 客户端或用户都可以修改 `default_provider`
- 只有任务明确依赖某个 provider 时，脚本才显式固定 provider 名
- `doctor.py` 会同步 runtime-managed `.dp/providers/cdp-port.py`，并把未初始化工作区的
  `default_provider` 初始化为 `cdp-port`
- runtime 只提供 provider contract 与 loader，不内置 AdsPower 等具体 provider 实现
- provider 唯一正式路径是 `.dp/providers/<name>.py`，同时兼容等价 snake_case 文件名
- provider 可通过本地 API、本地 launcher，或显式端口接管来获取调试地址
- 若 workflow 未显式固定 provider，且客户端/用户也未改掉工作区默认值，则回退到 `cdp-port`
- 若当前默认 provider 为 `cdp-port`，必须显式传入 `--port <port>` 或 `browser_profile.port`
- `cdp-port` 不负责启动浏览器，只负责接管显式 port 对应的已运行浏览器
- provider 模式下仍保持 `existing_only(True)`；skill 负责“启动或定位浏览器 + 接管调试地址”，
  不负责关闭 provider 启动出的浏览器
- 高层 workflow 只消费规范化 `launch_info`，不直接依赖 raw provider start result
- 除 `SessionPage` 这类纯请求例外场景外，浏览器类任务默认都走 provider-first 入口

Provider contract 细节见 `references/provider-contract.md`。

### 4. 交互与节奏约束

交互默认走 DrissionPage / CDP 原生能力。不要把手写 DOM 事件、直接改 `value`、
手动派发事件当作主流程；这些只能作为最后兜底。

- 点击 / 输入优先使用 bundled `native_click()` / `native_input()`，它们包含完整等待链
- 上传优先 `upload_file()`，下载优先 `download_file()`
- 新标签页优先 `click.for_new_tab()` / `wait.new_tab()`
- JS 只用于只读探测、辅助定位、临时打标；`by_js=True` 仅最后兜底
- 节奏保持保守，避免高频刷新、无间隔重试、短时间打开过多 tab

文件 helper 的边界要清楚：

- `upload_file()` 默认处理跨平台路径
- workflow 传入 `launch_info` 时，`upload_file()` / `download_file()` 会结合 provider hints
  判断本地文件访问能力
- 若 provider 明确声明 `remote` 或不支持本地文件访问，helper 必须直接报错，
  不继续盲猜路径
- `download_file()` 是单目标下载 helper：一次调用只管理一个目标下载
- `download_file()` 统一走浏览器下载目录 + 点击触发 + 完成等待的主路径
- 支持的链路上，`download_file()` 会尽量在创建下载任务时改名；增强不可用时，
  至少保证最终落盘文件名符合 `rename`
- `download_file(..., by_js=True)` 只影响点击触发方式，不改变下载主路径
- 若任务依赖新标签页，应先完成标签页切换，再触发下载

完整交互链路和 workflow 模板见 `references/workflows.md`。

### 5. 复用优先

先找已有脚本，只有找不到合适脚本时才生成新脚本。这样可以保留站点知识、登录流程、
稳定选择器和历史修复。

1. 先用 bundled `scripts/list-scripts.py` 枚举已有 workflow
2. 若客户端运行时 `cwd` 不在目标项目树内，应显式传入项目根路径：
   `scripts/list-scripts.py --root <project-root>`
3. 读取 index 后，按以下优先级判断是否复用：
   - **site + intent** 精确匹配：强信号，直接复用
   - **url** 前缀匹配：同站点同路径，读取脚本后判断是否复用或微调
   - **task** 语义判断：最后兜底，低置信度时不要盲目套用
4. `status: broken` 的脚本优先修复再复用，而不是绕过旧问题新建脚本

边界示例：

| 场景 | 判断 | 推荐操作 |
|---|---|---|
| site=hn，intent=scrape，已有 `scrape-top.py`，新任务同样是抓 HN 榜单 | site+intent 精确匹配 | 直接复用，无需询问 |
| site=hn，intent=scrape，已有 `scrape-top.py`，新任务是抓评论区 | url 前缀不同 | url 不匹配，生成新脚本 |
| site=hn，已有多个脚本，新任务描述与 task 字段语义相近但不精确 | task 语义低置信度 | 优先生成临时脚本，或先读旧脚本再改 |

### 6. 生成并执行

- 临时执行脚本统一写入 `.dp/tmp/_run.py`
- 执行时优先走工作区虚拟环境
- 生成脚本时统一复用 `.dp/lib` 中的辅助模块
- 不要在业务脚本中复制通用 helper
- 文件头、连接方式、helper 导入方式以 `references/workflows.md` 的对应模板为准；
  纯请求 `SessionPage` 不接管浏览器，也不要求 provider 或端口

### 7. 归档与沉淀

输出必须用 `site_run_dir(site, script_name)` 获取本次执行目录，路径格式为：

```text
.dp/projects/<site>/output/<script-name>/YYYY-MM-DD_HHMMSS_mmm/
```

一个目录对应一次执行，目录内文件使用语义名称，例如 `data.json`、`screenshot.png`、
`before.png`、`detail.json`。

- 临时测试输出保存到 `.dp/tmp/_out/`
- 只在以下情况向用户追问：账号密码、高风险动作（支付 / 发帖 / 删除）、
  或确实无法推断的多义任务
- 默认沉淀：登录 / bootstrap 脚本、多步骤流程、用户明确要求保留、
  已在同站点被第二次引用
- 默认不沉淀：一次性探索、强依赖临时页面状态、ad-hoc 单步操作
- 满足沉淀条件时，将脚本写入 `.dp/projects/<site>/scripts/<name>.py`
- 沉淀脚本应在末尾用 `mark_script_status("ok")` 回写运行状态，
  并在 `except` 中回写 `"broken"`

失败处理与跨脚本协作由 Agent 根据执行上下文语义判断，包括调试、重试、降级模式，
以及多脚本任务中的数据传递。这是设计选择：保留判断空间，但所有输出路径、
provider、helper 和 README 边界仍必须遵守本 contract。

## 站点 README 规则

站点级 `README.md` 采用混合托管模型：`## Scripts` 区块由 Agent 自动维护，
其余章节由人工维护。

- `## Scripts` 托管区必须使用 `<!-- dp:scripts:start/end -->` 标记
- 临时脚本和一次性探索脚本不写入 README
- 若托管标记损坏或缺失，只输出 warning，不重写整份文件
- 骨架格式和完整规范见 `references/site-readme.md`

## 脚本规范

- 文件头、连接方式、helper 使用方式统一以 `references/workflows.md` 的对应模板为准
- 纯请求 `SessionPage` 脚本不导入 provider 连接 helper
- 浏览器连接原则是 `existing_only(True)`：只接管已有浏览器，不调用 `page.quit()` / `browser.quit()`
- 如果业务依赖 browser provider，优先复用 runtime 里的
  `get_default_browser_provider()` / `build_default_browser_profile()` /
  `start_profile_and_connect_browser()`
- 具体 provider 实现放在 `.dp/providers/<name>.py`，不要在业务脚本里手写 provider API 调用
- 新建站点项目时，应确保 `.dp/projects/<site>/{scripts,output}/` 存在
- 站点 README 按上面的强约定维护

## 迭代修改

- 用户要求“在上次脚本基础上修改”时，直接读取并修改原文件
- 覆盖保存，更新 `updated:` 日期
- 不额外新建版本号文件，除非用户明确要求保留多个版本

## 参考文档

按需读取，不要在每个任务里一次性展开所有参考文档：

- 对象选择：`references/mode-selection.md`
- Workflow 模板：`references/workflows.md`
- Provider Contract：`references/provider-contract.md`
- DrissionPage 接口速查：`references/interface.md`
- 站点 README 规则：`references/site-readme.md`

## 评测与发布前检查

- 最小 smoke prompts 见 `evals/evals.json`
- 最小人工验收步骤见 `evals/smoke-checklist.md`
- 分发前先运行 bundled `scripts/validate_bundle.py`
