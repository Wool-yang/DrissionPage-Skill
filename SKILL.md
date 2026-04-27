---
name: dp
description: >
  当用户需要用浏览器完成网页截图、页面快照、数据抓取、内容提取、自动登录、填写表单、点击按钮，或任何依赖 DOM、真实登录态、页面渲染结果的网页交互任务时使用。即使用户没有明确提到 DrissionPage，也应主动触发此 skill。
compatibility: >
  需要宿主客户端能够读取此 skill、运行本地 Python 与 shell 命令、读取 bundled scripts/references，并在目标工作区写文件。默认假设 Python 3.10+、可写文件系统、以及可连接本地 Chromium 调试地址的环境。若客户端要接入自定义 browser provider，应在工作区提供 `.dp/providers/<name>.py` 实现，并能访问它依赖的本地 API 或 launcher；若最终使用 fallback `cdp-port`，则必须显式提供测试端口。
metadata:
  bundle-version: "2026-04-27.1"
  runtime-lib-version: "2026-04-27.1"
---

# 浏览器自动化

这是 `dp` skill 的公开安装源。客户端可以把它安装到任意本地 skill 目录；skill 的执行逻辑不依赖固定安装目录名，不假设自身位于特定路径。

优先复用这个 skill 包里的脚本、模板和参考文档，不要在每次任务里重写通用辅助逻辑。

## 何时使用

- 用户需要截图、抓取、提取、登录、表单填写、点击、滚动、上传、下载、切换标签页
- 用户明确要求“用浏览器做这件事”，或任务必须依赖页面 DOM、真实登录态、浏览器渲染结果
- 用户已经在浏览器中登录，希望复用当前会话、cookies 或页面状态继续工作

## 执行流程

### 1. Preflight（工作区检测）

工作区是**跨会话可复用**的持久状态，不需要每次新会话都重新检测。

**工作区根（宿主 cwd）**：
在 Claude Code 与 Codex 中，dp 默认以当前会话工作区 cwd 作为工作区根，
.dp/ 路径一律相对该根目录解析；调用 scripts/doctor.py 前必须确保 cwd 已切到目标工作区根。

**可以跳过 preflight 的条件**（满足以下全部）：
- `.dp/.venv/` 存在，且工作区 Python 可执行并可导入 `DrissionPage`
- `.dp/lib/connect.py`、`.dp/lib/download_correlation.py`、`.dp/lib/output.py`、`.dp/lib/utils.py`、`.dp/lib/_dp_compat.py` 全部存在
- `.dp/providers/cdp-port.py` 存在
- `.dp/config.json` 存在，且 `default_provider` 经过规范化后是非空合法 provider 名
- 若当前默认 provider 不是 `cdp-port`，则其对应的 `.dp/providers/<name>.py` 或等价 snake_case 文件也必须存在
- `.dp/state.json` 存在
- `state.json` 中的 `runtime_lib_version` 与当前 skill 的 `runtime-lib-version` 一致
- `state.json` 中的 `bundle_version` 与当前 skill 的 `bundle-version` 一致

**需要运行 preflight 的情况**：
- `.dp/` 不存在、`.dp/.venv/` 缺失，或工作区 Python 不可执行 / 不可导入 `DrissionPage`
- `.dp/lib/connect.py`、`.dp/lib/download_correlation.py`、`.dp/lib/output.py`、`.dp/lib/utils.py`、`.dp/lib/_dp_compat.py` 任一缺失
- `.dp/providers/cdp-port.py` 缺失
- `.dp/config.json` 缺失、损坏，或 `default_provider` 缺失 / 非字符串 / 空字符串 / 纯空白
- `default_provider` 非空但不合法：属于显式配置错误，doctor 不做猜测式修复，需用户或客户端修正 `.dp/config.json`
- 当前默认 provider 非 `cdp-port` 但对应 provider 文件缺失：属于显式配置错误，doctor 不会自动发明实现，需用户或客户端补齐 `.dp/providers/<name>.py` 或修正 `.dp/config.json`
- `.dp/state.json` 不存在或版本不一致
- `.dp/state.json` 损坏（无法解析）：视同工作区需要重新初始化，操作与"版本不一致"相同
- 任务执行时出现明确的环境错误
- 用户显式要求修复

**操作**：
1. 运行 `scripts/doctor.py --check`
2. 若退出码为 1，且问题属于缺失 / 空白 / 版本不一致等可自动修复状态，运行 `scripts/doctor.py`
3. 若 `doctor.py` 报 `default_provider` 不合法、或当前默认 provider 对应实现文件不存在等显式配置错误，则停止自动修复，改由用户或客户端修正 `.dp/config.json` 或补齐 `.dp/providers/<name>.py`
4. 修复完成后工作区 Python 固定为：
   - Windows：`.dp/.venv/Scripts/python.exe`
   - macOS / Linux：`.dp/.venv/bin/python`

