# DrissionPage 接口速查

当编写或修改 workflow 脚本，需要快速确认 DrissionPage 常用 API 写法时，读取本文。

本文是面向 `dp` source bundle 的精简速查，不追求覆盖全部 DrissionPage API。
优先使用 `templates/utils.py` 中的 bundled helper；只有 helper 不覆盖当前需求时，
再参考这里直接调用 DrissionPage 接口。

> **适配版本**：本文档以 DrissionPage **4.1.1.x**（已验证 4.1.1.2）为基准。
> 若升级到更高版本，请先检查 `templates/_dp_compat.py` 中标注“依赖 DrissionPage 私有实现”的函数。
> 私有 API（`_browser`、`_download_path`、`_run_cdp` 等）在非 major 版本间也可能静默变动。

## 目录

- [默认交互原则](#默认交互原则)
- [Layer 1：最常用 10 个操作（秒查）](#layer-1最常用-10-个操作秒查)
- [Layer 2：分类接口全集](#layer-2分类接口全集)
  - 导航与页面 / 元素查找 / 元素操作 / 获取元素信息 / 等待 / 截图与保存 / JavaScript / Cookie 与存储
- [Layer 3：高级特性](#layer-3高级特性)
  - 多标签页管理 / 网络请求监听 / 下载管理 / Shadow DOM / iframe 处理 / 弹窗处理 / 浏览器配置

---

本文按渐进披露组织：

- Layer 1：写脚本时最常用的操作
- Layer 2：按类别查具体 API
- Layer 3：只有任务需要时才进入的高级能力

不要在普通点击、输入、上传、下载任务中绕开 bundled helper；helper 已经包含等待链、
跨平台路径处理和 `dp` 的运行时边界。

---

## 默认交互原则

- 优先原生交互和显式等待
- 尽量不要手写 DOM 事件、直接改 `value`、直接改状态
- 点击默认顺序：`ele.wait.clickable()` -> `ele.scroll.to_see()` -> `ele.wait.stop_moving()` -> `ele.wait.not_covered()` -> `ele.click(by_js=False)`
- 输入默认顺序：`ele.scroll.to_see()` -> `ele.wait.clickable()` -> `ele.focus()` -> `ele.clear(by_js=False)` -> `ele.input(text, clear=False, by_js=False)`
- 需要更像真实键入时，优先 `page.actions.type()` / `page.actions.input()`
- JS 更适合只读探测、辅助定位、临时打标；`by_js=True` 和手动派发事件仅最后兜底
- 节奏保持保守：避免高频刷新、无间隔重试、短时间打开过多 tab、短时间扫过多目标

---

## Layer 1：最常用 10 个操作（秒查）

```python
page.get(url)                           # 导航到 URL
page.ele('#id')                         # 按 ID 找元素（内置等待）
page.ele('.class')                      # 按 class 找元素
page.ele('text=精确文本')                # 按文本内容找元素
ele.click(by_js=False)                  # 原生点击
ele.input('文字内容', by_js=False)       # 原生输入
page.get_screenshot(path, name, full_page=True)  # 截图
page.wait.doc_loaded()                  # 等待页面加载完成
page.run_js('return document.title', as_expr=True)  # 执行 JS
[e.text for e in page.eles('css:.item')]  # 批量提取文本
```

---

## Layer 2：分类接口全集

### 导航与页面

```python
# 导航
page.get(url, retry=3, timeout=30)     # 访问 URL，支持重试
page.refresh()                          # 刷新
page.back(steps=1)                      # 后退
page.forward(steps=1)                   # 前进
page.stop_loading()                     # 停止加载

# 页面信息
page.url                                # 当前 URL
page.title                              # 页面标题
page.html                               # 完整 HTML
page.json                               # 响应 JSON（API 页面用）
page.cookies()                          # 获取 cookies
```

### 元素查找

```python
# 单个元素（内置等待，默认 10 秒）
page.ele(locator)                       # 找第一个匹配
page.ele(locator, index=2)             # 找第 N 个
page(locator)                          # 简写形式

# 多个元素
page.eles(locator)                     # 返回列表

# 定位符写法
'#element_id'                          # ID
'.class_name'                          # class（支持 .a.b 多 class）
'tag'                                  # 标签名
'@attr=value'                          # 属性等于
'@attr^=prefix'                        # 属性前缀
'@attr$=suffix'                        # 属性后缀
'@attr*=substr'                        # 属性包含
'text=精确文本'                         # 文本精确匹配
'text^=前缀'                           # 文本前缀
'text*=包含'                           # 文本包含
'xpath://div[@id="x"]'                 # XPath
'css:div.container > p'               # CSS 选择器

# 元素内部查找
ele.ele(locator)                       # 子元素
ele.eles(locator)                      # 所有子元素
ele.parent(level=1)                    # 父元素
ele.child(index=1)                     # 直接子元素
ele.next(index=1)                      # 下一个同级
ele.prev(index=1)                      # 上一个同级
```

### 元素操作

```python
# 点击
ele.click()                            # 模拟点击（自动处理遮挡）
ele.click(by_js=False)                 # 明确要求原生点击
ele.click(by_js=True)                  # JS 点击，仅最后兜底
ele.click.left()                       # 左键
ele.click.right()                      # 右键
ele.click.middle()                     # 中键（返回新标签页对象）
ele.click.multi(times=2)               # 双击

# 输入
ele.focus()                            # 聚焦输入框
ele.input('text', by_js=False)         # 输入（自动清空）
ele.input('text', clear=False, by_js=False)  # 追加输入
ele.clear(by_js=False)                 # 原生清空
page.actions.type('text')              # 模拟逐键输入
page.actions.input('text')             # 快速输入文本

# 表单
ele.check()                            # 勾选复选框
ele.select.by_value('val')             # 下拉框按值选择
ele.select.by_text('显示文字')          # 下拉框按文字选择

# 鼠标
ele.hover()                            # 悬停
ele.drag_to(target_ele)               # 拖拽到元素
ele.drag(offset_x, offset_y)          # 拖拽偏移

# 截图
ele.get_screenshot(path, name)        # 元素截图
```

### 获取元素信息

```python
ele.text                               # 格式化文本
ele.raw_text                           # 原始文本（含空白）
ele.html                               # outerHTML
ele.inner_html                         # innerHTML
ele.tag                                # 标签名
ele.attr('href')                       # 属性值
ele.attrs                              # 所有属性字典
ele.value                              # value 属性
ele.style('color')                     # CSS 样式值
ele.states.is_displayed                # 是否可见
ele.states.is_enabled                  # 是否可用
ele.rect.location                      # 位置坐标
```

### 等待

```python
page.wait.doc_loaded(timeout=30)       # 等待页面加载
page.wait.eles_loaded('.sel', timeout=10)   # 等待元素出现
page.wait.ele_displayed('#id')         # 等待元素显示
page.wait.ele_hidden('#id')            # 等待元素隐藏
page.wait.ele_deleted('#id')           # 等待元素消失
page.wait.url_change(old_url, exclude=True)  # 等待 URL 变化
page.wait.title_change('新标题', exclude=False)  # 等待标题变化
ele.wait.clickable(timeout=10)         # 等待元素可点击
ele.wait.stop_moving(timeout=10)       # 等待元素停止移动
ele.wait.not_covered(timeout=10)       # 等待元素不被遮挡
page.wait(2.5)                         # 固定等待（秒）
page.wait(1, 3)                        # 随机等待 1~3 秒
```

### 截图与保存

```python
# 截图
page.get_screenshot(
    path='./output',           # 目录
    name='shot.png',           # 文件名
    full_page=True,            # 全页 or 可视区
    as_bytes='png',            # 返回字节而非保存
    as_base64='jpg',           # 返回 base64
    left_top=(x1, y1),         # 指定区域
    right_bottom=(x2, y2),
)

# 保存为 PDF
page.save(path='./output', name='page.pdf', as_pdf=True)
```

### JavaScript

```python
page.run_js('return document.title', as_expr=True)  # 返回 JS 表达式结果
page.run_js('arguments[0].click()', ele)            # 传入元素
page.run_js('return arguments[0] + arguments[1]', 1, 2)  # 传入参数
page.add_init_js(script)                            # 页面加载时自动执行

ele.run_js('return this.offsetWidth', as_expr=True)  # 在元素上下文执行
```

### Cookie 与存储

```python
page.cookies()                         # 当前域 cookies
page.cookies(all_domains=True)         # 所有域 cookies
page.set.cookies(cookies_dict)         # 设置 cookies
page.clear_cache(cookies=True)         # 清除缓存
page.local_storage()                   # 获取 localStorage
page.session_storage()                 # 获取 sessionStorage
```

---

## Layer 3：高级特性

### 多标签页管理

```python
page.tab                               # 当前标签页对象
page.tabs_count                        # 标签页数量
page.tab_ids                           # 所有标签页 ID
page.latest_tab                        # 最新激活的标签页

page.new_tab(url)                      # 新建标签页
page.get_tab(title='标题')             # 按标题获取标签页
page.activate_tab(tab_id)              # 激活标签页
page.close_tabs(tab_id)                # 关闭标签页

# 点击链接在新标签页打开
new_tab = ele.click.for_new_tab()
new_tab = ele.click.middle()
tab_id = page.browser.wait.new_tab(timeout=10)
```

### 网络请求监听（ListenerPage）

```python
page.listen.start('api/data')         # 开始监听包含此路径的请求
page.ele('#load-btn').click()
packet = page.listen.wait(timeout=10)  # 等待第一个匹配包
data = packet.response.body           # 获取响应体
page.listen.stop()                    # 停止监听
```

### 下载管理

```python
# 触发下载
ele.click.to_download(
    save_path='./downloads',
    rename='new_name.zip',
)

# 等待下载完成
page.browser.wait.downloads_done(timeout=60)
```

### Shadow DOM

```python
ele.shadow_root                        # 获取 shadow root
ele.sr                                 # 简写
shadow = ele.sr.ele('.inner')          # 在 shadow root 内查找
```

### iframe 处理

```python
frame = page.ele('iframe')            # 获取 iframe 元素
# ChromiumFrame 对象，支持与页面相同的所有操作
frame.ele('#inside')                   # 在 frame 内查找
```

### 弹窗处理

```python
page.handle_alert(accept=True)         # 确认 alert/confirm
page.handle_alert(accept=False)        # 取消 confirm
page.handle_alert(accept=True, send='输入内容')  # prompt 输入
```

### 浏览器配置

```python
from DrissionPage import ChromiumOptions

co = ChromiumOptions()
co.set_headless(True)                  # 无头模式
co.set_user_agent('...')              # 设置 UA
co.set_proxy('http://proxy:8080')     # 设置代理
co.add_extension('/path/to/ext')      # 加载扩展
co.set_argument('--disable-images')   # 浏览器启动参数
co.set_local_port(9222)               # 调试端口
co.existing_only(True)                # 只连接已有浏览器（不新建）
```
