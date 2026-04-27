# DP Smoke Checklist

按以下顺序做最小人工验收。这个清单用于确认 Agent 行为、工作区 contract、
provider-first 连接、输出归档和关键 workflow 都没有偏离设计。

## 1. 触发检查

- 给出截图需求，确认客户端会使用 `dp`
- 给出抓取需求，确认客户端会使用 `dp`
- 给出登录或表单需求，确认客户端会使用 `dp`
- 给出“复用当前浏览器登录态”的需求，确认客户端不会误判为纯请求任务

## 2. Preflight 检查

客户端只有在以下条件全部满足时才可跳过 doctor：

- `.dp/.venv/` 存在，且工作区 Python 可执行并可导入 `DrissionPage`
- `.dp/lib/connect.py`、`.dp/lib/download_correlation.py`、`.dp/lib/output.py`、
  `.dp/lib/utils.py`、`.dp/lib/_dp_compat.py` 全部存在
- `.dp/providers/cdp-port.py` 存在
- `.dp/config.json` 存在
- `default_provider` 可规范化为合法 provider 名
- 若当前默认 provider 不是 `cdp-port`，其对应 provider 文件也必须存在
- `.dp/state.json` 存在
- state 中的 `runtime_lib_version` / `bundle_version` 与当前 skill 一致

需要触发 doctor 自动修复的情况：

- `.dp/config.json` 缺失或损坏
- `default_provider` 缺失 / 非字符串 / 空字符串 / 纯空白
- `.dp/state.json` 缺失、损坏或版本不一致
- runtime-managed 文件缺失

需要 fail fast、让用户或客户端修正的情况：

- `default_provider` 非空但不合法：属于配置错误；doctor 不做猜测式修复
- 当前默认 provider 非 `cdp-port` 但对应 provider 文件缺失：属于配置错误；
  doctor 不会自动发明实现，需补齐 `.dp/providers/<name>.py`
  或等价 snake_case 文件，或修正配置

## 3. 模式选择检查

- DOM / 点击 / 截图 / JS 渲染场景 -> `ChromiumPage`
- 已登录浏览器继续高效抓数据 -> `WebPage`
- 明确纯请求场景 -> `SessionPage`
- 选不准时使用 `ChromiumPage`

## 4. 浏览器约束检查

- 默认先解析工作区 provider，再接管返回的调试地址
- 不新建、不关闭浏览器
- 若最终默认 provider 为 `cdp-port`，必须显式传入 `--port <port>`
- `9222` 只能作为显式示例端口，不是隐藏默认值

## 5. 交互约束检查

- 输入优先原生输入，不直接改 `value`
- 点击优先原生点击，不默认走 JS click
- 上传使用 bundled `upload_file()`
- 下载使用 bundled `download_file()`
- 节奏保守，不高频刷新或无间隔重试

## 6. 输出与沉淀检查

- 输出归档到 `.dp/projects/<site>/output/<script-name>/YYYY-MM-DD_HHMMSS_mmm/`
- 每个目录对应一次执行
- 目录内文件使用语义名称，如 `data.json`、`screenshot.png`
- 临时脚本落到 `.dp/tmp/_run.py`
- 已沉淀脚本写入 `.dp/projects/<site>/scripts/`
- 站点 README 只更新托管区

## 7. 上传场景检查

- 上传使用 bundled `upload_file()`
- 直接 `input[type=file]` 优先走跨平台路径规范化 + 文件输入赋值
- chooser 按钮再走点击上传
- 若 provider 通过 `launch_info` 明确声明 `remote` 或不支持本地文件访问，`upload_file()` 应直接报错
- 被上传文件视为输入，不放入 run-dir
- run-dir 内只保存执行中生成的新文件，如截图确认或结果 JSON

## 8. 下载场景检查

