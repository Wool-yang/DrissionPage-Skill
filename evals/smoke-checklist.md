# DP Smoke Checklist

按以下顺序做最小人工验收：

## 1. 触发检查

- 给出截图需求，确认客户端会使用 `dp`
- 给出抓取需求，确认客户端会使用 `dp`
- 给出登录或表单需求，确认客户端会使用 `dp`

## 2. Preflight 检查

- 只有 `.dp/.venv/` 存在且工作区 Python 可执行并可导入 `DrissionPage`、`.dp/lib/connect.py` / `.dp/lib/download_correlation.py` / `.dp/lib/output.py` / `.dp/lib/utils.py` / `.dp/lib/_dp_compat.py`、`.dp/providers/cdp-port.py`、`.dp/config.json`、`.dp/state.json` 全部就绪，且 `default_provider` 可规范化为合法 provider 名、若当前默认 provider 不是 `cdp-port` 则其对应 provider 文件也必须存在、state 中的 `runtime_lib_version` / `bundle_version` 与当前 skill 一致时，客户端才可跳过 doctor
- `.dp/config.json` 缺失、损坏，或 `default_provider` 缺失 / 非字符串 / 空字符串 / 纯空白时，应触发 doctor 自动修复
- `default_provider` 非空但不合法时，属于配置错误；doctor 不做猜测式修复，需用户或客户端修正配置
- 当前默认 provider 非 `cdp-port` 但对应 provider 文件缺失时，属于配置错误；doctor 不会自动发明实现，需用户或客户端补齐对应 provider 文件（含 `.dp/providers/<name>.py` 或等价 snake_case 文件）或修正配置
- 以上任一缺失、损坏或显式要求修复时，都应触发 doctor

## 3. 模式选择检查

- DOM / 点击 / 截图场景 -> `ChromiumPage`
- 已登录继续高效抓数据 -> `WebPage`
- 纯请求场景 -> `SessionPage`

## 4. 浏览器约束检查

- 默认先解析工作区 provider，再接管返回的调试地址
- 不新建、不关闭浏览器
- 若最终默认 provider 为 `cdp-port`，必须显式传入 `--port <port>`
- `9222` 只能作为显式示例端口，不是隐藏默认值

## 5. 交互约束检查

- 输入优先原生输入，不直接改 `value`
- 点击优先原生点击，不默认走 JS click
- 节奏保守，不高频刷新或重试

## 6. 输出与沉淀检查

- 输出归档到 `.dp/projects/<site>/output/<script-name>/YYYY-MM-DD_HHMMSS_mmm/`
- 每个目录对应一次执行，目录内文件用语义名称（如 `data.json`、`screenshot.png`）
- 临时脚本落到 `.dp/tmp/_run.py`
- 已沉淀脚本写入 `.dp/projects/<site>/scripts/`
- 站点 README 按规则更新

## 7. 上传场景检查

- 上传使用 bundled `upload_file()`
- 直接 `input[type=file]` 优先走跨平台路径规范化 + 文件输入赋值；chooser 按钮再走点击上传
- 若 provider 通过 `launch_info` 明确声明 `remote` 或不支持本地文件访问，`upload_file()` 应直接报错
- 被上传文件视为输入，不放入 run-dir
- run-dir 内只保存执行中生成的新文件（如截图确认）

## 8. 下载场景检查

- 下载使用 bundled `download_file()`
- `download_file()` 一次调用只管理一个目标下载
- 统一走浏览器下载目录 + 原生点击 + 完成等待的 CDP 下载主路径
- 跨平台场景下载目录要做规范化，避免 WSL 接管 Windows Chromium 时保存路径被本地 `Path()` 改坏
- 若 provider 通过 `launch_info` 明确声明 `remote` 或不支持本地文件访问，`download_file()` 应直接报错
- 若调用方显式传 `by_js=True`，只应影响点击触发方式，不应改变下载主路径
- 对 `data:` 直链下载可优先本地直存，避免浏览器下载管理器成为单点故障
- 同一次任务只有一个 run dir
- 下载文件保存到当前 run dir，文件名优先语义名

## 9. 登录场景检查（login）

- 登录前先检查是否已有有效 session，避免重复登录
- 输入账号密码使用原生输入，不直接操作 `value`
- 登录后等待页面跳转或登录态标志出现，再继续后续操作
- 登录态 cookies 持久化到 `.dp/projects/<site>/` 供后续复用

## 10. 纯请求场景检查（session-page）

- `SessionPage` 不依赖浏览器连接，可单独运行，无需调试端口
- 适用场景：已有 cookies / token、纯 API 抓取、无需 JS 渲染
- Headers 和 cookies 可从 `ChromiumPage` 导入，或手动构造
- 不要在需要 JS 渲染或真实点击的场景错误使用 `SessionPage`

## 11. 新标签页场景检查

- 使用 `click.for_new_tab()` 或 `wait.new_tab()` 切换
- 标签页切换不创建新 run dir
- 同一任务所有输出归到同一 run dir

## 12. Custom 多步场景检查

- 仍遵守原生交互优先、保守节奏
- 多步骤产生的所有输出落入同一 run dir
- 文件名使用语义名称区分不同步骤

## 13. fresh-tab 绑定检查（手动验收）

`start_profile_and_connect_browser(..., fresh_tab=True)` 的 tab_id 绑定只有单元测试覆盖，需通过真实浏览器手动验证：

- 记录调用前 `browser.tabs` 数量
- 调用 `start_profile_and_connect_browser(..., fresh_tab=True)` 后确认 tab 数量增加了 1
- 返回的 `page.url` 为 `about:blank`（或传入的 url 参数值），不是原来活跃 tab 的 URL
- 在新 tab 上执行 `page.get("https://...")` 不影响原 tab 内容
- 若上述任意一项失败，说明 DrissionPage 内部存在单例缓存导致 tab 绑定偏差，需考虑改用 `browser.get_tab(tab_id)` 方案

## 14. 源码 smoke vs 安装副本 smoke

### 源码 smoke（日常开发验证）

从 `dp-skill-source/` 所在工作区根执行（`.dp/` 已初始化；若当前默认 provider 仍为 `cdp-port`，浏览器已在你即将显式传入的调试端口上运行）：

```
python <skill-root>/scripts/smoke.py --port <port>
```

- 验证 run-dir contract（路径、文件语义名、上传输入不进 run-dir 等）
- 验证 10 个 case 全部 PASS

### 安装副本 smoke（发布前验证）

确认安装副本已从最新内层源码同步后，从外层工作区执行：

1. `python <installed-skill-dir>/scripts/doctor.py --check`（若失败则先 init）
2. `python <installed-skill-dir>/scripts/smoke.py --port <port>`

- 验证端到端宿主加载行为
- 验证已安装副本与源码 contract 一致
