# Workflow Discovery

当任务目标是建立、修复或判断可复用站点 workflow，且已有脚本、README 或历史输出无法提供高置信路径时，读取本文。

Workflow discovery 的目标是快速建立站点 workflow 模型：入口、前置状态、关键步骤、状态验证、输出契约和可复用脚本边界。它位于截图、抓取、登录等 action template 之上，用来判断这些动作如何组合成稳定流程。

## 触发矩阵

| 场景 | 先做 discovery 的原因 | 下一步 |
|---|---|---|
| 需要沉淀新站点 workflow，且没有 `.dp/projects/<site>/scripts/` | 没有可复用路径 | 探测页面结构和稳定选择器 |
| 只有 workflow_summary 文本相近，入口或输出契约无法确认 | 复用置信度低 | 读取旧脚本，再验证入口、状态和选择器 |
| 用户要求把一次操作变成可复用 workflow | 需要沉淀标准 | 先确认步骤、状态验证和输出契约 |
| 旧脚本 `status: broken` 且失败原因不清 | 直接重写会丢失历史经验 | 对比旧选择器、当前 DOM 和失败状态 |
| 可复用 workflow 依赖多模块、弹窗、iframe、分页或导出动作，且状态机不清楚 | 页面状态机不清楚 | 小步探测交互和状态变化 |

轻量截图、简单导航、已有稳定脚本的直接复用，不需要先跑完整 discovery。

## 产物契约

Discovery 产物按用途分层：

- `.dp/tmp/_workflow_discovery_<site>_<intent>.py`：可重复运行的临时探测脚本
- `.dp/tmp/_out/`：一次性 scratch 输出，不作为证据真源
- `.dp/projects/<site>/output/workflow-discovery-<intent>/<timestamp>/`：本次 discovery evidence 真源
- `.dp/projects/<site>/workflow-drafts/<intent>.md`：可选站点级索引，只保存稳定结论和 evidence run-dir 链接

每次非平凡 discovery 的 run-dir 中至少建议包含 `entry.png`、`dom-summary.json` 和
`workflow-draft.md`。`workflow-draft.md` 建议包含：

- 入口 URL 和前置状态，例如登录、筛选器、默认 tab、权限范围
- 页面结构摘要：主要区域、列表/表格、表单、按钮、分页、弹窗、iframe
- 候选选择器和选择依据
- 关键交互步骤和状态验证点
- 输出契约：文件名、字段、下载名、截图名或参数
- 是否达到沉淀条件，以及还缺什么

## 探测流程

1. 连接浏览器，确认当前 URL、title、登录态和入口状态。
2. 用只读 DOM 探测收集页面结构，不先写破坏性点击逻辑。
3. 读取已有脚本和 README 托管区，识别可能复用的入口、选择器和输出。
4. 对关键控件做小步交互探测，每步保存 before/after 状态。
5. 明确成功、失败、空数据、加载中、权限不足等状态的判断方式。
6. 将 `workflow-draft.md` 写入 discovery run-dir，再决定复用、修复、新建或沉淀脚本。

## 只读 DOM 探测

优先用 JS 做只读结构摘要，避免在未知页面上直接执行点击、提交或下载：

```python
summary = page.run_js("""
const pick = (el) => ({
  tag: el.tagName.toLowerCase(),
  text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 120),
  id: el.id || '',
  cls: Array.from(el.classList || []).slice(0, 5).join('.'),
  name: el.getAttribute('name') || '',
  role: el.getAttribute('role') || '',
  testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || '',
  href: el.getAttribute('href') || '',
  type: el.getAttribute('type') || ''
});
return {
  url: location.href,
  title: document.title,
  forms: Array.from(document.querySelectorAll('form')).slice(0, 20).map(pick),
  buttons: Array.from(document.querySelectorAll('button,[role=button],input[type=button],input[type=submit]')).slice(0, 80).map(pick),
  links: Array.from(document.querySelectorAll('a[href]')).slice(0, 80).map(pick),
  inputs: Array.from(document.querySelectorAll('input,textarea,select')).slice(0, 80).map(pick),
  tables: Array.from(document.querySelectorAll('table')).slice(0, 20).map(t => ({
    text: (t.innerText || '').trim().slice(0, 300),
    rows: t.rows ? t.rows.length : null
  })),
  iframes: Array.from(document.querySelectorAll('iframe')).map(pick)
};
""")
```

保存摘要时使用语义名称，例如 `dom-summary.json`、`buttons.json`、`forms.json`。

## 交互探测

交互探测只覆盖理解 workflow 必需的最小步骤：

- 每个关键动作前先截图或保存 `state-before.json`
- 点击/输入使用 `native_click()` / `native_input()`，不要把 JS click 当主路径
- 动作后等待 URL、标题、DOM 节点、按钮状态、toast、表格行数或下载事件变化
- 每个动作后保存 `state-after.json` 或截图，记录验证依据
- 高风险动作、不可逆提交、发帖、支付、删除必须先向用户确认

状态验证示例：

```python
before_url = page.url
native_click(page.ele("css:button.search"))
page.wait.doc_loaded()
changed = {
    "url_changed": page.url != before_url,
    "title": page.title,
    "rows": len(page.eles("css:table tbody tr")),
}
save_json(changed, run / "state-after-search.json")
```

## 导出探测

导出、下载、批量保存等动作先判断触发方式，不要把 `download_file()` 扩展成批量编排 helper：