**两种刷新路径的区别**：
- `runtime-lib-version` 变化：同步 `.dp/lib/` 与 runtime-managed provider，更新 state.json
- `bundle-version` 单独变化（只有文档/脚本变更）：只刷新工作区文档和 state.json，**不同步 runtime-managed 代码、不重建 venv、不重装依赖**

**doctor 的职责边界**：doctor 只检测/修复**工作区环境**（venv、lib、runtime-managed provider、config、版本一致性）；对自定义 provider 只做存在性校验，不自动生成实现。
以下属于**任务运行时检查**，不由 doctor 负责：
- 浏览器是否已打开、调试端口是否可连接
- 当前页面是否正确、当前会话是否已登录

### 2. 识别意图和对象

从用户请求或上下文提取：

- `site-name`：小写连字符格式，如 `hacker-news`
- 意图：base 集合为 `screenshot` / `scrape` / `login` / `form` / `upload` / `download` / `newtab` / `web-page-sync` / `custom`，
  允许用 `<base>-<qualifier>` 格式扩展（如 `scrape-orders`、`login-sso`）；
  `scripts/list-scripts.py --intent` 按**子串**过滤，不是精确匹配
- 对象选择（见 `references/mode-selection.md`）：
  - 需要点击、截图、DOM、页面渲染 -> **ChromiumPage**（默认）
  - 已登录浏览器，需要同步 cookies 继续高效请求 -> **WebPage**
  - 纯请求、无需浏览器交互 -> **SessionPage**

选不准时默认用 **ChromiumPage**。

### 2b. 站点名规范化

`site-name` 需满足 `[a-z0-9-]+` 格式，按以下优先级确定：

1. 优先复用已有 `.dp/projects/<site>/` 目录名
2. 其次使用调用方显式提供的站点名
3. 否则从目标 URL 的 hostname 推导

hostname 推导规则（由 `normalize_site_name()` 实现）：
- 转小写
- 去掉 `www.` 前缀
- 连续非 `[a-z0-9]` 字符替换为单个 `-`
- 去掉首尾 `-`
- 空值回退为 `site`
- 不做主域截断（`news.ycombinator.com` → `news-ycombinator-com`）

### 3. 端口与连接策略

- 默认行为是先解析 browser provider，不再先扫描远程调试端口
- 通用 workflow 模板默认通过 `get_default_browser_provider()` 继承工作区默认 provider；只有任务明确依赖某个 provider 时才显式固定 provider 名
- 工作区默认 provider 存放在 `.dp/config.json` 的 `default_provider`；客户端或用户都可以修改它
- `doctor.py` 会在工作区同步 runtime-managed `cdp-port.py`，并把 `default_provider` 初始化为 `cdp-port`
- runtime 只提供 provider contract 与 loader，不内置 AdsPower 等具体 provider 实现
- provider 唯一正式路径：`.dp/providers/<name>.py`
- provider 可通过本地 API、本地 launcher，或显式端口接管来获取调试地址
- 若 workflow 未显式固定 provider，且客户端/用户也未改掉工作区默认值，则回退到 `cdp-port`
- 若当前默认 provider 为 `cdp-port`，必须显式传入 `--port <port>` 或 `browser_profile.port`
- `cdp-port` 不负责启动浏览器，只负责接管显式端口对应的已运行浏览器
- provider 模式下仍保持 `existing_only(True)`；skill 负责“启动或定位浏览器 + 接管调试地址”，不负责关闭 provider 启动出的浏览器
- 高层 workflow 只消费规范化 `launch_info`，不直接依赖 raw provider start result
- 除 `SessionPage` 这类纯请求例外场景外，浏览器类任务默认都走 provider

### 4. 交互与节奏约束

- 优先 DrissionPage / CDP 内置能力，不手写 DOM 事件、不直接改 `value`
- 点击 / 输入优先使用 bundled `native_click()` / `native_input()`（含完整等待链）
- 上传优先 `upload_file()`，下载优先 `download_file()`
  - `upload_file()` 默认处理跨平台路径；若 workflow 传入 `launch_info`，还会结合 provider hints 判断本地文件访问能力；若 provider 明确声明 `remote` 或不支持本地文件访问，则 helper 直接报错
  - `download_file()` 是**单目标下载 helper**：一次调用只管理一个目标下载，统一走浏览器下载目录 + 点击触发 + 完成等待的主路径
  - `download_file()` 在支持的链路上会尽量在创建下载任务时改名；若增强不可用，则回退到最终落盘 rename
  - 必要时可用 `download_file(..., by_js=True)` 作为点击兜底；它只影响点击触发方式，不改变下载主路径
  - 若任务依赖新标签页，应先完成标签页切换，再触发下载
- 新标签优先 `click.for_new_tab()` / `wait.new_tab()`
- JS 只用于只读探测、辅助定位、临时打标；`by_js=True` 仅最后兜底
- 节奏保持保守：避免高频刷新、无间隔重试、短时间打开过多 tab
- 完整交互链路和 workflow 模板见 `references/workflows.md`

### 5. 复用优先

