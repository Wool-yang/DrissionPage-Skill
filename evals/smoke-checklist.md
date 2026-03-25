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