- 单个明确按钮触发单个文件：使用 `download_file()`，文件落在当前 run-dir
- 多个文件或多步骤导出：外层 workflow 编排多个单目标步骤，共享同一个 `run_dir`
- 点击后新标签页生成文件：先完成新标签页切换，再触发下载
- 页面异步生成任务：先记录任务状态、轮询条件和最终文件入口

导出探测至少记录：

- 触发元素候选选择器
- 是否打开新 tab、弹窗或后台任务
- 文件名能否预测，是否需要语义重命名
- 完成状态如何判断

## 选择器优先级

候选选择器按稳定性排序：

1. 业务语义属性：`data-testid`、`data-test`、`data-cy`、稳定 `name`
2. 可访问性语义：`role`、`aria-label`、label 文本与字段关联
3. 稳定表头、按钮文本、链接文本与附近区域限定
4. 稳定 URL、表单结构、字段顺序作为辅助
5. CSS class 仅在明显稳定时使用
6. 深层绝对 XPath、自动生成 class、动态 id 只作为临时探测，不进入沉淀脚本主路径

记录选择器时要同时记录 fallback，例如：

```md
- 搜索按钮：`button[data-testid=search]`
  - fallback: `xpath://button[contains(., "Search") or contains(., "查询")]`
  - 验证：点击后结果表格行数变化或出现空状态提示
```

## 诊断表

| 现象 | 优先检查 | 常见处理 |
|---|---|---|
| `.text` 为空但页面可见 | iframe、shadow DOM、canvas、虚拟列表 | 列出 iframe，检查可访问 DOM；必要时截图辅助定位 |
| 选择器命中 0 个元素 | 页面未加载、tab 不对、权限不足、选择器太脆弱 | 保存 URL/title/screenshot，等待稳定节点后重试 |
| 点击无效果 | 元素被遮挡、未滚动到可见、禁用态、点击目标是子元素 | 使用原生点击等待链，记录 disabled/covered 状态 |
| 表格行数不稳定 | 虚拟滚动、分页、筛选条件、异步加载 | 记录加载标志和总数元素，避免固定 sleep |
| iframe 内控件不可见 | 当前上下文不在 iframe | 记录 iframe 列表和 src，再切换到正确上下文 |
| 导出没有文件 | 异步任务、新 tab、权限弹窗、浏览器下载目录不可用 | 先识别触发链路，再决定单目标下载或外层编排 |

## 沉淀检查清单

只有同时满足以下条件，才把 discovery 结果沉淀为 `.dp/projects/<site>/scripts/<name>.py`：

- 有稳定入口 URL 或可复用的当前页面前置条件
- 已确认关键步骤、等待条件和状态验证点
- 输出契约明确，且同一次 run 只使用一个 run-dir
- 选择器有主路径和必要 fallback，避免依赖动态 id 或深层绝对 XPath
- 脚本使用 provider-first 连接和 bundled helper，不复制 helper 实现
- 脚本至少成功运行一次，并用 `mark_script_status("ok")` 回写状态
- 站点 README 只更新托管 `## Scripts` 区；discovery 证据仍保留在 run-dir 的 `workflow-draft.md`

## 紧凑骨架

```python
"""
site: <site-name>
workflow_summary: discover reusable workflow for <intent>
intent: workflow-discovery-<intent>
url: <entry-url>
tags: discovery
created: YYYY-MM-DD
updated: YYYY-MM-DD
last_run:
status:
usage: python .dp/tmp/_workflow_discovery_<site>_<intent>.py [--port <port>]
"""
import sys
from pathlib import Path

def _load_dp_lib(start: Path) -> None:
    for base in (start.resolve().parent, *start.resolve().parents):
        for lib in (base / "lib", base / ".dp" / "lib"):
            if (lib / "connect.py").exists() and (lib / "output.py").exists():
                sys.path.insert(0, str(lib))
                return
    raise RuntimeError("未找到 .dp/lib，请先运行 doctor.py 初始化工作区。")

_load_dp_lib(Path(__file__))
from connect import (
    build_default_browser_profile,
    get_default_browser_provider,
    parse_port,
    start_profile_and_connect_browser,
)
from output import site_run_dir
from utils import save_json, screenshot

SITE = "<site-name>"
SCRIPT_NAME = "workflow-discovery-<intent>"
ENTRY_URL = "<entry-url>"

PROVIDER = get_default_browser_provider()
BROWSER_PROFILE = build_default_browser_profile(PROVIDER, parse_port())
launch_info, page = start_profile_and_connect_browser(PROVIDER, BROWSER_PROFILE)

run = site_run_dir(SITE, SCRIPT_NAME)
if ENTRY_URL:
    page.get(ENTRY_URL)
page.wait.doc_loaded()

screenshot(page, run / "entry.png")
summary = page.run_js("""
return {
  url: location.href,
  title: document.title,
  buttons: Array.from(document.querySelectorAll('button,[role=button],a,input')).slice(0, 80).map(el => ({
    tag: el.tagName.toLowerCase(),
    text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 120),
    id: el.id || '',
    name: el.getAttribute('name') || '',
    role: el.getAttribute('role') || '',
    testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || '',
    href: el.getAttribute('href') || ''
  }))
};
""")
save_json(summary, run / "dom-summary.json")
(run / "workflow-draft.md").write_text(
    "# Workflow Draft\n\n"
    f"- evidence_run: {run}\n"
    f"- entry_url: {summary.get('url', '')}\n"
    f"- title: {summary.get('title', '')}\n\n"
    "## Structure\n\n"
    "- Fill in key regions, selectors, state checks, and output contract before saving a workflow.\n",
    encoding="utf-8",
)
print(f"[dp] discovery output -> {run}")
```
