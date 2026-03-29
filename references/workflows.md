# Workflow 代码模板

## 目录

- [默认交互约束](#默认交互约束)
- [通用脚本头](#通用脚本头每个脚本必须有)
- [Workflow 1：截图 screenshot](#workflow-1截图screenshot)
- [Workflow 2：数据抓取 scrape](#workflow-2数据抓取scrape)
- [Workflow 3：自动登录 login](#workflow-3自动登录login)
- [Workflow 4：表单填写 form](#workflow-4表单填写form)
- [Workflow 5：文件上传 upload](#workflow-5文件上传upload)
- [Workflow 6：文件下载 download](#workflow-6文件下载download)
- [Workflow 7：新标签页 new-tab](#workflow-7新标签页new-tab)
- [Workflow 8：WebPage cookie 同步 web-page-sync](#workflow-8webpage-cookie-同步web-page-sync)
- [Workflow 9：自定义多步任务 custom](#workflow-9自定义多步任务custom)

---

每种 workflow 都包含完整的独立脚本（含连接逻辑），可直接写入 `.dp/tmp/_run.py` 执行。
本文件里的"通用脚本头"是 canonical 骨架。客户端消费这个 source bundle 时，应直接复用它，而不是自行改写 helper 的导入与路径策略。

---

## 默认交互约束

- 所有模板默认走原生交互和显式等待，不把 JS 点击、直接改 `value`、手动派发事件当主流程
- 点击优先：`wait.clickable()` -> `scroll.to_see()` -> `wait.stop_moving()` -> `wait.not_covered()` -> `click(by_js=False)`
- 输入优先：`scroll.to_see()` -> `wait.clickable()` -> `focus()` -> `clear(by_js=False)` -> `input(..., by_js=False)`
- 滚动 / 悬停 / 拖拽 / 上传 / 下载 / 新标签优先使用 DrissionPage 内置能力
- 批量抓取、翻页、重试、刷新都要保守，避免高频无间隔操作

---

## 通用脚本头（每个脚本必须有）

```python
"""
site: <site-name>
task: <一句话描述>
intent: <短标签，1-3 词，如 scrape-orders / login-sso / screenshot-full>
         # 推荐参考词：screenshot, scrape, login, form；新场景自然扩展，不强制枚举
url: <目标 URL 或路径前缀，可选>
tags: <逗号分隔关键词，可选>
created: YYYY-MM-DD
updated: YYYY-MM-DD
last_run:
status:
usage: python scripts/<name>.py [--port 9222]
"""
import sys
from pathlib import Path

# 自动查找 .dp/lib，兼容临时脚本和已保存脚本两种位置
def _load_dp_lib(start: Path) -> None:
    for base in (start.resolve().parent, *start.resolve().parents):
        for lib in (base / "lib", base / ".dp" / "lib"):
            if (lib / "connect.py").exists() and (lib / "output.py").exists():
                sys.path.insert(0, str(lib))
                return
    raise RuntimeError("未找到 .dp/lib，请先运行 doctor.py 初始化工作区。")


_load_dp_lib(Path(__file__))
from connect import connect_browser, parse_port
from output import site_run_dir
from utils import native_click, native_input, screenshot, save_json, mark_script_status, upload_file, download_file

page = connect_browser(parse_port())
```

---

## Workflow 1：截图（screenshot）

**触发词**：截图、快照、snapshot、保存页面

```python
# ── 接通用脚本头 ──

# 配置
SITE = "site-name"          # 替换为实际 site-name
FULL_PAGE = True            # False = 仅可视区域

# 执行
try:
    run = site_run_dir(SITE, "screenshot")
    page.wait.doc_loaded()
    out = run / "full.png"
    page.get_screenshot(path=str(run), name=out.name, full_page=FULL_PAGE)
    print(f"[dp] 截图 → {out}")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
```

**变体**：
- 截取特定元素：`ele.get_screenshot(path=str(run), name="element.png")`
- 截取指定区域：`page.get_screenshot(left_top=(x1,y1), right_bottom=(x2,y2), path=str(run), name="region.png")`
- 保存为 PDF：`page.save(path=str(run), name="page.pdf", as_pdf=True)`

---

## Workflow 2：数据抓取（scrape）

**触发词**：抓取、爬取、提取、获取数据、extract

```python
# ── 接通用脚本头 ──

# 配置
SITE = "site-name"          # 替换为实际 site-name
URL = "https://..."         # 目标 URL（如果需要导航）
SELECTOR = "css:selector"   # 元素选择器，替换为实际值

# 执行
try:
    run = site_run_dir(SITE, "scrape")
    # page.get(URL)  # 如需导航，取消注释
    page.wait.doc_loaded()

    results = []
    for ele in page.eles(SELECTOR):
        results.append({
            "text": ele.text,
            "href": ele.attr("href"),
            # 按需添加其他字段
        })

    save_json(results, run / "data.json")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
```

**常用选择器参考**：
```python
page.eles("css:.title a")          # CSS 选择器
page.eles("xpath://div[@class='item']")  # XPath
page.eles("text^=关键字")           # 文本前缀匹配
page.eles("@data-id")              # 含某属性的元素
```

---

## Workflow 3：自动登录（login）

**触发词**：登录、login、sign in、认证

```python
# ── 接通用脚本头 ──

# 配置（替换为实际值）
SITE = "site-name"
LOGIN_URL = "https://example.com/login"
USERNAME_SEL = "#username"     # 用户名输入框选择器
PASSWORD_SEL = "#password"     # 密码输入框选择器
SUBMIT_SEL = "@type=submit"    # 提交按钮选择器
USERNAME = "your_username"     # 建议从环境变量读取
PASSWORD = "your_password"     # 建议从环境变量读取

# 执行
try:
    run = site_run_dir(SITE, "login")
    page.get(LOGIN_URL)
    page.wait.doc_loaded()

    native_input(page.ele(USERNAME_SEL), USERNAME)
    native_input(page.ele(PASSWORD_SEL), PASSWORD)
    native_click(page.ele(SUBMIT_SEL))

    # 等待登录成功（URL 发生变化）
    try:
        page.wait.url_change(LOGIN_URL, exclude=True, timeout=15)
        print(f"[dp] 登录成功 → {page.url}")
        screenshot(page, run / "result.png")
    except Exception:
        print(f"[dp] 登录超时，当前页面：{page.title}")
        screenshot(page, run / "timeout.png")

    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
```

**安全建议**：账号密码建议通过环境变量传入，不硬编码在脚本中：
```python
import os
USERNAME = os.environ.get("DP_USERNAME", "")
PASSWORD = os.environ.get("DP_PASSWORD", "")
```

---

## Workflow 4：表单填写（form）

**触发词**：填写表单、填充、提交、form、submit

```python
# ── 接通用脚本头 ──

# 配置（替换为实际值）
SITE = "site-name"
# 字段定义：[(选择器, 值), ...]
FIELDS = [
    ("#field1", "value1"),
    ("#field2", "value2"),
    # 更多字段...
]
SUBMIT_SEL = "@type=submit"

# 执行
try:
    run = site_run_dir(SITE, "form")
    page.wait.doc_loaded()

    for selector, value in FIELDS:
        ele = page.ele(selector)
        native_input(ele, value)

    native_click(page.ele(SUBMIT_SEL))
    page.wait.doc_loaded()
    print(f"[dp] 表单已提交 → {page.title} ({page.url})")
    screenshot(page, run / "result.png")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
```

**表单特殊控件**：
```python
# 下拉选择框
page.ele("select#lang").select.by_value("zh")
page.ele("select#lang").select.by_text("中文")

# 复选框 / 单选框
page.ele("#agree").click()  # 或 .check()

# 文件上传
upload_file(page.ele("input[type=file]"), "/path/to/file.txt")
```

---

## Workflow 5：文件上传（upload）

**触发词**：上传、upload、file input

```python
# ── 接通用脚本头 ──

# 配置（替换为实际值）
SITE = "site-name"
FILE_PATH = "/absolute/path/to/file.txt"   # 要上传的本地文件（调用方提供，不进 run-dir）
FILE_INPUT_SEL = "input[type=file]"        # 文件 input 选择器

# 执行
try:
    run = site_run_dir(SITE, "upload")
    # 被上传文件视为外部输入，不复制进 run-dir
    upload_file(page.ele(FILE_INPUT_SEL), FILE_PATH)
    # run-dir 只保存执行中生成的产物（确认截图等）
    screenshot(page, run / "result.png")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
```

**contract**：
- 被上传文件视为外部输入，**不放入 run-dir**
- run-dir 只保存确认截图或结果元数据等执行产物
- 对直接 `input[type=file]`，优先 `upload_file()`；它会处理跨平台路径
  （例如 WSL Python 接管 Windows Chromium 时的 `/mnt/<drive>/...` 与 `\\wsl$\\...`）

---

## Workflow 6：文件下载（download）

**触发词**：下载、download、保存文件

```python
# ── 接通用脚本头 ──

# 配置（替换为实际值）
SITE = "site-name"
DOWNLOAD_SEL = "#download-btn"   # 下载触发元素选择器
FILENAME = "data.csv"            # 语义文件名；无法预判时用 None 保留原始名

# 执行
try:
    run = site_run_dir(SITE, "download")
    ele = page.ele(DOWNLOAD_SEL)
    saved = download_file(
        ele,
        run,
        rename=FILENAME,         # 有语义名时重命名；None 则保留原始文件名
    )
    # download_file() 内部已等待完成，禁止在其后再调用下载管理器等待方法
    # （raw-CDP 分支未注册下载管理器，调用会立即报错）
    print(f"[dp] 下载完成 → {saved}")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
```

**contract**：
- 下载文件落到**当前 run-dir**
- 同一次任务只有一个 run-dir
- 文件名优先使用语义名；无法预判时保留原始文件名
- 对下载目录优先使用 `download_file()`
  - 同 OS 场景优先走 DrissionPage 自带下载管理
  - 跨 OS 场景或 DP 下载失败时，再 fallback 到 raw CDP 下载目录策略
  - `download_file()` 三条分支均自带等待逻辑，返回时文件已落盘；**禁止**在其后再调用下载管理器的等待方法（raw-CDP 分支未注册到下载管理器，调用会立即报错）
- 对 `data:` 直链下载可优先本地直存，减少对浏览器下载事件的依赖

---

## Workflow 7：新标签页（new-tab）

**触发词**：新标签页、新 tab、target=\_blank

```python
# ── 接通用脚本头 ──

# 配置（替换为实际值）
SITE = "site-name"
LINK_SEL = "a[target='_blank']"  # 触发新标签页的链接选择器

# 执行
try:
    run = site_run_dir(SITE, "newtab")      # 整个任务只用这一个 run-dir
    screenshot(page, run / "before.png")    # 可选：记录原页面状态

    new_tab = page.ele(LINK_SEL).click.for_new_tab()
    # 备选：tab_id = page.browser.wait.new_tab(timeout=10)
    #        new_tab = page.get_tab(tab_id)

    new_tab.wait.doc_loaded()
    screenshot(new_tab, run / "newtab.png")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
```

**contract**：
- 标签页切换**不创建新 run-dir**
- 父页面和新标签页的所有输出落入同一 run-dir
- 文件名语义化区分步骤（`before.png`、`newtab.png` 等）

---

## Workflow 8：WebPage cookie 同步（web-page-sync）

**触发词**：复用登录态、同步 cookies、WebPage、requests 模式、不走页面点击

```python
"""
site: <site-name>
task: <一句话描述>
intent: web-page-sync
url: <目标 API URL>
tags: <可选>
created: YYYY-MM-DD
updated: YYYY-MM-DD
last_run:
status:
usage: python scripts/<name>.py [--port 9222]
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
from connect import connect_web_page, parse_port
from output import site_run_dir
from utils import save_json, mark_script_status

# 配置（替换为实际值）
SITE = "site-name"
API_URL = "https://example.com/api/data"

try:
    run = site_run_dir(SITE, "web-page-sync")
    page = connect_web_page(parse_port())   # WebPage，默认 'd'（浏览器）模式
    page.change_mode('s')                  # 切换到 session 模式，自动同步浏览器 cookies
    page.get(API_URL)
    save_json(page.json, run / "data.json")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
```

**何时用 WebPage**：用户已在浏览器登录，希望复用当前 cookies 通过 requests 高效抓取接口数据，而不是继续走页面点击。connect_browser() 不能切换模式；需要 session 模式时必须用 connect_web_page()。

---

## Workflow 9：自定义多步任务（custom）

**触发词**：多步、multi-step，或任何无法映射到单一内置意图的复合任务

```python
# ── 接通用脚本头 ──

# 配置
SITE = "site-name"

# 执行（示例：截图列表 → 点进详情 → 提取数据）
try:
    run = site_run_dir(SITE, "custom")      # 整个任务只创建一个 run-dir

    # 步骤 1
    page.wait.doc_loaded()
    screenshot(page, run / "list.png")

    # 步骤 2
    native_click(page.ele("css:.item:first-child"))
    page.wait.doc_loaded()
    screenshot(page, run / "detail.png")

    # 步骤 3
    save_json({"title": page.title, "url": page.url}, run / "detail.json")

    print(f"[dp] 完成，输出 → {run}")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
```

**contract**：
- 多步骤产生的所有输出落入**同一 run-dir**（整个任务只调用一次 `site_run_dir()`）
- 文件名用语义名称区分步骤（`list.png`、`detail.png`、`detail.json` 等）

---

## 三级复用判断边界示例

在使用 `scripts/list-scripts.py` 检索已有脚本后，按以下优先级判断是否复用：

| 优先级 | 匹配条件 | 置信度 | 推荐操作 |
|---|---|---|---|
| 1 | site + intent 精确匹配 | 高 | 直接复用，无需询问 |
| 2 | url 前缀匹配（同站点同路径） | 中 | 读取脚本后决定复用或微调 |
| 3 | task 语义相近 | 低 | 优先生成临时脚本，或先读旧脚本再改 |

**边界原则**：

- `site + intent` 是强匹配信号，匹配时直接静默复用
- `url` 前缀匹配区分同站点不同子场景，匹配时读脚本后再判断
- `task` 语义判断是最后兜底；**低置信度时不要盲复用**——优先生成临时脚本，或先读旧脚本再改
- `status: broken` 的脚本优先修复再复用，而非新建

**示例**：

```python
# 场景 A：site=hn, intent=scrape，已有 scrape-top.py → 直接复用
# 场景 B：同站点但 url 从 "/" 变为 "/item?id=xxx" → url 不匹配，生成新脚本
# 场景 C：task 描述与旧脚本语义相近但不精确 → 生成临时脚本，验证后再沉淀
```
