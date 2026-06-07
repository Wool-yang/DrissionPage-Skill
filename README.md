# DrissionPage Skill

**[English](README_EN.md)**

`dp` 是一个面向 Skill 客户端的浏览器自动化与站点 workflow 能力包。它基于
[DrissionPage](https://github.com/g1879/DrissionPage)，通过 browser provider
接管可连接的 Chromium 调试地址，用于截图、抓取、登录、表单填写、上传下载、
新标签页处理，以及可复用站点 workflow 的探索和沉淀。

这个仓库发布的是 source bundle。运行时状态、虚拟环境、浏览器状态和任务输出都生成在使用方项目根目录的 `.dp/` 中，不属于本仓库。

## 概念

- **Provider-first**：浏览器任务先解析 browser provider，再接管 provider 返回的调试地址。普通远程调试端口被建模为 runtime-managed `cdp-port` provider。
- **Workflow-first**：workflow 是围绕站点和意图可重复执行的路径，包括入口状态、关键步骤、状态验证、输出契约和可复用脚本。
- **Reuse / Discovery first**：同站点后续任务优先复用或修复 `.dp/projects/<site>/scripts/` 下的脚本；低置信度流程先做 workflow discovery。
- **Native interaction first**：点击、输入、上传、下载、新标签页优先走 DrissionPage / CDP 原生能力，JS 只作为兜底。

## 快速开始

### 前置条件

- 支持 Skill 规范的客户端，例如 Codex、Claude Code，或其他兼容实现
- Python 3.10+
- 可写项目目录，用于生成 `.dp/`
- 若使用默认 `cdp-port` provider，需要 Chromium / Chrome 已开启远程调试端口

### 安装 Skill

```bash
git clone https://github.com/Wool-yang/DrissionPage-Skill.git
cd DrissionPage-Skill
python scripts/install.py --target /path/to/skills/dp
```

### 初始化工作区

在要执行网页任务的项目根目录运行：

```bash
python /path/to/skills/dp/scripts/doctor.py
```

`doctor.py` 会创建或刷新 `.dp/`，包括虚拟环境、运行时 helper、默认 provider、配置和版本状态。
`.dp/` 是本地运行时目录，不要提交到版本控制。

需要只检查不修复时运行：

```bash
python /path/to/skills/dp/scripts/doctor.py --check
```

## 浏览器入口

### 使用 `cdp-port`

未配置自定义 provider 时，默认 provider 是 `cdp-port`。它不会启动浏览器，只接管已经开启远程调试端口的 Chromium / Chrome。

```bash
# macOS / Linux
google-chrome --remote-debugging-port=<port> --user-data-dir=/tmp/chrome-debug
```

```powershell
# Windows PowerShell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=<port> --user-data-dir="$env:TEMP\chrome-debug"
```

当默认 provider 仍是 `cdp-port` 时，执行脚本需要显式提供 `--port <port>`。
`dp` 不会隐式扫描常见端口。

### 使用自定义 provider

在工作区提供 provider 实现：

```text
.dp/providers/<name>.py
```

然后修改 `.dp/config.json`：

```json
{
  "default_provider": "<name>"
}
```

通用 workflow 模板会继承这个默认 provider。Provider contract 见 `references/provider-contract.md`。

## 使用方式

安装并初始化后，在支持 Skill 的客户端中直接描述网页任务：

> “截一张 https://news.ycombinator.com 的全页截图”
>
> “抓取当前页面所有商品名称和价格，保存为 JSON”
>
> “我已经登录了，复用当前浏览器 session 请求订单接口”

Agent 使用 `dp` 时通常会检查 `.dp/`、解析 provider、选择 `ChromiumPage` / `WebPage` /
`SessionPage`、查找已有脚本，并把输出保存到 `.dp/projects/<site>/output/...`。

临时脚本 runner：脚本放在 `.dp/tmp/`，Windows 使用 `.dp/.venv/Scripts/python.exe`，
macOS / Linux 使用 `.dp/.venv/bin/python`。脚本头、runner 命令和 action templates 见
`references/action-templates.md`。

## 目录结构

Source bundle：

```text
.
├── SKILL.md                    # Agent 入口 contract
├── templates/                  # doctor 复制到 .dp/lib/ 的运行时 helper
├── scripts/                    # install / doctor / smoke / validate 工具
├── references/                 # Agent 按需读取的参考文档
└── evals/                      # smoke prompts 与人工验收清单
```

工作区：

```text
.dp/
├── .venv/                      # Python 虚拟环境
├── lib/                        # 运行时 helper 副本
├── providers/                  # 工作区 provider 实现
├── tmp/                        # 临时脚本和临时输出
├── projects/<site>/            # 站点脚本、README 和输出归档
├── config.json                 # default_provider 等配置
└── state.json                  # bundle/runtime 版本状态
```

## 参考文档

- Agent 入口与分流规则：`SKILL.md`
- 脚本头、runner、action templates：`references/action-templates.md`
- Workflow discovery：`references/workflow-discovery.md`
- Provider contract：`references/provider-contract.md`
- 对象选择：`references/mode-selection.md`
- DrissionPage 接口速查：`references/interface.md`
- 站点 README 托管区：`references/site-readme.md`

## 开发与发布

- 修改运行时模板（`templates/`）时，同时 bump `runtime-lib-version` 和 `bundle-version`
- 只修改文档、脚本、参考资料时，只 bump `bundle-version`
- 发布前运行 `python scripts/validate_bundle.py`
- 详细规则见 `CONTRIBUTING.md`

## 依赖

- [DrissionPage](https://github.com/g1879/DrissionPage) `>=4.1.1,<4.2`
- Python 标准库

## License

[MIT](LICENSE)
