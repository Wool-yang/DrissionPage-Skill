# 模式选择：ChromiumPage / WebPage / SessionPage

当任务不确定该用浏览器对象、混合请求对象还是纯请求对象时，读取本文。

对象选择先看任务性质，再看 provider。Provider 只改变“如何接管浏览器”，
不改变“应该用哪类 DrissionPage 对象”。除非用户请求明显属于纯请求路径，
否则不要把 `SessionPage` 当作默认选项。

若默认 provider 最终为 `cdp-port`，应显式传入测试端口。
通用 workflow 示例默认继承工作区 `default_provider`；客户端或用户可修改 `.dp/config.json`，
只有任务明确依赖某个 provider 时才在脚本里固定它。

## 决策矩阵

| 需求特征 | 对象 | 理由 |
|---|---|---|
| 需要点击、输入、截图、DOM 交互、JS 渲染内容 | **ChromiumPage**（默认） | 功能最完整，符合浏览器自动化默认预期 |
| 已登录浏览器，需要同步 cookies 后继续发请求 | **WebPage** | 保留浏览器登录态，同时可以切到 session 模式提速 |
| 不需要浏览器交互，只要高效 HTTP 请求 | **SessionPage** | 不接管浏览器，适合已知 API 或静态请求 |

选不准时用 **ChromiumPage**。它功能最全，可在任务中发现更轻路径后再降级。

如果浏览器由 browser provider 管理，选择规则不变：
仍然先按任务类型决定是 `ChromiumPage`、`WebPage` 还是 `SessionPage`；
变化的只是连接入口，需要先通过 provider 启动或定位浏览器，再接管返回的调试地址。

---

## ChromiumPage（默认）

适用场景：

- 动态页面
- 需要点击、输入、滚动、截图
- 需要等待 JS 渲染内容
- 需要处理新标签页、上传、下载等浏览器行为

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

适用场景：

- 用户已经在浏览器里登录
- 页面交互只用于建立或复用登录态
- 后续数据更适合通过 requests/session 获取
- 需要同步浏览器 cookies 到请求模式

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

# 浏览器模式登录或确认登录态
page.get("https://site.com/login")
page.ele("#user").input("user@example.com", by_js=False)
page.ele("#pass").input("password", by_js=False)
page.ele("@type=submit").click(by_js=False)

# 切换到 session 模式，复用已有 cookies
page.change_mode("s")
page.get("https://site.com/api/data")
data = page.json
```

---

## SessionPage（纯请求模式）

适用场景：

- 静态页面
- 已知 API
- 已有 cookies / token
- 无需 DOM、点击、截图、JS 渲染或当前浏览器登录态

注意：这是少数可以不接管已有浏览器的场景。只在明确不需要浏览器能力时才用它。

```python
from DrissionPage import SessionPage

page = SessionPage()
page.get("https://api.example.com/data")
data = page.json
```

---

## Cookies 同步

```python
# WebPage -> 将浏览器 cookies 同步到 session
page.cookies.to_session()

# Session -> 将 session cookies 同步到浏览器
page.cookies.to_browser()
```
