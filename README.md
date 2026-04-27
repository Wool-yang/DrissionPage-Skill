# DrissionPage Skill

**[English](README_EN.md)**

`dp` 是一个面向 Skill 客户端的浏览器自动化能力包。它基于
[DrissionPage](https://github.com/g1879/DrissionPage)，通过 browser provider
获取并接管可连接的 Chromium 调试地址，用于完成截图、抓取、登录、表单填写、
文件上传下载、新标签页处理等网页任务。

这个仓库发布的是通用 source bundle：`SKILL.md` 给 Agent 提供执行 contract，
`templates/` 提供运行时 helper，`references/` 提供按需读取的模板和接口说明。
运行时状态不放在本仓库中，而是在使用方项目根目录的 `.dp/` 工作区中生成。

---

## 设计模型

### Provider-first

所有浏览器类任务默认先解析 browser provider，再接管 provider 返回的调试地址。
普通远程调试端口也被建模为 runtime-managed `cdp-port` provider，而不是散落在脚本里的特殊逻辑。

### Provider 可扩展

`dp` 核心只提供 provider contract 和 loader，不内置 AdsPower、指纹浏览器或具体 launcher 的私有 API。
自定义 provider 放在目标工作区的 `.dp/providers/<name>.py`，由客户端或用户维护。

### 复用优先

站点脚本会沉淀到 `.dp/projects/<site>/scripts/`。后续同站点、同意图或相近路径的任务优先复用已有脚本，
这样可以保留登录流程、稳定选择器、历史修复和站点经验。

### 原生交互优先

点击、输入、上传、下载、新标签页等动作优先走 DrissionPage / CDP 的原生能力。
JS 点击、直接改 `value`、手动派发事件只作为最后兜底。

---

## 能做什么

| 任务类型 | 示例 |
|----------|------|
| 截图 | 全页截图、元素截图、指定区域截图 |
| 抓取 | 列表提取、详情页提取、翻页抓取 |
| 登录 | 账号密码登录、复用当前浏览器登录态 |
| 表单 | 填写字段、提交表单、保存结果截图 |
| 上传 | 处理本地文件路径并填入上传控件 |
| 下载 | 单目标下载、语义文件名、跨平台下载目录处理 |
| 新标签页 | 点击后切换到新标签并继续操作 |
| 混合模式 | 浏览器登录后同步 cookies，再用 requests/session 高效请求 |
| 自定义 provider | 通过工作区 provider 启动或定位浏览器后接管 |

---

## 快速开始

### 前置条件

- 任意支持 Skill 规范的客户端框架，例如 Claude Code、Codex，或其他兼容实现
- Python 3.10+
- 可写项目目录，用于生成 `.dp/` 工作区
- 若最终使用默认 `cdp-port` provider，需要 Chromium / Chrome 已开启远程调试端口

### 安装 Skill

```bash
git clone https://github.com/Wool-yang/DrissionPage-Skill.git
cd DrissionPage-Skill

# 安装到目标客户端的 skill 目录，路径按实际客户端调整
python scripts/install.py --target /path/to/skills/dp
```

### 初始化工作区

在要执行网页任务的项目根目录运行：

```bash
python /path/to/skills/dp/scripts/doctor.py
```

该命令会在当前项目根生成 `.dp/`，包括虚拟环境、运行时 helper、默认 provider、配置和版本状态。
`.dp/` 是本机运行时目录，不应提交到版本控制。

### 使用 `cdp-port` 接管已有浏览器

如果没有配置自定义 provider，工作区默认 provider 是 `cdp-port`。它不会启动浏览器，
只接管已经开启远程调试端口的 Chromium / Chrome。

```bash
# macOS / Linux
google-chrome --remote-debugging-port=<port> --user-data-dir=/tmp/chrome-debug

# Windows PowerShell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=<port> --user-data-dir="$env:TEMP\chrome-debug"
```

当默认 provider 仍为 `cdp-port` 时，执行脚本需要显式提供端口，例如 `--port <port>`。
`dp` 不会隐式扫描常见端口。

### 切换到自定义 provider

在工作区中提供 provider 实现：

```text
.dp/providers/<name>.py
```

然后修改 `.dp/config.json`：

```json
{
  "default_provider": "<name>"
}
```

通用 workflow 模板会继承这个默认 provider。只有任务明确依赖某个 provider 时，脚本才需要固定 provider 名。
Provider contract 见 `references/provider-contract.md`。

---

## 使用方式

安装并初始化后，在支持 Skill 的客户端中直接描述任务：

> “截一张 https://news.ycombinator.com 的全页截图”
>
> “抓取当前页面所有商品名称和价格，保存为 JSON”
>
> “我已经登录了，帮我复用当前浏览器 session 请求订单接口”

Agent 使用 `dp` 时通常会：

1. 检查 `.dp/` 工作区是否就绪，必要时运行 doctor
2. 解析默认 provider，并通过 provider 获取调试地址
3. 判断使用 `ChromiumPage`、`WebPage` 还是 `SessionPage`
4. 查找已沉淀脚本，优先复用或修复
5. 必要时生成临时脚本并执行
6. 将输出保存到 `.dp/projects/<site>/output/<script-name>/<timestamp>/`
7. 对值得复用的流程沉淀脚本，并维护站点 README 的托管区

---

## Source Bundle 结构

```text
.
├── SKILL.md                    # Agent 入口 contract
├── templates/                  # 运行时库，doctor 复制到 .dp/lib/
│   ├── connect.py              # provider-first 浏览器连接 helper
│   ├── download_correlation.py # 单目标下载请求相关性子层
│   ├── output.py               # run-dir 与输出路径管理
│   ├── utils.py                # 截图、点击、输入、上传、下载等 helper
│   ├── _dp_compat.py           # DrissionPage 内部 API 兼容层
│   └── providers/
│       └── cdp-port.py         # runtime-managed fallback provider
├── scripts/                    # 安装、doctor、smoke、校验工具
├── references/                 # Agent 按需读取的参考文档
└── evals/                      # 最小 smoke prompts 与人工验收清单
```

## 工作区结构

```text
.dp/
├── .venv/                      # 自动创建的 Python 虚拟环境
├── lib/                        # 运行时库副本，由 doctor 管理
├── providers/                  # 工作区 provider 实现
├── tmp/
│   ├── _run.py                 # 当次执行的临时脚本
│   └── _out/                   # 临时输出
├── projects/
│   └── <site-name>/
│       ├── README.md           # 站点索引，Scripts 区块由 Agent 托管
│       ├── scripts/            # 沉淀的可复用脚本
│       └── output/             # 按任务和时间戳归档的执行输出
├── config.json                 # default_provider 等工作区配置
└── state.json                  # bundle/runtime 版本状态
```

`.dp/` 只属于本机工作区。它可能包含虚拟环境、运行时状态、浏览器 profile 相关信息或任务输出，
不要作为 source bundle 的一部分发布。

---

## 客户端适配

本仓库定义的是跨客户端通用 bundle 和运行时 contract，不绑定单一客户端。
不同客户端可以在安装目录中保留自己的适配文件；这些文件属于客户端适配层，不属于 `dp` 的核心 contract。

- Codex：以 OpenAI 官方 Codex Skills 文档为准（https://developers.openai.com/codex/skills）
- Claude Code：以 Anthropic 官方 Claude Code Skills 文档为准（https://docs.anthropic.com/en/docs/claude-code/skills）

`scripts/install.py` 只同步 upstream bundle 文件，并保留目标目录中不属于 upstream manifest 的自定义文件。
因此客户端侧补充文件可以与 `dp` 主体共存，不会在常规升级时被误删。

---

## 开发与发布

- 修改运行时模板（`templates/`）时，同时 bump `runtime-lib-version` 和 `bundle-version`
- 只修改文档、脚本、参考资料时，只 bump `bundle-version`
- 发布前运行 `scripts/validate_bundle.py`
- 详细规则见 `CONTRIBUTING.md`

## 依赖

- [DrissionPage](https://github.com/g1879/DrissionPage) `>=4.1.1,<4.2`
- Python 标准库

## License

[MIT](LICENSE)
