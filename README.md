# DrissionPage Skill

**[English](README_EN.md)**

一个面向所有支持 Skill 规范的客户端框架的浏览器自动化 Skill，基于 [DrissionPage](https://github.com/g1879/DrissionPage) 通过 browser provider 获取并接管可连接的 Chromium 调试地址，完成截图、抓取、登录、表单填写、文件上下传等网页自动化任务。

---

## 核心理念

- **Provider-first**：默认先解析 browser provider，再由 provider 返回可连接的调试地址。普通远程调试端口接入也被收编为 `cdp-port` provider。
- **Provider 可扩展**：对 AdsPower 这类指纹浏览器或本地 launcher 浏览器，`dp` 核心只提供 provider contract 和 loader；具体 provider 实现在工作区 `.dp/providers/<name>.py` 中扩展，再统一接入 DrissionPage。
- **复用而非重写**：每个站点的执行脚本会按需沉淀，下次同类任务优先复用，而非重新生成。
- **原生交互优先**：点击和输入使用 DrissionPage 内置的原生链路，不直接操作 DOM 事件，更接近真实用户行为。

## 能做什么

| 任务类型 | 示例 |
|----------|------|
| 截图 | 全页截图、指定区域截图 |
| 抓取 | 列表数据提取、翻页抓取 |
| 登录 | 账号密码登录、保持会话 |
| 表单 | 填写并提交表单 |
| 上传 | 文件上传（input 直接 + 文件选择器） |
| 下载 | 文件下载（含跨平台路径处理） |
| 新标签页 | 打开链接并操作新标签 |
| 混合模式 | 浏览器登录 + requests 高效请求 |
| 指纹浏览器 | 通过工作区 provider 启动或定位浏览器后接管 |

## 安装

### 前置条件

- 任意支持 Skill 规范的客户端框架（例如 Claude Code、Codex，或其他兼容实现）
- Python 3.10+
- 若默认 provider 为 `cdp-port`，需要 Chromium / Chrome 浏览器已开启远程调试端口

### 安装 Skill

```bash
# 克隆仓库
git clone https://github.com/Wool-yang/DrissionPage-Skill.git

# 安装到目标客户端的 skill 目录（示例路径，按实际调整）
python scripts/install.py --target /path/to/skills/dp
```

### 初始化工作区

在你的项目根目录执行，生成 `.dp/` 工作区（含虚拟环境和运行时库）：

```bash
python /path/to/skills/dp/scripts/doctor.py
```

### 开启浏览器远程调试

```bash
# macOS / Linux
google-chrome --remote-debugging-port=<port> --user-data-dir=/tmp/chrome-debug

# Windows（PowerShell）
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=<port> --user-data-dir="$env:TEMP\chrome-debug"
```

通用 workflow 模板默认继承工作区 `.dp/config.json` 中的 `default_provider`。
客户端或用户可以把它改成别的工作区 provider；只有默认值最终为 `cdp-port` 时，才需要显式提供测试端口。

## 使用方式

安装并初始化后，在支持 Skill 的客户端中直接用自然语言描述任务：

> "截一张 https://news.ycombinator.com 的全页截图"
>
> "抓取当前页面的所有商品名称和价格，保存为 JSON"
>
> "帮我登录这个网站，用户名是 xxx"

Skill 会自动：
1. 检测工作区版本，按需升级
2. 解析默认 provider，并通过 provider 获取调试地址
3. 查找已沉淀的同类脚本，优先复用
4. 生成并执行自动化脚本
5. 将输出保存到 `.dp/projects/<site>/output/<task>/<timestamp>/`

如果任务明确依赖某个 provider，客户端或脚本也可以显式固定 provider；通用模板则默认继承工作区默认值。

## 项目结构

```
.
├── SKILL.md                  # Skill 描述文件（供支持 Skill 规范的客户端读取）
├── templates/                # 运行时库（随工作区初始化复制到 .dp/lib/）
│   ├── connect.py            # 浏览器连接 helper
│   ├── download_correlation.py # 单目标下载请求相关性子层
│   ├── output.py             # 输出路径管理
│   ├── utils.py              # 通用操作封装（截图、点击、输入、上传、下载）
│   ├── _dp_compat.py         # DrissionPage 内部 API 兼容层
│   └── providers/
│       └── cdp-port.py       # Runtime-managed fallback provider template
├── scripts/                  # 管理工具
│   ├── doctor.py             # 工作区初始化与健康检测
│   ├── install.py            # Bundle 同步安装
│   ├── list-scripts.py       # 已沉淀脚本枚举
│   ├── smoke.py              # 自动化验收测试
│   ├── test_helpers.py       # 单元测试套件
│   └── validate_bundle.py    # 发布前 bundle 校验
├── references/               # Agent 参考文档
│   ├── workflows.md          # Workflow 代码模板
│   ├── provider-contract.md  # Workspace provider contract
│   ├── mode-selection.md     # 对象选择决策矩阵
│   ├── interface.md          # DrissionPage 接口速查
│   └── site-readme.md        # 站点 README 规范
└── evals/                    # 评测与验收
    ├── evals.json            # 11 个最小 smoke prompts
    └── smoke-checklist.md    # 人工验收清单
```

## 客户端适配与可选补充文件

本仓库只定义 `dp` 的通用 bundle 内容和运行时 contract，不强绑定某一个客户端框架。不同客户端在接入前，**可选**按自身规则在安装目录下补充一些专属文件；这些文件属于客户端侧适配层，不属于 `dp` 的跨客户端核心 contract。

### 1. Codex

Codex 侧的 skill 目录结构、扫描位置、可选元数据文件和调用方式，以 OpenAI 官方文档为准：

- https://developers.openai.com/codex/skills

### 2. Claude Code

Claude Code 侧的 skill 目录、frontmatter 扩展字段和调用规则，以 Anthropic 官方文档为准：

- https://docs.anthropic.com/en/docs/claude-code/skills

### 补充文件的兼容性保证

`scripts/install.py` 只同步 upstream bundle 文件，并保留目标目录下不属于 upstream manifest 的自定义文件；因此客户端侧补充的专属文件可以与 `dp` 主体共存，不会在常规升级时被误删。

## 工作区目录（`.dp/`）

```
.dp/
├── .venv/                    # 自动创建的 Python 虚拟环境
├── lib/                      # 运行时库副本（由 doctor.py 管理）
├── tmp/
│   ├── _run.py               # 当次执行的临时脚本
│   └── _out/                 # 临时输出
├── projects/
│   └── <site-name>/
│       ├── README.md         # 站点索引
│       ├── scripts/          # 沉淀的可复用脚本
│       └── output/           # 按任务和时间戳归档的执行输出
└── state.json                # 版本状态（供 preflight 判断）
```

> `.dp/` 是本机运行时产物，不应提交到版本控制。

## 依赖

- [DrissionPage](https://github.com/g1879/DrissionPage)（`>=4.1.1,<4.2`）：核心浏览器自动化库，本项目的运行时库和工作流设计均基于 DrissionPage 提供的 API。
- Python 标准库（无其他第三方依赖）

## License

[MIT](LICENSE)
