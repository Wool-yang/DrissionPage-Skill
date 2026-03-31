# 模式选择：ChromiumPage / WebPage / SessionPage

选错对象会导致功能缺失或效率低下。按以下矩阵决策：
除非用户请求明显属于纯请求路径，否则不要把 `SessionPage` 当作默认选项。
若默认 provider 最终为 `cdp-port`，应显式传入测试端口。
通用 workflow 示例默认继承工作区 `default_provider`；客户端或用户可修改 `.dp/config.json`，只有任务明确依赖某个 provider 时才在脚本里固定它。

## 决策矩阵

| 需求特征 | 对象 |
|---|---|
| 需要点击、输入、截图、DOM 交互 | **ChromiumPage**（默认） |
| 已登录浏览器，需要同步 cookies 继续发请求 | **WebPage** |
| 不需要浏览器交互，只要高效 HTTP 请求 | **SessionPage** |

**选不准时用 ChromiumPage**——它功能最全，可随时降级。

如果浏览器由 browser provider 管理，**对象选择规则不变**：
仍然先按任务类型决定是 `ChromiumPage`、`WebPage` 还是 `SessionPage`；
变化的只是连接入口，需要先通过 provider 启动浏览器，再接管返回的调试地址。

---

## ChromiumPage（默认）

**适用**：动态页面、需要点击/输入/截图、JS 渲染内容、需要等待加载

```python
from connect import (
    build_default_browser_profile,
    get_default_browser_provider,
    parse_port,
    start_profile_and_connect_browser,
)

provider = get_default_browser_provider()
browser_profile = build_default_browser_profile(provider, parse_port())
launch_info, page = start_profile_and_connect_browser(provider, browser_profile)
```

---

## WebPage（混合模式）

**适用**：已通过浏览器登录，需要切换到 requests 模式提速，同时保持 cookies

```python
from connect import (
    build_default_browser_profile,
    get_default_browser_provider,
    parse_port,
    start_profile_and_connect_web_page,
)

provider = get_default_browser_provider()
browser_profile = build_default_browser_profile(provider, parse_port())
launch_info, page = start_profile_and_connect_web_page(provider, browser_profile, mode="d")

# 浏览器模式登录
page.get("https://site.com/login")
page.ele("#user").input("user@example.com", by_js=False)
page.ele("#pass").input("password", by_js=False)
page.ele("@type=submit").click(by_js=False)

# 切换到 session 模式（复用已有 cookies，速度更快）
page.change_mode("s")
page.get("https://site.com/api/data")
data = page.json
```

---

## SessionPage（纯请求模式）

**适用**：静态页面、已知接口、无需浏览器、高频批量请求

**注意**：这是少数可以不接管已有浏览器的场景。只在明确不需要 DOM、点击、截图、已登录 cookies 时才用它。

```python
from DrissionPage import SessionPage
page = SessionPage()
page.get("https://api.example.com/data")
data = page.json
```

---

## cookies 同步

```python
# WebPage → 将浏览器 cookies 同步到 session
page.cookies.to_session()

# Session → 将 session cookies 同步到浏览器
page.cookies.to_browser()
```
