# Workflow 代码模板

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
from utils import native_click, native_input, screenshot, save_json, mark_script_status

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
page.ele("input[type=file]").click.to_upload("/path/to/file.txt")
```
