# DP Smoke Checklist

按以下顺序做最小人工验收：

## 1. 触发检查

- 给出截图需求，确认客户端会使用 `dp`
- 给出抓取需求，确认客户端会使用 `dp`
- 给出登录或表单需求，确认客户端会使用 `dp`

## 2. Preflight 检查

- 若 `.dp/state.json` 存在且 `runtime_lib_version` 与当前 skill 一致，客户端不重复跑 doctor
- 只有 state 缺失、版本不一致、venv 损坏、显式要求修复时才触发 doctor

## 3. 模式选择检查

- DOM / 点击 / 截图场景 -> `ChromiumPage`
- 已登录继续高效抓数据 -> `WebPage`
- 纯请求场景 -> `SessionPage`

## 4. 浏览器约束检查

- 默认优先接管已有浏览器
- 不新建、不关闭浏览器
- 默认端口 9222；显式传入端口时优先使用显式端口

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
- 被上传文件视为输入，不放入 run-dir
- run-dir 内只保存执行中生成的新文件（如截图确认）

## 8. 下载场景检查

- 下载使用 bundled `download_file()`
- 同 OS 场景优先走 DrissionPage 自带下载管理
- 跨平台场景下载目录要做规范化，避免 WSL 接管 Windows Chromium 时保存路径被本地 `Path()` 改坏
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

## 13. 源码 smoke vs 安装副本 smoke

### 源码 smoke（日常开发验证）

从 `dp-skill-source/` 所在工作区根执行（.dp/ 已初始化，浏览器已以调试端口运行）：

```
python <skill-root>/scripts/smoke.py --port 9222
```

- 验证 run-dir contract（路径、文件语义名、上传输入不进 run-dir 等）
- 验证 10 个 case 全部 PASS

### 安装副本 smoke（发布前验证）

确认安装副本已从最新内层源码同步后，从外层工作区执行：

1. `python <installed-skill-dir>/scripts/doctor.py --check`（若失败则先 init）
2. `python <installed-skill-dir>/scripts/smoke.py --port 9222`

- 验证端到端宿主加载行为
- 验证已安装副本与源码 contract 一致