- 下载使用 bundled `download_file()`
- `download_file()` 一次调用只管理一个目标下载
- 统一走浏览器下载目录 + 原生点击 + 完成等待的 CDP 下载主路径
- 跨平台场景下载目录要做规范化，避免 WSL 接管 Windows Chromium 时保存路径被本地 `Path()` 改坏
- 若 provider 通过 `launch_info` 明确声明 `remote` 或不支持本地文件访问，`download_file()` 应直接报错
- 若调用方显式传 `by_js=True`，只应影响点击触发方式，不应改变下载主路径
- 对 `data:` 直链下载可优先本地直存，避免浏览器下载管理器成为单点故障
- 同一次任务只有一个 run-dir
- 下载文件保存到当前 run-dir，文件名优先语义名

## 9. 登录场景检查（login）

- 登录前先检查是否已有有效 session，避免重复登录
- 输入账号密码使用原生输入，不直接操作 `value`
- 登录后等待页面跳转或登录态标志出现，再继续后续操作
- 沉淀脚本不硬编码账号密码
- 若脚本生成登录确认截图或结果元数据，按 run-dir contract 归档到站点输出目录
- 不要求 runtime 自动导出或保存 cookies；默认复用当前浏览器 profile / provider 会话

## 10. 纯请求场景检查（session-page）

- `SessionPage` 不依赖浏览器连接，可单独运行，无需调试端口
- 适用场景：已有显式 cookies / token、纯 API 抓取、无需 JS 渲染
- 若需要当前浏览器登录态或 cookies 同步，应使用 `WebPage`
- 不要在需要 JS 渲染或真实点击的场景错误使用 `SessionPage`

## 11. 新标签页场景检查

- 使用 `click.for_new_tab()` 或 `wait.new_tab()` 切换
- 标签页切换不创建新 run-dir
- 同一任务所有输出归到同一 run-dir
- 如果新标签页里触发下载，应先完成标签页切换，再调用下载 helper

## 12. Custom 多步场景检查

- 仍遵守原生交互优先、保守节奏
- 多步骤产生的所有输出落入同一 run-dir
- 文件名使用语义名称区分不同步骤
- 不因为流程复杂而绕开 provider-first 连接和 bundled helper

## 13. fresh-tab 绑定检查（手动验收）

`start_profile_and_connect_browser(..., fresh_tab=True)` 的 tab_id 绑定只有单元测试覆盖，
需通过真实浏览器手动验证：

- 记录调用前 `browser.tabs` 数量
- 调用 `start_profile_and_connect_browser(..., fresh_tab=True)` 后确认 tab 数量增加了 1
- 返回的 `page.url` 为 `about:blank`（或传入的 url 参数值），不是原来活跃 tab 的 URL
- 在新 tab 上执行 `page.get("https://...")` 不影响原 tab 内容
- 若上述任一项失败，说明 DrissionPage 内部存在单例缓存导致 tab 绑定偏差，
  需考虑改用 `browser.get_tab(tab_id)` 方案

## 14. 源码 smoke vs 安装副本 smoke

### 源码 smoke（日常开发验证）

从 `dp-skill-source/` 所在工作区根执行。前提：

- `.dp/` 已初始化
- 若当前默认 provider 仍为 `cdp-port`，浏览器已在即将显式传入的调试端口上运行

```bash
python <skill-root>/scripts/smoke.py --port <port>
```

应验证：

- run-dir contract 正确
- 上传输入不进入 run-dir
- 10 个 case 全部 PASS

### 安装副本 smoke（发布前验证）

确认安装副本已从最新内层源码同步后，从外层工作区执行：

```bash
python <installed-skill-dir>/scripts/doctor.py --check
python <installed-skill-dir>/scripts/smoke.py --port <port>
```

若 doctor check 失败，先运行 doctor 初始化或刷新工作区，再执行 smoke。

应验证：

- 端到端宿主加载行为正常
- 安装副本与源码 contract 一致
- `.dp/state.json` 记录的版本与当前 skill 一致