- 先用 bundled `scripts/list-scripts.py` 枚举已有 workflow
- 若客户端运行时 cwd 不在目标项目树内，应显式传入项目根路径：`scripts/list-scripts.py --root <project-root>`
- 读取 index 后，按以下优先级判断是否有可复用脚本：
  1. **site + intent** 精确匹配（最强信号）
  2. **url** 前缀匹配（同站点同路径，区分子场景）
  3. **task** 语义判断（最后兜底）
- `status: broken` 的脚本优先修复再复用，而非新建
- 找到匹配脚本时，优先读取并静默复用；只有复杂修改才额外询问
- 找不到匹配脚本时，才从 `references/workflows.md` 选模板生成

**三级匹配的设计意图**：`site+intent` 和 `url` 是强信号，客户端应直接复用；
`task` 是有意保留给 Agent 的**语义判断层**，低置信度时不要强复用——
优先生成临时脚本，或先读旧脚本再改，而不是盲目套用。

**边界示例**：

| 场景 | 判断 | 推荐操作 |
|---|---|---|
| site=hn，intent=scrape，已有 `scrape-top.py`，新任务同样是抓 HN 榜单 | site+intent 精确匹配 | 直接复用，无需询问 |
| site=hn，intent=scrape，已有 `scrape-top.py`，新任务是抓评论区 | url 前缀不同（`/item?id=...` vs `/`） | url 不匹配，生成新脚本 |
| site=hn，已有多个脚本，新任务描述与 task 字段语义相近但不精确 | task 语义低置信度 | 优先生成临时脚本，或先读旧脚本再改，不要盲目套用 |

### 6. 生成并执行

- 临时执行脚本统一写入 `.dp/tmp/_run.py`
- 执行时优先走工作区虚拟环境
- 生成脚本时，统一复用 `.dp/lib` 中的辅助模块，不要在业务脚本中复制通用 helper

### 7. 归档与沉淀

- 输出使用 `site_run_dir(site, script_name)` 获取本次执行目录，路径格式为：
  `.dp/projects/<site>/output/<script-name>/YYYY-MM-DD_HHMMSS_mmm/`
- 一个目录对应一次执行，目录内文件用语义名称（`data.json`、`screenshot.png` 等）
- 临时测试输出保存到 `.dp/tmp/_out/`
- 只在以下情况向用户追问：账号密码、高风险动作（支付 / 发帖 / 删除）、确实无法推断的多义任务
- 任务完成后按以下判断是否沉淀脚本：

  **默认沉淀**：登录 / bootstrap 脚本、多步骤流程、用户明确要求保留、已在同站点被第二次引用
  **默认不沉淀**：一次性探索、强依赖临时页面状态、ad-hoc 单步操作

  满足沉淀条件时，将脚本写入 `.dp/projects/<site>/scripts/<name>.py`
- 沉淀脚本应在末尾用 `mark_script_status("ok")` 回写运行状态，并在 except 中回写 `"broken"`

**关于失败处理与跨脚本协作**：脚本异常时如何响应（调试/重试/降级模式），
以及多脚本任务中的数据传递（如 login 输出给 scrape 使用），
均由 Agent 根据执行上下文**语义判断**，不预设固定协议。这是设计选择，不是遗漏。

## 站点 README 规则

站点级 `README.md` 采用**混合托管模型**：`## Scripts` 区块由 Agent 自动维护（用 `<!-- dp:scripts:start/end -->` 标记），其余章节由人工维护。

- 临时脚本和一次性探索脚本不写入 README
- 若托管标记损坏或缺失，只输出 warning，不重写整份文件
- 骨架格式和完整规范见 `references/site-readme.md`

## 脚本规范

- 文件头、连接方式、helper 使用方式，统一以 `references/workflows.md` 的“通用脚本头”为准
- 浏览器连接原则：`existing_only(True)`；只接管已有浏览器，不调用 `page.quit()` / `browser.quit()`
- 如果业务依赖 browser provider，优先复用 runtime 里的 `get_default_browser_provider()` / `build_default_browser_profile()` / `start_profile_and_connect_browser()`；具体 provider 实现放在 `.dp/providers/<name>.py`，不要在业务脚本里手写 provider API 调用
- 新建站点项目时，应确保 `.dp/projects/<site>/{scripts,output}/` 存在；站点 README 按上面的强约定维护

## 迭代修改

- 用户要求“在上次脚本基础上修改”时，直接读取并修改原文件
- 覆盖保存，更新 `updated:` 日期
- 不额外新建版本号文件，除非用户明确要求保留多个版本

## 参考文档

- 对象选择：`references/mode-selection.md`
- Workflow 模板：`references/workflows.md`
- Provider Contract：`references/provider-contract.md`
- DrissionPage 接口速查：`references/interface.md`
- 站点 README 模板：`references/site-readme.md`

## 评测与发布前检查

- 最小 smoke prompts 见 `evals/evals.json`
- 最小人工验收步骤见 `evals/smoke-checklist.md`
- 分发前先运行 bundled `scripts/validate_bundle.py`
