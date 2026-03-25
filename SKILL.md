---
name: dp
description: >
  使用 DrissionPage 接管用户已经打开的 Chromium 浏览器来完成网页自动化任务。每当用户提到网页截图、页面快照、数据抓取、内容提取、自动登录、填写表单、点击按钮，或任何涉及浏览器交互的需求时，都应主动使用此 skill，即使用户没有明确提到 DrissionPage。默认优先连接用户已有浏览器的远程调试端口，而不是自行新建或关闭浏览器。
compatibility: >
  需要宿主客户端能够读取此 skill、运行本地 Python 与 shell 命令、读取 bundled scripts/references，并在目标工作区写文件。默认假设 Python 3.10+、可写文件系统、以及可连接本地 Chromium 远程调试端口的环境。
metadata:
  bundle-version: "2026-03-20.1"
  runtime-lib-version: "2026-03-25.1"
  bundle-type: "canonical-source"
---

# 浏览器自动化

这是 `dp` 的 canonical source bundle。客户端应按自己的机制消费或安装这份 skill；此 source bundle 不负责生成任何客户端专属安装目录或配置产物。

优先复用这个 skill 包里的脚本、模板和参考文档，不要在每次任务里重写通用辅助逻辑。

## 何时使用

- 用户需要截图、抓取、提取、登录、表单填写、点击、滚动、上传、下载、切换标签页
- 用户明确要求“用浏览器做这件事”，或任务必须依赖页面 DOM、真实登录态、浏览器渲染结果
- 用户已经在浏览器中登录，希望复用当前会话、cookies 或页面状态继续工作

## 执行流程

### 1. Preflight（工作区检测）

工作区是**跨会话可复用**的持久状态，不需要每次新会话都重新检测。

**可以跳过 preflight 的条件**（满足以下全部）：
- `.dp/state.json` 存在
- `state.json` 中的 `runtime_lib_version` 与当前 skill 的 `runtime-lib-version` 一致

**需要运行 preflight 的情况**：
- `.dp/` 不存在、`.dp/.venv/` 缺失、`.dp/lib/` 缺失
- `.dp/state.json` 不存在或版本不一致
- 任务执行时出现明确的环境错误
- 用户显式要求修复

**操作**：
1. 运行 `scripts/doctor.py --check`
2. 若退出码为 1，运行 `scripts/doctor.py` 修复
3. 修复完成后工作区 Python 固定为：
   - Windows：`.dp/.venv/Scripts/python.exe`
   - macOS / Linux：`.dp/.venv/bin/python`

**doctor 的职责边界**：doctor 只检测/修复**工作区环境**（venv、lib、版本一致性）。
以下属于**任务运行时检查**，不由 doctor 负责：
- 浏览器是否已打开、调试端口是否可连接
- 当前页面是否正确、当前会话是否已登录

### 2. 识别意图和对象

从用户请求或上下文提取：

- `site-name`：小写连字符格式，如 `hacker-news`
- 意图：`screenshot` / `scrape` / `login` / `form` / `custom`
- 对象选择（见 `references/mode-selection.md`）：
  - 需要点击、截图、DOM、页面渲染 -> **ChromiumPage**（默认）
  - 已登录浏览器，需要同步 cookies 继续高效请求 -> **WebPage**
  - 纯请求、无需浏览器交互 -> **SessionPage**

选不准时默认用 **ChromiumPage**。

### 3. 端口与连接策略

- 默认远程调试端口是 `9222`
- 如果客户端或用户已知目标端口，优先显式传入 `--port <port>`
- 只有未显式指定端口时，才允许按候选端口顺序扫描：`9222`、`9333`、`9444`、`9111`
- 除 `SessionPage` 这类纯请求例外场景外，默认始终优先接管已有浏览器，不新建、不关闭

### 4. 交互与节奏约束

- 优先 DrissionPage / CDP 内置能力，尽量不要手写 DOM 事件、直接改 `value`、直接改状态
- 点击默认顺序：`wait.clickable()` -> `scroll.to_see()` -> `wait.stop_moving()` -> `wait.not_covered()` -> `click(by_js=False)`
- 输入默认顺序：`scroll.to_see()` -> `wait.clickable()` -> `focus()` -> `clear(by_js=False)` -> `input(..., by_js=False)`
- 滚动 / 悬停 / 拖拽优先 `scroll.to_see()`、`hover()`、`drag()` / `drag_to()`
- 上传 / 下载 / 新标签优先 `click.to_upload()`、`click.to_download()`、`click.for_new_tab()` / `wait.new_tab()`
- JS 只用于只读探测、辅助定位、临时打标；`by_js=True`、`this.click()`、手动派发事件仅最后兜底
- 节奏保持保守：避免高频刷新、无间隔重试、短时间打开过多 tab、短时间扫过多目标

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
- 如果任务完成后明显值得复用，将脚本沉淀到 `.dp/projects/<site>/scripts/<name>.py`
- 沉淀脚本应在末尾用 `mark_script_status("ok")` 回写运行状态，并在 except 中回写 `"broken"`

## 站点 README 规则

站点级 `README.md` 是强约定，但由客户端按规范维护，不要求由 bundled 脚本自动生成。

### 最小骨架（必需）

每个 `.dp/projects/<site>/README.md` 至少包含：

- `# <site-name>`
- `## Scripts`
- `## Notes`
- `## Last Updated`

### 可选扩展（按需披露）

只有在站点复杂度确实需要时，才增加这些章节：

- `## Login`
- `## Common Selectors`
- `## Output Fields`
- `## Caveats`

### 更新义务

- 新增已沉淀脚本 -> 必须在 `## Scripts` 中增加条目
- 修改已沉淀脚本 -> 必须更新对应条目和 `Last Updated`
- 删除已沉淀脚本 -> 必须同步移除条目
- 临时脚本和一次性探索脚本 -> 不写入站点 README

README 条目至少写明：脚本文件名、一句话用途、推荐复用场景、最后更新时间。

## 脚本规范

- 文件头、连接方式、helper 使用方式，统一以 `references/workflows.md` 的“通用脚本头”为准
- 浏览器连接原则：`existing_only(True)`；只接管已有浏览器，不调用 `page.quit()` / `browser.quit()`
- 新建站点项目时，应确保 `.dp/projects/<site>/{scripts,output}/` 存在；站点 README 按上面的强约定维护

## 迭代修改

- 用户要求“在上次脚本基础上修改”时，直接读取并修改原文件
- 覆盖保存，更新 `updated:` 日期
- 不额外新建版本号文件，除非用户明确要求保留多个版本

## 参考文档

- 对象选择：`references/mode-selection.md`
- Workflow 模板：`references/workflows.md`
- DrissionPage 接口速查：`references/interface.md`
- 站点 README 模板：`references/site-readme.md`

## 评测与发布前检查

- 最小 smoke prompts 见 `evals/evals.json`
- 最小人工验收步骤见 `evals/smoke-checklist.md`
- 分发前先运行 bundled `scripts/validate_bundle.py`
