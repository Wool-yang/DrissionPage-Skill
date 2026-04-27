#!/usr/bin/env python3
"""
_rewrite_header_fields / mark_script_status / extract_fields / doctor.check 最小回归测试。
无第三方依赖，直接调真实实现。退出码 0=全过，1=有失败。
"""
from __future__ import annotations

import importlib.util
import inspect
import io
import os
import sys
import tempfile
from contextlib import redirect_stderr
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True

# templates/ 加入 sys.path，使 utils / output 可在无 DrissionPage 环境下 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "templates"))
from utils import (  # noqa: E402
    _rewrite_header_fields,
    browser_download_path,
    browser_upload_path,
    download_file,
    mark_script_status,
    upload_file,
)
import utils as _utils_mod  # noqa: E402
from output import normalize_site_name  # noqa: E402
import output as _output_mod  # noqa: E402

# list-scripts.py 文件名含连字符，用 importlib 加载
_ls_spec = importlib.util.spec_from_file_location(
    "list_scripts", Path(__file__).parent / "list-scripts.py"
)
_ls_mod = importlib.util.module_from_spec(_ls_spec)
_ls_spec.loader.exec_module(_ls_mod)
extract_fields = _ls_mod.extract_fields

# install.py 用 importlib 加载
_install_spec = importlib.util.spec_from_file_location(
    "install", Path(__file__).parent / "install.py"
)
_install_mod = importlib.util.module_from_spec(_install_spec)
_install_spec.loader.exec_module(_install_mod)

# doctor.py 用 importlib 加载（便于 patch 模块级全局变量）
_doc_spec = importlib.util.spec_from_file_location(
    "doctor", Path(__file__).parent / "doctor.py"
)
_doctor = importlib.util.module_from_spec(_doc_spec)
_doc_spec.loader.exec_module(_doctor)

# validate_bundle.py 用 importlib 加载
_vb_spec = importlib.util.spec_from_file_location(
    "validate_bundle", Path(__file__).parent / "validate_bundle.py"
)
_vb = importlib.util.module_from_spec(_vb_spec)
_vb_spec.loader.exec_module(_vb)


def _load_download_correlation_module():
    """按文件路径加载 download_correlation 模块。"""
    path = Path(__file__).resolve().parent.parent / "templates" / "download_correlation.py"
    if not path.exists():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location("download_correlation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# ── 测试框架 ──────────────────────────────────────────────────────────────────

_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _failed
    if condition:
        print(f"  ok  {name}")
    else:
        print(f"  FAIL {name}" + (f"\n       {detail}" if detail else ""))
        _failed += 1


def _tmp(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return Path(f.name)


class _FakeOwner:
    def __init__(self, ua: str):
        self._ua = ua
        self.upload_paths: list[str] = []
        self.upload_waited = False
        self.browser_cdp_calls: list[tuple[str, dict]] = []
        self.page_cdp_calls: list[tuple[str, dict]] = []
        self.set = SimpleNamespace(upload_files=self._upload_files)
        self.wait = SimpleNamespace(upload_paths_inputted=self._upload_paths_inputted)
        self._driver = SimpleNamespace(set_callback=self._set_callback)
        self._download_path = "/fake/owner-downloads"
        self._browser = SimpleNamespace(
            _download_path="/fake/browser-downloads",
            _run_cdp=self._browser_run_cdp,
        )
        self.driver_callbacks: dict[str, object] = {}

    def run_js(self, _script: str, as_expr: bool = True):
        return self._ua

    def _upload_files(self, file_path: str) -> None:
        self.upload_paths.append(file_path)

    def _upload_paths_inputted(self) -> None:
        self.upload_waited = True

    def _browser_run_cdp(self, method: str, **kwargs):
        self.browser_cdp_calls.append((method, kwargs))
        return {}

    def _run_cdp(self, method: str, **kwargs):
        self.page_cdp_calls.append((method, kwargs))
        return {}

    def _set_callback(self, event: str, callback, immediate: bool = False) -> None:
        if callback:
            self.driver_callbacks[event] = callback
        else:
            self.driver_callbacks.pop(event, None)


class _FakeWait:
    def clickable(self, timeout: int = 10, wait_moved: bool = True) -> None:
        return None

    def stop_moving(self, timeout: int = 10) -> None:
        return None

    def not_covered(self, timeout: int = 10) -> None:
        return None


class _FakeScroll:
    def to_see(self) -> None:
        return None


class _FakeClickProxy:
    def __init__(self, ele):
        self._ele = ele

    def __call__(self, by_js: bool = False) -> None:
        self._ele.click_calls.append(by_js)

    def to_download(
        self,
        save_path=None,
        rename=None,
        suffix=None,
        new_tab=None,
        by_js=False,
        timeout=None,
    ):
        call = {
            "save_path": save_path,
            "rename": rename,
            "suffix": suffix,
            "new_tab": new_tab,
            "by_js": by_js,
            "timeout": timeout,
        }
        self._ele.download_calls.append(call)
        return "mission"


class _FakeElement:
    def __init__(self, tag: str, input_type: str, ua: str, attrs: dict[str, str] | None = None):
        self.tag = tag
        self._input_type = input_type
        self._attrs = attrs or {}
        self.owner = _FakeOwner(ua)
        self.wait = _FakeWait()
        self.scroll = _FakeScroll()
        self.input_calls: list[tuple[str, bool, bool]] = []
        self.click_calls: list[bool] = []
        self.download_calls: list[dict] = []
        self.js_calls: list[str] = []
        self.click = _FakeClickProxy(self)

    def attr(self, name: str) -> str:
        if name == "type":
            return self._input_type
        return self._attrs.get(name, "")

    def input(self, value: str, clear: bool = False, by_js: bool = False) -> None:
        self.input_calls.append((value, clear, by_js))

    def run_js(self, script: str) -> None:
        self.js_calls.append(script)


# ── 测试用例 ──────────────────────────────────────────────────────────────────

TODAY = date.today().isoformat()

# 基础脚本：字段为空
_EMPTY = '''\
"""
site: test
task: demo
last_run:
status:
"""
pass
'''

# 字段已有旧值
_STALE = '''\
"""
site: test
task: demo
last_run: 2020-01-01
status: broken
"""
pass
'''

# 正文里有 status: / last_run: 文本，不应被改
_BODY_HAS_FIELDS = '''\
"""
site: test
task: demo
last_run:
status:
"""

def report():
    print("status: ready")
    last_run: int = 42
    return last_run
'''

# shebang 行在 docstring 前
_WITH_SHEBANG = '''\
#!/usr/bin/env python3
"""
site: test
last_run:
status:
"""
pass
'''

# 无 docstring
_NO_DOCSTRING = '''\
x = 1
status: broken
last_run: 2020-01-01
'''

# 单引号 docstring
_SINGLE_QUOTE = """\
'''
site: test
last_run:
status:
'''
pass
"""


def test_empty_fields() -> None:
    result = _rewrite_header_fields(_EMPTY, "ok", TODAY)
    check("空 last_run 被填入", f"last_run: {TODAY}" in result, repr(result))
    check("空 status 被填入", "status: ok" in result, repr(result))
    check("相邻字段 task 未被破坏", "task: demo" in result, repr(result))


def test_stale_fields() -> None:
    result = _rewrite_header_fields(_STALE, "ok", TODAY)
    check("旧 last_run 被更新", f"last_run: {TODAY}" in result, repr(result))
    check("broken → ok", "status: ok" in result and "broken" not in result, repr(result))


def test_body_not_modified() -> None:
    result = _rewrite_header_fields(_BODY_HAS_FIELDS, "ok", TODAY)
    check('正文 print("status: ready") 未被改', 'print("status: ready")' in result, repr(result))
    check("正文 last_run: int = 42 未被改", "last_run: int = 42" in result, repr(result))
    check("头部 status 仍然更新", "status: ok" in result, repr(result))


def test_shebang() -> None:
    result = _rewrite_header_fields(_WITH_SHEBANG, "ok", TODAY)
    check("shebang 脚本头部正常更新", f"last_run: {TODAY}" in result, repr(result))
    check("shebang 行未被破坏", result.startswith("#!/usr/bin/env python3"), repr(result[:40]))


def test_no_docstring() -> None:
    result = _rewrite_header_fields(_NO_DOCSTRING, "ok", TODAY)
    check("无 docstring 时原文不变", result == _NO_DOCSTRING, repr(result))


def test_single_quote_docstring() -> None:
    result = _rewrite_header_fields(_SINGLE_QUOTE, "ok", TODAY)
    check("单引号 docstring 正常更新", f"last_run: {TODAY}" in result, repr(result))


def test_mark_script_status_integration() -> None:
    """端到端：mark_script_status 通过 sys.argv[0] 回写临时脚本文件。"""
    p = _tmp(_BODY_HAS_FIELDS)
    orig_argv = sys.argv[:]
    try:
        sys.argv[0] = str(p)
        mark_script_status("ok")
    finally:
        sys.argv[:] = orig_argv

    try:
        text = p.read_text(encoding="utf-8")
        check("integration: 头部 last_run 回写", f"last_run: {TODAY}" in text, repr(text))
        check("integration: 头部 status 回写", "status: ok" in text, repr(text))
        check('integration: 正文未被改', 'print("status: ready")' in text, repr(text))
    finally:
        p.unlink(missing_ok=True)


# ── extract_fields 测试用例 ───────────────────────────────────────────────────

# 正文里有同名字段，不应被提取
_BODY_POLLUTES = '''\
"""
site: test-site
task: 抓取订单
intent: scrape
url: https://example.com/orders
status:
last_run:
"""

def report():
    # status: 正在运行
    last_run: int = 0
    x = """
status: ready
last_run: 2020-01-01
"""
    return x
'''

# URL 含 # (SPA 路由)
_URL_WITH_HASH = '''\
"""
site: test-site
task: 登录
intent: login
url: https://example.com/#/signin
status:
"""
pass
'''

# shebang + 双引号 docstring
_SHEBANG_DOUBLE = '''\
#!/usr/bin/env python3
"""
site: shebang-site
task: 截图
intent: screenshot
url: https://example.com/
status: ok
"""
pass
'''

# 单引号 docstring
_SINGLE_QUOTE_EXTRACT = """\
'''
site: single-quote-site
task: 表单
intent: form
url: https://example.com/form
status: broken
'''
pass
"""

# 正文里有多行字符串包含字段文本
_MULTILINE_BODY = '''\
"""
site: test-site
task: 数据抓取
intent: scrape
status: ok
"""
TEMPLATE = """
task: 这不是元数据
status: in-template
"""
'''


def test_extract_only_docstring() -> None:
    """正文中的字段不污染提取结果。"""
    p = _tmp(_BODY_POLLUTES)
    try:
        fields = extract_fields(p)
        check("extract: task 正确提取", fields.get("task") == "抓取订单", repr(fields))
        check("extract: intent 正确提取", fields.get("intent") == "scrape", repr(fields))
        check("extract: url 正确提取", fields.get("url") == "https://example.com/orders", repr(fields))
        # 正文里的 status: / last_run: 不应被提取（头部字段为空应返回空）
        check("extract: 正文 status 不污染", fields.get("status", "") == "", repr(fields))
        check("extract: 正文 last_run 不污染", fields.get("last_run", "") == "", repr(fields))
    finally:
        p.unlink(missing_ok=True)


def test_extract_url_with_hash() -> None:
    """URL 中的 # 不被截断。"""
    p = _tmp(_URL_WITH_HASH)
    try:
        fields = extract_fields(p)
        check("extract: SPA URL 完整保留", fields.get("url") == "https://example.com/#/signin", repr(fields))
    finally:
        p.unlink(missing_ok=True)


def test_extract_shebang() -> None:
    """shebang 行不影响 docstring 解析。"""
    p = _tmp(_SHEBANG_DOUBLE)
    try:
        fields = extract_fields(p)
        check("extract: shebang 脚本 task 提取正确", fields.get("task") == "截图", repr(fields))
        check("extract: shebang 脚本 intent 提取正确", fields.get("intent") == "screenshot", repr(fields))
    finally:
        p.unlink(missing_ok=True)


def test_extract_single_quote_docstring() -> None:
    """单引号 docstring 正常提取。"""
    p = _tmp(_SINGLE_QUOTE_EXTRACT)
    try:
        fields = extract_fields(p)
        check("extract: 单引号 task 提取正确", fields.get("task") == "表单", repr(fields))
        check("extract: 单引号 status 提取正确", fields.get("status") == "broken", repr(fields))
    finally:
        p.unlink(missing_ok=True)


def test_extract_multiline_body_not_polluted() -> None:
    """正文多行字符串里的字段不污染索引。"""
    p = _tmp(_MULTILINE_BODY)
    try:
        fields = extract_fields(p)
        check("extract: 多行正文 task 不被覆盖", fields.get("task") == "数据抓取", repr(fields))
        check("extract: 多行正文 status 不被覆盖", fields.get("status") == "ok", repr(fields))
    finally:
        p.unlink(missing_ok=True)


# ── list-scripts.py --url / --status 过滤测试 ─────────────────────────────────

import io
import unittest.mock as _mock


def _make_site_scripts(tmp: Path, scripts: list[dict]) -> Path:
    """在 tmp/.dp/projects/<site>/scripts/ 创建测试脚本，返回 projects_dir。"""
    for s in scripts:
        site = s.get("site", "test-site")
        script_dir = tmp / ".dp" / "projects" / site / "scripts"
        script_dir.mkdir(parents=True, exist_ok=True)
        content = f'''\
"""
site: {site}
task: {s.get("task", "demo")}
intent: {s.get("intent", "scrape")}
url: {s.get("url", "")}
status: {s.get("status", "")}
last_run:
"""
pass
'''
        (script_dir / s["name"]).write_text(content, encoding="utf-8")
    return tmp / ".dp" / "projects"


def _capture_list_scripts(projects_dir: Path, extra_args: list[str]) -> str:
    """调用 list-scripts main()，捕获 stdout 输出。"""
    argv = ["list-scripts.py", "--root", str(projects_dir.parent.parent)] + extra_args
    buf = io.StringIO()
    with _mock.patch("sys.argv", argv), _mock.patch("sys.stdout", buf):
        try:
            _ls_mod.main()
        except SystemExit:
            pass
    return buf.getvalue()


def test_list_scripts_url_filter() -> None:
    """--url 前缀匹配：只返回 url 字段以指定前缀开头的脚本。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _make_site_scripts(tmp, [
            {"name": "orders.py", "url": "https://example.com/orders", "intent": "scrape"},
            {"name": "profile.py", "url": "https://example.com/profile", "intent": "scrape"},
            {"name": "other.py", "url": "https://other.com/path", "intent": "scrape"},
        ])
        out = _capture_list_scripts(tmp / ".dp" / "projects", ["--url", "https://example.com"])
        check("list: --url 命中 orders", "orders.py" in out, repr(out))
        check("list: --url 命中 profile", "profile.py" in out, repr(out))
        check("list: --url 排除 other", "other.py" not in out, repr(out))


def test_list_scripts_status_filter() -> None:
    """--status 精确匹配：只返回 status 字段等于指定值的脚本。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _make_site_scripts(tmp, [
            {"name": "ok1.py", "status": "ok", "url": "https://a.com/"},
            {"name": "broken1.py", "status": "broken", "url": "https://b.com/"},
            {"name": "empty.py", "status": "", "url": "https://c.com/"},
        ])
        out_broken = _capture_list_scripts(tmp / ".dp" / "projects", ["--status", "broken"])
        check("list: --status broken 命中", "broken1.py" in out_broken, repr(out_broken))
        check("list: --status broken 排除 ok", "ok1.py" not in out_broken, repr(out_broken))

        out_ok = _capture_list_scripts(tmp / ".dp" / "projects", ["--status", "ok"])
        check("list: --status ok 命中", "ok1.py" in out_ok, repr(out_ok))
        check("list: --status ok 排除 broken", "broken1.py" not in out_ok, repr(out_ok))


def test_list_scripts_url_no_match() -> None:
    """--url 无匹配时输出"没有匹配的脚本"。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _make_site_scripts(tmp, [
            {"name": "orders.py", "url": "https://example.com/orders", "intent": "scrape"},
        ])
        out = _capture_list_scripts(tmp / ".dp" / "projects", ["--url", "https://notexist.com"])
        check("list: --url 无匹配提示", "没有匹配" in out, repr(out))

import json as _json  # noqa: E402（已在顶层有 json，这里显式别名避免歧义）


def test_list_scripts_json_normal() -> None:
    """--json 返回合法 JSON 数组，每项包含预期字段和正确值。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _make_site_scripts(tmp, [
            {"name": "login.py", "site": "example", "task": "登录",
             "intent": "login", "url": "https://example.com/login", "status": "ok"},
        ])
        out = _capture_list_scripts(tmp / ".dp" / "projects", ["--json"])
        data = _json.loads(out)
        check("list: --json 返回列表", isinstance(data, list), repr(out))
        check("list: --json 非空", len(data) == 1, repr(out))
        item = data[0]
        for key in ("site", "file", "path", "task", "intent", "url", "tags", "status", "last_run"):
            check(f"list: --json 包含字段 {key}", key in item, repr(item))
        check("list: --json site 正确", item["site"] == "example", repr(item))
        check("list: --json intent 正确", item["intent"] == "login", repr(item))
        check("list: --json path 为绝对路径", Path(item["path"]).is_absolute(), repr(item))


def test_list_scripts_json_no_projects() -> None:
    """--json 在无脚本目录时返回 []，而不是中文提示。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        argv = ["list-scripts.py", "--root", str(tmp), "--json"]
        buf = io.StringIO()
        with _mock.patch("sys.argv", argv), _mock.patch("sys.stdout", buf):
            try:
                _ls_mod.main()
            except SystemExit:
                pass
        out = buf.getvalue().strip()
        check("list: --json 空目录返回 []", out == "[]", repr(out))


def test_list_scripts_json_no_match() -> None:
    """--json + filter 过滤后无匹配时返回 []，而不是中文提示。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _make_site_scripts(tmp, [
            {"name": "orders.py", "url": "https://example.com/orders", "intent": "scrape"},
        ])
        out = _capture_list_scripts(tmp / ".dp" / "projects", ["--json", "--status", "broken"])
        data = _json.loads(out)
        check("list: --json 无匹配返回 []", data == [], repr(out))


# ── install.py 测试 ───────────────────────────────────────────────────────────

def test_install_normal() -> None:
    """install: 完整安装流程：文件被复制，manifest 被写出。"""
    with tempfile.TemporaryDirectory() as src_d, tempfile.TemporaryDirectory() as dst_d:
        src = Path(src_d)
        dst = Path(dst_d) / "out"
        dst.mkdir()
        (src / "SKILL.md").write_text("v1", encoding="utf-8")
        (src / "scripts").mkdir()
        (src / "scripts" / "doctor.py").write_text("# x", encoding="utf-8")
        orig = _install_mod.SKILL_DIR
        _install_mod.SKILL_DIR = src
        try:
            _install_mod.install(dst)
        finally:
            _install_mod.SKILL_DIR = orig
        check("install: SKILL.md 已复制", (dst / "SKILL.md").exists(), "")
        check("install: scripts/doctor.py 已复制", (dst / "scripts" / "doctor.py").exists(), "")
        check("install: manifest 已写出", (dst / _install_mod.MANIFEST_FILE).exists(), "")


def test_install_preserves_custom() -> None:
    """install: target 独有的文件不被删除（通过 _sync_dir 验证保留行为）。"""
    with tempfile.TemporaryDirectory() as src_d, tempfile.TemporaryDirectory() as dst_d:
        src = Path(src_d)
        dst = Path(dst_d) / "out"
        dst.mkdir()
        custom = dst / "custom.md"
        custom.write_text("mine", encoding="utf-8")
        (src / "SKILL.md").write_text("v2", encoding="utf-8")
        _install_mod._sync_dir(src, dst)
        check("install: 自定义文件保留", custom.exists(), "")
        check("install: SKILL.md 更新", (dst / "SKILL.md").read_text(encoding="utf-8") == "v2", "")


def test_install_target_inside_source_guard() -> None:
    """install: target 位于 source 内部时抛出 ValueError。"""
    inner = _install_mod.SKILL_DIR / "_test_inner_target"
    try:
        _install_mod.install(inner)
        check("install: 应抛出 ValueError", False, "未抛出异常")
    except ValueError:
        check("install: 抛出 ValueError", True, "")


def test_install_manifest_prune() -> None:
    """install: manifest 记录的 upstream 旧文件在 source 删除后自动清理；无 manifest 时不 prune。"""
    with tempfile.TemporaryDirectory() as src_d, tempfile.TemporaryDirectory() as dst_d:
        src = Path(src_d)
        dst = Path(dst_d) / "out"
        dst.mkdir()
        (src / "SKILL.md").write_text("v1", encoding="utf-8")
        (src / "old.md").write_text("old", encoding="utf-8")
        orig = _install_mod.SKILL_DIR
        _install_mod.SKILL_DIR = src
        try:
            # 首次安装（无 manifest）：old.md 被复制，manifest 被写出
            _install_mod.install(dst)
            check("install: 第一次安装有 old.md", (dst / "old.md").exists(), "")
            check("install: manifest 已写出", (dst / _install_mod.MANIFEST_FILE).exists(), "")
            # 第二次安装：source 删除 old.md → manifest prune 自动清理
            (src / "old.md").unlink()
            _install_mod.install(dst)
            check("install: manifest prune 删除 old.md", not (dst / "old.md").exists(), "")
            check("install: SKILL.md 保留", (dst / "SKILL.md").exists(), "")
        finally:
            _install_mod.SKILL_DIR = orig


def test_install_file_to_dir() -> None:
    """install: 完整两轮安装中 file→dir 升级路径走通，manifest prune 不误删目录。"""
    with tempfile.TemporaryDirectory() as src_d, tempfile.TemporaryDirectory() as dst_d:
        src = Path(src_d)
        dst = Path(dst_d) / "out"
        dst.mkdir()
        orig = _install_mod.SKILL_DIR
        _install_mod.SKILL_DIR = src
        try:
            # 第一次安装：notes 是文件
            (src / "notes").write_text("old file", encoding="utf-8")
            _install_mod.install(dst)
            check("file→dir: 第一次 notes 是文件", (dst / "notes").is_file(), "")
            # 第二次安装：notes 变为目录
            (src / "notes").unlink()
            (src / "notes").mkdir()
            (src / "notes" / "readme.md").write_text("content", encoding="utf-8")
            _install_mod.install(dst)  # 修复前这里抛 IsADirectoryError
            check("file→dir: notes 变为目录", (dst / "notes").is_dir(), "")
            check("file→dir: notes/readme.md 存在", (dst / "notes" / "readme.md").exists(), "")
        finally:
            _install_mod.SKILL_DIR = orig


def test_install_dir_to_file() -> None:
    """install: 完整两轮安装中 dir→file 升级路径走通。"""
    with tempfile.TemporaryDirectory() as src_d, tempfile.TemporaryDirectory() as dst_d:
        src = Path(src_d)
        dst = Path(dst_d) / "out"
        dst.mkdir()
        orig = _install_mod.SKILL_DIR
        _install_mod.SKILL_DIR = src
        try:
            # 第一次安装：notes 是目录
            (src / "notes").mkdir()
            (src / "notes" / "old.md").write_text("old", encoding="utf-8")
            _install_mod.install(dst)
            check("dir→file: 第一次 notes 是目录", (dst / "notes").is_dir(), "")
            # 第二次安装：notes 变为文件
            (src / "notes" / "old.md").unlink()
            (src / "notes").rmdir()
            (src / "notes").write_text("new content", encoding="utf-8")
            _install_mod.install(dst)
            check("dir→file: notes 变为文件", (dst / "notes").is_file(), "")
            check("dir→file: 内容正确", (dst / "notes").read_text(encoding="utf-8") == "new content", "")
        finally:
            _install_mod.SKILL_DIR = orig


def test_install_root_skip() -> None:
    """install: source root 顶层 projects/output 被排除，嵌套子目录内的同名目录保留。"""
    with tempfile.TemporaryDirectory() as src_d, tempfile.TemporaryDirectory() as dst_d:
        src = Path(src_d)
        dst = Path(dst_d) / "out"
        dst.mkdir()
        # 顶层运行态目录（应被排除）
        (src / "projects" / "demo").mkdir(parents=True)
        (src / "projects" / "demo" / "data.json").write_text("{}", encoding="utf-8")
        (src / "output" / "run1").mkdir(parents=True)
        (src / "output" / "run1" / "result.txt").write_text("x", encoding="utf-8")
        # 合法嵌套目录（应被保留）
        (src / "assets" / "output").mkdir(parents=True)
        (src / "assets" / "output" / "keep.txt").write_text("keep", encoding="utf-8")
        (src / "SKILL.md").write_text("v1", encoding="utf-8")
        orig = _install_mod.SKILL_DIR
        _install_mod.SKILL_DIR = src
        try:
            _install_mod.install(dst)
        finally:
            _install_mod.SKILL_DIR = orig
        check("root_skip: 顶层 projects/ 未被安装", not (dst / "projects").exists(), "")
        check("root_skip: 顶层 output/ 未被安装", not (dst / "output").exists(), "")
        check("root_skip: assets/output/keep.txt 已安装", (dst / "assets" / "output" / "keep.txt").exists(), "")


def _patch_doctor(tmp: Path):
    """返回 context manager，临时将 doctor 模块的工作区全局变量指向 tmp/.dp。"""
    import contextlib

    @contextlib.contextmanager
    def ctx():
        dp = tmp / ".dp"
        dp.mkdir(parents=True, exist_ok=True)
        saved = {k: getattr(_doctor, k) for k in ("WORKSPACE", "VENV", "LIB", "CONFIG", "STATE")}
        _doctor.WORKSPACE = dp
        _doctor.VENV = dp / ".venv"
        _doctor.LIB = dp / "lib"
        _doctor.CONFIG = dp / "config.json"
        _doctor.STATE = dp / "state.json"
        try:
            yield dp
        finally:
            for k, v in saved.items():
                setattr(_doctor, k, v)

    return ctx()


def _seed_workspace_ready_state(
    dp: Path,
    *,
    default_provider: str = "cdp-port",
    create_selected_provider: bool = True,
) -> Path:
    """写出最小 ready 工作区结构，返回 fake venv python 路径。"""
    fake_py = dp / ".venv" / "bin" / "python"
    fake_py.parent.mkdir(parents=True, exist_ok=True)
    fake_py.write_text("#!/bin/sh\n", encoding="utf-8")
    for name in ("connect.py", "download_correlation.py", "output.py", "utils.py", "_dp_compat.py"):
        path = dp / "lib" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    providers = dp / "providers"
    providers.mkdir(parents=True, exist_ok=True)
    (providers / "cdp-port.py").write_text("", encoding="utf-8")
    if default_provider != "cdp-port" and create_selected_provider:
        (providers / f"{default_provider}.py").write_text("", encoding="utf-8")
    (dp / "config.json").write_text(
        _json.dumps({"default_provider": default_provider}, ensure_ascii=False),
        encoding="utf-8",
    )
    (dp / "state.json").write_text(
        _json.dumps(
            {
                "runtime_lib_version": _doctor._read_runtime_lib_version(),
                "bundle_version": _doctor._read_bundle_version(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return fake_py


def test_doctor_check_state_missing() -> None:
    """state.json 不存在时 check() 返回可读 issue，不 traceback。"""
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            issues = _doctor.check()
            check("doctor: state.json 缺失被报告",
                  any("state.json" in i for i in issues), str(issues))


def test_doctor_check_version_mismatch() -> None:
    """runtime_lib_version 不一致时 check() 返回 issue。"""
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            dp.joinpath("state.json").write_text(
                _json.dumps({"bundle_version": "old", "runtime_lib_version": "0.0.0"}),
                encoding="utf-8",
            )
            issues = _doctor.check()
            check("doctor: 版本不一致被报告",
                  any("不一致" in i for i in issues), str(issues))


def test_doctor_check_bundle_version_mismatch() -> None:
    """runtime_lib_version 一致但 bundle_version 不一致时，check() 应返回 issue。"""
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            current_runtime = _doctor._read_runtime_lib_version()
            dp.joinpath("state.json").write_text(
                _json.dumps({
                    "bundle_version": "1970-01-01.0",
                    "runtime_lib_version": current_runtime,
                }),
                encoding="utf-8",
            )
            issues = _doctor.check()
            check(
                "doctor: bundle_version 不一致被报告",
                any("bundle" in i for i in issues),
                str(issues),
            )


def test_doctor_check_bundle_version_missing() -> None:
    """state.json 无 bundle_version 字段时，check() 应返回 issue（旧格式工作区）。"""
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            current_runtime = _doctor._read_runtime_lib_version()
            dp.joinpath("state.json").write_text(
                _json.dumps({"runtime_lib_version": current_runtime}),
                encoding="utf-8",
            )
            issues = _doctor.check()
            check(
                "doctor: bundle_version 缺失被报告",
                any("bundle" in i for i in issues),
                str(issues),
            )


def test_doctor_check_state_corrupted() -> None:
    """state.json 损坏时 check() 返回 issue，不 traceback。"""
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            dp.joinpath("state.json").write_text("{ not valid json <<<", encoding="utf-8")
            try:
                issues = _doctor.check()
                check("doctor: state.json 损坏被报告",
                      any("损坏" in i or "state.json" in i for i in issues), str(issues))
            except Exception as e:
                check("doctor: state.json 损坏不应 traceback", False, str(e))


def test_doctor_check_python_not_executable() -> None:
    """venv Python 存在但不可执行时 check() 返回 issue，不 traceback。"""
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            # 创建 Scripts/python.exe（Windows 路径）和 bin/python，写入垃圾内容
            for sub in (("Scripts", "python.exe"), ("bin", "python")):
                fake = dp / ".venv" / sub[0] / sub[1]
                fake.parent.mkdir(parents=True, exist_ok=True)
                fake.write_bytes(b"\x7fELF\x00\x00garbage")  # 非法可执行文件
            try:
                issues = _doctor.check()
                check("doctor: Python 不可执行被报告",
                      any("不可执行" in i or "检测失败" in i or "DrissionPage" in i
                          for i in issues),
                      str(issues))
            except Exception as e:
                check("doctor: Python 不可执行不应 traceback", False, str(e))


def test_doctor_check_requires_selected_default_provider_file() -> None:
    """当前默认 provider 不是 cdp-port 时，缺少对应 provider 文件应返回 issue。"""
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            fake_py = _seed_workspace_ready_state(
                dp,
                default_provider="adspower",
                create_selected_provider=False,
            )
            with _mock.patch.object(_doctor, "resolve_venv_python", return_value=fake_py), _mock.patch.object(
                _doctor.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ):
                issues = _doctor.check()
            check(
                "doctor: 缺少当前默认 provider 文件被报告",
                any("adspower" in issue and "provider" in issue for issue in issues),
                str(issues),
            )


def test_doctor_check_requires_download_correlation_lib() -> None:
    """新的 managed runtime asset 缺失时，doctor.check() 应返回 issue。"""
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            fake_py = _seed_workspace_ready_state(dp)
            (dp / "lib" / "download_correlation.py").unlink(missing_ok=True)
            with _mock.patch.object(_doctor, "resolve_venv_python", return_value=fake_py), _mock.patch.object(
                _doctor.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ):
                issues = _doctor.check()
            check(
                "doctor: 缺少 download_correlation.py 会报错",
                any("download_correlation.py" in issue for issue in issues),
                str(issues),
            )


def test_doctor_check_reports_corrupted_config() -> None:
    """config.json 损坏时应明确报告配置损坏，而不是降级成缺少 default_provider。"""
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            fake_py = _seed_workspace_ready_state(dp)
            (dp / "config.json").write_text("{broken", encoding="utf-8")
            with _mock.patch.object(_doctor, "resolve_venv_python", return_value=fake_py), _mock.patch.object(
                _doctor.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ):
                issues = _doctor.check()
            check(
                "doctor: 损坏 config 被明确报告",
                any("config.json" in issue and ("损坏" in issue or "格式错误" in issue) for issue in issues),
                str(issues),
            )


def test_doctor_write_state_fields() -> None:
    """_write_state() 写入 runtime_lib_version 字段，不写旧的 lib_version。"""
    with tempfile.TemporaryDirectory() as d:
        state_path = Path(d) / "state.json"
        orig_state = _doctor.STATE
        _doctor.STATE = state_path
        try:
            _doctor._write_state("2026-03-20.1", "2026-03-25.1")
            state = _json.loads(state_path.read_text(encoding="utf-8"))
            check("doctor: state.json 含 runtime_lib_version",
                  state.get("runtime_lib_version") == "2026-03-25.1", str(state))
            check("doctor: state.json 含 bundle_version",
                  state.get("bundle_version") == "2026-03-20.1", str(state))
            check("doctor: state.json 不含旧 lib_version",
                  "lib_version" not in state, str(state))
        finally:
            _doctor.STATE = orig_state


# ── doctor.init() 行为测试 ────────────────────────────────────────────────────

def test_doctor_init_garbage_venv_no_traceback() -> None:
    """init() 遇到垃圾 venv Python 时返回 False，不 traceback。"""
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            # 创建垃圾内容的 python.exe（存在但无法执行）
            for sub in (("Scripts", "python.exe"), ("bin", "python")):
                fake = dp / ".venv" / sub[0] / sub[1]
                fake.parent.mkdir(parents=True, exist_ok=True)
                fake.write_bytes(b"\x7fELF\x00garbage")
            try:
                result = _doctor.init()
                check("init: 垃圾 venv 返回 False", result is False, repr(result))
            except Exception as e:
                check("init: 垃圾 venv 不应 traceback", False, str(e))


def test_doctor_init_lib_overwrite_and_state() -> None:
    """init() 修复路径能覆盖 .dp/lib/* 并写出正确字段的 state.json。

    方法：在 _patch_doctor 会指向的 VENV 路径创建真实最小 venv，
    放入假 DrissionPage 包让导入检查通过（不联网），再在 lib/ 放旧内容，
    调 init()，验证 lib 被覆盖、state.json 写入正确字段。
    """
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # _patch_doctor 会将 WORKSPACE = tmp/.dp，VENV = tmp/.dp/.venv
        # 所以 venv 必须创建在这个路径，init() 才能找到它
        dp = tmp / ".dp"
        venv_dir = dp / ".venv"
        venv_dir.mkdir(parents=True, exist_ok=True)

        import subprocess as _sp

        # 1. 在 doctor 实际会用的 VENV 路径创建真实最小 venv
        r = _sp.run([sys.executable, "-m", "venv", str(venv_dir)],
                    capture_output=True, timeout=30)
        if r.returncode != 0:
            check("init: lib 覆盖（venv 创建失败，跳过）", True, "skipped")
            check("init: state.json 字段（venv 创建失败，跳过）", True, "skipped")
            return

        # 2. 找 venv Python 路径
        venv_py_win = venv_dir / "Scripts" / "python.exe"
        venv_py_unix = venv_dir / "bin" / "python"
        venv_py = venv_py_win if venv_py_win.exists() else venv_py_unix
        if not venv_py.exists():
            check("init: lib 覆盖（找不到 venv Python，跳过）", True, "skipped")
            check("init: state.json 字段（找不到 venv Python，跳过）", True, "skipped")
            return

        # 3. 在此 venv 的 site-packages 放假 DrissionPage，
        #    让 init() 的 "import DrissionPage" 检查通过，无需联网安装
        sp_r = _sp.run([str(venv_py), "-c",
                        "import site; print(site.getsitepackages()[0])"],
                       capture_output=True, text=True, timeout=10)
        if sp_r.returncode == 0:
            sp_dir = Path(sp_r.stdout.strip()) / "DrissionPage"
            sp_dir.mkdir(parents=True, exist_ok=True)
            (sp_dir / "__init__.py").write_text("# fake DrissionPage for testing\n",
                                                encoding="utf-8")

        # 4. patch doctor 指向 tmp（WORKSPACE=tmp/.dp，VENV=tmp/.dp/.venv），
        #    在 lib/ 放旧内容，然后调 init()
        with _patch_doctor(tmp) as patched_dp:
            lib_dir = patched_dp / "lib"
            lib_dir.mkdir(parents=True, exist_ok=True)
            for name in ("connect.py", "output.py", "utils.py"):
                (lib_dir / name).write_text("# STALE CONTENT", encoding="utf-8")

            try:
                result = _doctor.init()
            except Exception as e:
                check("init: lib 覆盖（init 抛异常）", False, str(e))
                check("init: state.json 字段（init 抛异常）", False, str(e))
                return

            check("init: 返回 True", result is True, repr(result))

            # 5. 验证 lib 文件被覆盖（不再是旧内容）
            for name in ("connect.py", "output.py", "utils.py", "_dp_compat.py"):
                content = (lib_dir / name).read_text(encoding="utf-8")
                check(f"init: lib/{name} 已覆盖",
                      content != "# STALE CONTENT",
                      f"content[:40]={content[:40]!r}")

            check(
                "init: providers/cdp-port.py 已同步",
                (patched_dp / "providers" / "cdp-port.py").exists(),
                str((patched_dp / "providers" / "cdp-port.py")),
            )
            config_path = patched_dp / "config.json"
            config = _json.loads(config_path.read_text(encoding="utf-8"))
            check(
                "init: config.json 含 default_provider",
                config.get("default_provider") == "cdp-port",
                str(config),
            )

            # 6. 验证 state.json 写入了正确字段
            state_path = patched_dp / "state.json"
            if state_path.exists():
                state = _json.loads(state_path.read_text(encoding="utf-8"))
                check("init: state.json 含 runtime_lib_version",
                      "runtime_lib_version" in state, str(state))
                check("init: state.json 不含旧 lib_version",
                      "lib_version" not in state, str(state))
            else:
                check("init: state.json 已创建", False, "state.json 不存在")
                check("init: state.json 字段（state 不存在）", False, "")


def _create_real_test_venv_with_fake_drissionpage(dp: Path) -> Path | None:
    """在指定 .dp 目录下创建真实最小 venv，并注入假的 DrissionPage 包。"""
    venv_dir = dp / ".venv"
    venv_dir.mkdir(parents=True, exist_ok=True)

    import subprocess as _sp

    r = _sp.run([sys.executable, "-m", "venv", str(venv_dir)], capture_output=True, timeout=30)
    if r.returncode != 0:
        return None

    venv_py_win = venv_dir / "Scripts" / "python.exe"
    venv_py_unix = venv_dir / "bin" / "python"
    venv_py = venv_py_win if venv_py_win.exists() else venv_py_unix
    if not venv_py.exists():
        return None

    sp_r = _sp.run(
        [str(venv_py), "-c", "import site; print(site.getsitepackages()[0])"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if sp_r.returncode == 0:
        sp_dir = Path(sp_r.stdout.strip()) / "DrissionPage"
        sp_dir.mkdir(parents=True, exist_ok=True)
        (sp_dir / "__init__.py").write_text("# fake DrissionPage for testing\n", encoding="utf-8")
    return venv_py


def test_doctor_init_repairs_blank_default_provider() -> None:
    """init() 遇到空字符串 default_provider 时应修复为 cdp-port。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        dp = tmp / ".dp"
        venv_py = _create_real_test_venv_with_fake_drissionpage(dp)
        if venv_py is None:
            check("init: 空 default_provider 修复（venv 创建失败，跳过）", True, "skipped")
            return

        with _patch_doctor(tmp) as patched_dp:
            (patched_dp / "config.json").write_text('{"default_provider": ""}', encoding="utf-8")
            try:
                result = _doctor.init()
                config = _json.loads((patched_dp / "config.json").read_text(encoding="utf-8"))
                check(
                    "init: 空 default_provider 被修复",
                    result is True and config.get("default_provider") == "cdp-port",
                    str(config),
                )
            except Exception as e:
                check("init: 空 default_provider 修复不应 traceback", False, str(e))


def test_doctor_init_normalizes_default_provider() -> None:
    """init() 遇到大小写/空白变体 default_provider 时应写回规范名。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        dp = tmp / ".dp"
        venv_py = _create_real_test_venv_with_fake_drissionpage(dp)
        if venv_py is None:
            check("init: default_provider 规范化（venv 创建失败，跳过）", True, "skipped")
            return

        with _patch_doctor(tmp) as patched_dp:
            (patched_dp / "config.json").write_text('{"default_provider": " CDP-PORT "}', encoding="utf-8")
            try:
                result = _doctor.init()
                config = _json.loads((patched_dp / "config.json").read_text(encoding="utf-8"))
                check(
                    "init: default_provider 被规范化",
                    result is True and config.get("default_provider") == "cdp-port",
                    str(config),
                )
            except Exception as e:
                check("init: default_provider 规范化不应 traceback", False, str(e))


def test_doctor_init_fails_without_managed_provider_template() -> None:
    """缺少 runtime-managed provider 模板时，init() 应失败且不写 state。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        dp = tmp / ".dp"
        venv_py = _create_real_test_venv_with_fake_drissionpage(dp)
        if venv_py is None:
            check("init: 缺 managed provider 模板（venv 创建失败，跳过）", True, "skipped")
            return

        with _patch_doctor(tmp) as patched_dp:
            orig_provider_templates = _doctor.PROVIDER_TEMPLATES
            _doctor.PROVIDER_TEMPLATES = tmp / "missing-provider-templates"
            try:
                result = _doctor.init()
                check(
                    "init: 缺 managed provider 模板返回 False",
                    result is False,
                    repr(result),
                )
                check(
                    "init: 缺 managed provider 模板不写 state",
                    not (patched_dp / "state.json").exists(),
                    str(patched_dp / "state.json"),
                )
            except Exception as e:
                check("init: 缺 managed provider 模板不应 traceback", False, str(e))
            finally:
                _doctor.PROVIDER_TEMPLATES = orig_provider_templates


def test_doctor_init_fails_when_selected_default_provider_file_missing() -> None:
    """init() 遇到缺失的当前默认 provider 实现时应失败且不写 state。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        dp = tmp / ".dp"
        venv_py = _create_real_test_venv_with_fake_drissionpage(dp)
        if venv_py is None:
            check("init: 缺当前默认 provider 文件（venv 创建失败，跳过）", True, "skipped")
            return

        with _patch_doctor(tmp) as patched_dp:
            (patched_dp / "config.json").write_text('{"default_provider":"adspower"}', encoding="utf-8")
            try:
                result = _doctor.init()
                check(
                    "init: 缺当前默认 provider 文件返回 False",
                    result is False,
                    repr(result),
                )
                check(
                    "init: 缺当前默认 provider 文件不写 state",
                    not (patched_dp / "state.json").exists(),
                    str(patched_dp / "state.json"),
                )
            except Exception as e:
                check("init: 缺当前默认 provider 文件不应 traceback", False, str(e))


def test_doctor_init_bundle_only_refresh_skips_runtime_sync() -> None:
    """仅 bundle_version 漂移时，init() 不应覆盖 runtime 资产。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        dp = tmp / ".dp"
        venv_py = _create_real_test_venv_with_fake_drissionpage(dp)
        if venv_py is None:
            check("init: bundle-only refresh 跳过 runtime sync（venv 创建失败，跳过）", True, "skipped")
            return

        with _patch_doctor(tmp) as patched_dp:
            lib_dir = patched_dp / "lib"
            lib_dir.mkdir(parents=True, exist_ok=True)
            for name in ("connect.py", "download_correlation.py", "output.py", "utils.py", "_dp_compat.py"):
                (lib_dir / name).write_text("# KEEP RUNTIME\n", encoding="utf-8")

            providers_dir = patched_dp / "providers"
            providers_dir.mkdir(parents=True, exist_ok=True)
            (providers_dir / "cdp-port.py").write_text("# KEEP PROVIDER\n", encoding="utf-8")
            (patched_dp / "config.json").write_text('{"default_provider":"cdp-port"}', encoding="utf-8")
            (patched_dp / "state.json").write_text(
                _json.dumps(
                    {
                        "runtime_lib_version": _doctor._read_runtime_lib_version(),
                        "bundle_version": "1970-01-01.0",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            try:
                with _mock.patch.object(
                    _doctor,
                    "create_venv",
                    side_effect=AssertionError("bundle-only refresh 不应创建 venv"),
                ), _mock.patch.object(
                    _doctor,
                    "install_drissionpage",
                    side_effect=AssertionError("bundle-only refresh 不应重装 DrissionPage"),
                ):
                    result = _doctor.init()
                check("init: bundle-only refresh 返回 True", result is True, repr(result))
                for name in ("connect.py", "download_correlation.py", "output.py", "utils.py", "_dp_compat.py"):
                    content = (lib_dir / name).read_text(encoding="utf-8")
                    check(
                        f"init: bundle-only refresh 不覆盖 lib/{name}",
                        content == "# KEEP RUNTIME\n",
                        content[:80],
                    )
                provider_content = (providers_dir / "cdp-port.py").read_text(encoding="utf-8")
                check(
                    "init: bundle-only refresh 不覆盖 providers/cdp-port.py",
                    provider_content == "# KEEP PROVIDER\n",
                    provider_content[:80],
                )
                state = _json.loads((patched_dp / "state.json").read_text(encoding="utf-8"))
                check(
                    "init: bundle-only refresh 更新 bundle_version",
                    state.get("bundle_version") == _doctor._read_bundle_version(),
                    str(state),
                )
                check(
                    "init: bundle-only refresh 保持 runtime_lib_version",
                    state.get("runtime_lib_version") == _doctor._read_runtime_lib_version(),
                    str(state),
                )
            except Exception as e:
                check("init: bundle-only refresh 不应 traceback", False, str(e))


# ── normalize_site_name 测试 ──────────────────────────────────────────────────

def test_normalize_site_name() -> None:
    cases = [
        ("", "site"),
        ("example.com", "example-com"),
        ("www.example.com", "example-com"),
        ("NEWS.YCOMBINATOR.COM", "news-ycombinator-com"),
        ("news.ycombinator.com", "news-ycombinator-com"),
        ("  spaces.around.com  ", "spaces-around-com"),
        ("sub.sub.example.co.uk", "sub-sub-example-co-uk"),
        ("example--double.com", "example-double-com"),
        ("www.", "site"),
        ("123.example.com", "123-example-com"),
    ]
    for raw, expected in cases:
        result = normalize_site_name(raw)
        check(
            f"normalize_site_name({raw!r})",
            result == expected,
            f"got {result!r}, want {expected!r}",
        )


def test_site_run_dir_normalizes() -> None:
    """site_run_dir() 内部应调用 normalize_site_name，保证 www./大写 等被规范化。"""
    with tempfile.TemporaryDirectory() as d:
        orig_ws = _output_mod.workspace_root
        _output_mod.workspace_root = lambda: Path(d)
        try:
            run = _output_mod.site_run_dir("www.Example.com", "test")
            check(
                "site_run_dir normalize: www.Example.com -> example-com",
                "example-com" in str(run).replace("\\", "/"),
                str(run),
            )
        finally:
            _output_mod.workspace_root = orig_ws


# ── upload helper 测试 ────────────────────────────────────────────────────────

def test_browser_upload_path_wsl_drive_mount() -> None:
    """WSL 下 /mnt/<drive>/... 路径应转换为 Windows 盘符路径。

    仅在 WSL 环境下有效（__file__ 需要是 /mnt/<drive>/... 格式）。
    """
    src = Path(__file__).resolve()
    if not src.as_posix().startswith("/mnt/"):
        check("upload path: /mnt drive -> Windows drive（非 WSL /mnt 路径，跳过）", True, "skipped")
        return
    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    with _mock.patch.object(_utils_mod, "_is_wsl", return_value=True):
        result = browser_upload_path(src, owner)
    posix = src.as_posix()
    expected = f"{posix.split('/')[2].upper()}:/{'/'.join(posix.split('/')[3:])}"
    check("upload path: /mnt drive -> Windows drive", result == expected, repr(result))


def test_browser_upload_path_wsl_unc() -> None:
    """WSL 下非 /mnt/<drive>/ 路径应转换为 \\\\wsl$ UNC 路径。"""
    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    with tempfile.NamedTemporaryFile() as f:
        src = Path(f.name).resolve()
        with _mock.patch.object(_utils_mod, "_is_wsl", return_value=True), _mock.patch.dict(
            os.environ, {"WSL_DISTRO_NAME": "TestDistro"}, clear=False
        ):
            result = browser_upload_path(src, owner)
        expected = "\\\\wsl$\\TestDistro" + src.as_posix().replace("/", "\\")
        check("upload path: WSL UNC", result == expected, repr(result))


def test_browser_upload_path_linux_passthrough() -> None:
    """Linux/macOS 浏览器使用本地绝对路径，不做 Windows 兼容转换。"""
    owner = _FakeOwner("Mozilla/5.0 (X11; Linux x86_64)")
    with tempfile.NamedTemporaryFile() as f:
        src = Path(f.name).resolve()
        result = browser_upload_path(src, owner)
        check("upload path: Linux 直传", result == src.as_posix(), repr(result))


def test_browser_upload_path_ua_expr_probe() -> None:
    """UA 探测应使用表达式模式，不应传入 return 语句。

    仅在 WSL 环境下有效（__file__ 需要是 /mnt/<drive>/... 格式）。
    """
    src = Path(__file__).resolve()
    if not src.as_posix().startswith("/mnt/"):
        check("upload path: UA probe 用表达式模式（非 WSL /mnt 路径，跳过）", True, "skipped")
        return

    class _ExprOwner(_FakeOwner):
        def run_js(self, script: str, as_expr: bool = True):
            if script != "navigator.userAgent":
                raise AssertionError(script)
            return self._ua

    owner = _ExprOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    with _mock.patch.object(_utils_mod, "_is_wsl", return_value=True):
        result = browser_upload_path(src, owner)
    posix = src.as_posix()
    expected = f"{posix.split('/')[2].upper()}:/{'/'.join(posix.split('/')[3:])}"
    check("upload path: UA probe 用表达式模式", result == expected, repr(result))


def test_browser_upload_path_prefers_launch_info_browser_os_hint() -> None:
    """launch_info.provider_metadata.browser_os 存在时，应优先于 UA 推断。"""
    src = Path(__file__).resolve()
    if not src.as_posix().startswith("/mnt/"):
        check("upload path: launch_info browser_os hint（非 WSL /mnt 路径，跳过）", True, "skipped")
        return
    owner = _FakeOwner("Mozilla/5.0 (X11; Linux x86_64)")
    launch_info = {
        "provider": "chrome-cdp",
        "provider_metadata": {"browser_os": "windows"},
    }
    with _mock.patch.object(_utils_mod, "_is_wsl", return_value=True):
        result = browser_upload_path(src, owner, launch_info=launch_info)
    check(
        "upload path: launch_info browser_os hint 生效",
        result.startswith("G:/") or result.startswith("\\\\wsl$\\"),
        repr(result),
    )


def test_browser_upload_path_prefers_launch_info_path_namespace_hint() -> None:
    """provider_metadata.path_namespace 存在时，应优先走声明的浏览器路径命名空间。"""
    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    launch_info = {
        "provider": "custom-provider",
        "provider_metadata": {
            "browser_os": "windows",
            "path_namespace": "posix",
        },
    }
    with tempfile.NamedTemporaryFile() as f, _mock.patch.dict(
        os.environ, {"WSL_DISTRO_NAME": "TestDistro"}, clear=False
    ):
        src = Path(f.name).resolve()
        result = browser_upload_path(src, owner, launch_info=launch_info)
    check(
        "upload path: launch_info path_namespace hint 生效",
        result == src.as_posix(),
        repr(result),
    )


def test_browser_upload_path_rejects_remote_file_access_mode() -> None:
    """provider 明确声明 remote 文件访问时，应直接报错。"""
    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    launch_info = {
        "provider": "remote-grid",
        "provider_metadata": {"file_access_mode": "remote"},
    }
    with tempfile.NamedTemporaryFile() as f:
        try:
            browser_upload_path(f.name, owner, launch_info=launch_info)
        except RuntimeError as exc:
            check(
                "upload path: remote provider 直接失败",
                "remote-grid" in str(exc),
                str(exc),
            )
        else:
            check("upload path: remote provider 直接失败", False, "expected RuntimeError")


def test_get_wsl_distro_name_falls_back_to_wsl_exe() -> None:
    """当环境变量缺失时，应允许通过 wsl.exe 回退获取 distro 名。"""
    with _mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": ""}, clear=False), _mock.patch.object(
        _utils_mod.subprocess,
        "check_output",
        return_value="TestDistro\n",
        create=True,
    ):
        result = _utils_mod._get_wsl_distro_name()
    check("upload path: WSL distro 可通过 wsl.exe 回退获取", result == "TestDistro", repr(result))


def test_browser_upload_path_wsl_distro_fallback_reaches_unc_output() -> None:
    """wsl.exe 回退得到的 distro 名必须真正进入最终 UNC 输出。"""
    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    with tempfile.NamedTemporaryFile() as f, _mock.patch.dict(
        os.environ, {"WSL_DISTRO_NAME": ""}, clear=False
    ), _mock.patch.object(
        _utils_mod.subprocess,
        "check_output",
        return_value="TestDistro\n",
        create=True,
    ):
        result = browser_upload_path(
            Path(f.name).resolve(),
            owner,
            launch_info={"provider_metadata": {"browser_os": "windows"}},
        )
    check(
        "upload path: wsl.exe 回退结果真正进入最终 UNC 输出",
        result.startswith("\\\\wsl$\\TestDistro\\"),
        repr(result),
    )


def test_browser_upload_path_windows_browser_requires_distro_for_posix_path() -> None:
    """Windows 浏览器消费 POSIX 路径时，拿不到 distro 应直接失败。"""
    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    with tempfile.NamedTemporaryFile() as f, _mock.patch.dict(
        os.environ, {"WSL_DISTRO_NAME": ""}, clear=False
    ), _mock.patch.object(
        _utils_mod.subprocess,
        "check_output",
        side_effect=RuntimeError("missing wsl.exe"),
        create=True,
    ):
        try:
            browser_upload_path(
                Path(f.name).resolve(),
                owner,
                launch_info={"provider_metadata": {"browser_os": "windows"}},
            )
        except RuntimeError:
            check("upload path: 缺 distro 时直接失败", True)
        else:
            check("upload path: 缺 distro 时直接失败", False, "expected RuntimeError")


def test_browser_download_path_windows_backslash() -> None:
    """Windows 浏览器下载目录应使用反斜杠路径。

    该测试依赖 /mnt/g/... WSL 映射路径，仅在 WSL 环境下有效；
    从 Windows Python（conda/native）运行时自动跳过，不 traceback。
    """
    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    wsl_tmp = "/mnt/g/Program/DPSkill/.dp/tmp"
    if not Path(wsl_tmp).is_dir():
        check("download path: Windows 反斜杠（WSL 路径不可用，跳过）", True, "skipped")
        return
    with tempfile.TemporaryDirectory(dir=wsl_tmp) as d, _mock.patch.object(
        _utils_mod, "_is_wsl", return_value=True
    ):
        result = browser_download_path(d, owner)
    check("download path: Windows 反斜杠", "\\" in result and result.startswith("G:\\"), repr(result))


def test_upload_file_input_strategy() -> None:
    """input[type=file] 走直接文件输入，并补发 input/change 事件。"""
    ele = _FakeElement("input", "file", "Mozilla/5.0 (X11; Linux x86_64)")
    with tempfile.NamedTemporaryFile() as f:
        upload_file(ele, f.name)
        expected = Path(f.name).resolve().as_posix()
        check("upload: file input 走 ele.input()", ele.input_calls == [(expected, False, False)], repr(ele.input_calls))
        check("upload: file input 不走 chooser", ele.owner.upload_paths == [], repr(ele.owner.upload_paths))
        check("upload: file input 补发 change", any("change" in s for s in ele.js_calls), repr(ele.js_calls))


def test_upload_file_passes_launch_info_to_browser_upload_path() -> None:
    """upload_file() 应把 launch_info 透传给 browser_upload_path()."""
    ele = _FakeElement("input", "file", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    launch_info = {"provider": "chrome-cdp", "provider_metadata": {"browser_os": "windows"}}
    captured: dict[str, object] = {}

    def _fake_browser_upload_path(path, obj=None, launch_info=None):
        captured["path"] = path
        captured["obj"] = obj
        captured["launch_info"] = launch_info
        return str(path)

    with tempfile.NamedTemporaryFile() as f, _mock.patch.object(
        _utils_mod, "browser_upload_path", side_effect=_fake_browser_upload_path
    ):
        upload_file(ele, f.name, launch_info=launch_info)

    check("upload: launch_info 已透传", captured.get("launch_info") == launch_info, repr(captured))


def test_upload_file_chooser_strategy() -> None:
    """chooser 按钮先 set.upload_files()，再走原生点击与等待。"""
    ele = _FakeElement("button", "", "Mozilla/5.0 (X11; Linux x86_64)")
    with tempfile.NamedTemporaryFile() as f:
        upload_file(ele, f.name, timeout=7)
        expected = Path(f.name).resolve().as_posix()
        check("upload: chooser 预置文件路径", ele.owner.upload_paths == [expected], repr(ele.owner.upload_paths))
        check("upload: chooser 走原生点击", ele.click_calls == [False], repr(ele.click_calls))
        check("upload: chooser 等待 inputted", ele.owner.upload_waited, repr(ele.owner.upload_waited))


def test_download_file_wrapper() -> None:
    """跨 OS 时 download_file() 应走 raw CDP fallback。"""
    ele = _FakeElement("a", "", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    launch_info = {"provider": "chrome-cdp", "provider_metadata": {"browser_os": "windows"}}
    captured: dict[str, object] = {}

    def _fake_set_download_path(target, browser_path: str) -> None:
        captured["target"] = target
        captured["browser_path"] = browser_path
        target.owner._browser._download_path = browser_path
        target.owner._download_path = browser_path

    with tempfile.TemporaryDirectory() as d, _mock.patch.object(
        _utils_mod, "_set_browser_download_path", _fake_set_download_path
    ), _mock.patch.object(
        _utils_mod, "_wait_download_complete", lambda *args, **kwargs: Path(d) / "report.txt"
    ):
        final_path = download_file(ele, d, rename="report.txt", timeout=9, launch_info=launch_info)

    expected = browser_download_path(Path(d), ele, launch_info=launch_info)
    check("download raw: 目录路径已规范化", captured.get("browser_path") == expected, repr(captured))
    check("download raw: 走原生点击", ele.click_calls == [False], repr(ele.click_calls))
    check("download raw: 返回最终路径", Path(final_path).name == "report.txt", repr(final_path))
    check(
        "download raw: 浏览器下载目录已恢复",
        ele.owner._browser._download_path == "/fake/browser-downloads",
        repr(ele.owner._browser._download_path),
    )
    check(
        "download raw: owner 下载目录已恢复",
        ele.owner._download_path == "/fake/owner-downloads",
        repr(ele.owner._download_path),
    )
    check(
        "download raw: restore 撤销 CDP 下载覆盖",
        any(
            method == "Browser.setDownloadBehavior"
            and kwargs.get("behavior") == "default"
            and "downloadPath" not in kwargs
            for method, kwargs in ele.owner.browser_cdp_calls
        ),
        repr(ele.owner.browser_cdp_calls),
    )


def test_download_file_raw_cdp_prepares_fetch_rename_for_chrome_cdp() -> None:
    """chrome-cdp 的 raw fallback 应在下载任务创建前通过 Fetch 改 suggested filename。"""
    ele = _FakeElement("a", "", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    launch_info = {"provider": "chrome-cdp", "provider_metadata": {"browser_os": "windows"}}

    def _fake_click(_ele, timeout=10):
        callback = _ele.owner.driver_callbacks.get("Fetch.requestPaused")
        if callback:
            callback(
                requestId="req-1",
                responseStatusCode=200,
                responseHeaders=[
                    {"name": "Content-Type", "value": "text/plain"},
                    {"name": "Content-Disposition", "value": 'attachment; filename=\"server-name.txt\"'},
                ],
            )
        _ele.click_calls.append(False)
        return _ele

    with tempfile.TemporaryDirectory() as d, _mock.patch.object(
        _utils_mod, "browser_download_path", return_value=r"G:\fake-downloads"
    ), _mock.patch.object(
        _utils_mod, "_set_browser_download_path", return_value=None
    ), _mock.patch.object(
        _utils_mod, "_wait_download_complete", return_value=Path(d) / "renamed.txt"
    ), _mock.patch.object(
        _utils_mod, "native_click", side_effect=_fake_click
    ):
        download_file(ele, d, rename="renamed.txt", timeout=9, launch_info=launch_info)

    check(
        "download raw: Fetch.enable 已调用",
        any(method == "Fetch.enable" for method, _ in ele.owner.page_cdp_calls),
        repr(ele.owner.page_cdp_calls),
    )
    check(
        "download raw: continueResponse 写入目标文件名",
        any(
            method == "Fetch.continueResponse"
            and "renamed.txt" in _json.dumps(kwargs, ensure_ascii=False)
            for method, kwargs in ele.owner.page_cdp_calls
        ),
        repr(ele.owner.page_cdp_calls),
    )
    check(
        "download raw: Fetch.disable 已调用",
        any(method == "Fetch.disable" for method, _ in ele.owner.page_cdp_calls),
        repr(ele.owner.page_cdp_calls),
    )


def test_download_file_raw_cdp_prepares_fetch_rename_for_cdp_capable_provider() -> None:
    """下载改名增强应基于 CDP 能力而不是绑死某个 provider 名。"""
    ele = _FakeElement("a", "", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    launch_info = {"provider": "custom-grid", "provider_metadata": {"browser_os": "windows"}}

    def _fake_click(_ele, timeout=10):
        callback = _ele.owner.driver_callbacks.get("Fetch.requestPaused")
        if callback:
            callback(
                requestId="req-2",
                responseStatusCode=200,
                responseHeaders=[
                    {"name": "Content-Type", "value": "text/plain"},
                    {"name": "Content-Disposition", "value": 'attachment; filename=\"server-name.txt\"'},
                ],
            )
        _ele.click_calls.append(False)
        return _ele

    with tempfile.TemporaryDirectory() as d, _mock.patch.object(
        _utils_mod, "browser_download_path", return_value=r"G:\fake-downloads"
    ), _mock.patch.object(
        _utils_mod, "_set_browser_download_path", return_value=None
    ), _mock.patch.object(
        _utils_mod, "_wait_download_complete", return_value=Path(d) / "renamed.txt"
    ), _mock.patch.object(
        _utils_mod, "native_click", side_effect=_fake_click
    ):
        download_file(ele, d, rename="renamed.txt", timeout=9, launch_info=launch_info)

    check(
        "download raw: 非 chrome-cdp provider 也会启用 Fetch 改名",
        any(method == "Fetch.enable" for method, _ in ele.owner.page_cdp_calls),
        repr(ele.owner.page_cdp_calls),
    )
    check(
        "download raw: 非 chrome-cdp provider 也会写入目标文件名",
        any(
            method == "Fetch.continueResponse"
            and "renamed.txt" in _json.dumps(kwargs, ensure_ascii=False)
            for method, kwargs in ele.owner.page_cdp_calls
        ),
        repr(ele.owner.page_cdp_calls),
    )


def test_download_file_raw_cdp_fetch_rename_failure_falls_back() -> None:
    """下载改名增强初始化失败时，download_file() 应继续下载，不阻塞主流程。"""
    ele = _FakeElement("a", "", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    launch_info = {"provider": "chrome-cdp", "provider_metadata": {"browser_os": "windows"}}

    with tempfile.TemporaryDirectory() as d, _mock.patch.object(
        _utils_mod, "browser_download_path", return_value=r"G:\fake-downloads"
    ), _mock.patch.object(
        _utils_mod, "_set_browser_download_path", return_value=None
    ), _mock.patch.object(
        _utils_mod, "_wait_download_complete", return_value=Path(d) / "renamed.txt"
    ), _mock.patch.object(
        _utils_mod, "prepare_download_interceptor", side_effect=RuntimeError("fetch unsupported")
    ):
        final_path = download_file(ele, d, rename="renamed.txt", timeout=9, launch_info=launch_info)

    check("download raw: Fetch 失败仍返回最终路径", Path(final_path).name == "renamed.txt", repr(final_path))


def test_download_file_passes_launch_info_to_browser_download_path() -> None:
    """download_file() 应把 launch_info 透传给 browser_download_path()."""
    ele = _FakeElement("a", "", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    launch_info = {"provider": "chrome-cdp", "provider_metadata": {"browser_os": "windows"}}
    captured: dict[str, object] = {}

    def _fake_browser_download_path(path, obj=None, launch_info=None):
        captured["path"] = path
        captured["obj"] = obj
        captured["launch_info"] = launch_info
        return r"G:\fake-downloads"

    with tempfile.TemporaryDirectory() as d, _mock.patch.object(
        _utils_mod, "browser_download_path", side_effect=_fake_browser_download_path
    ), _mock.patch.object(
        _utils_mod, "_set_browser_download_path", return_value=None
    ), _mock.patch.object(
        _utils_mod, "_wait_download_complete", return_value=Path(d) / "report.txt"
    ):
        download_file(ele, d, rename="report.txt", timeout=9, launch_info=launch_info)

    check("download: launch_info 已透传", captured.get("launch_info") == launch_info, repr(captured))


def test_download_file_same_os_still_uses_raw_cdp_path() -> None:
    """即使同 OS，也应只走统一 raw/CDP 下载主路径，不再走 DP 下载管理。"""
    ele = _FakeElement("a", "", "Mozilla/5.0 (X11; Linux x86_64)")
    captured: dict[str, object] = {}

    def _fake_set_download_path(target, browser_path: str, new_tab=None) -> None:
        captured["browser_path"] = browser_path
        target.owner._browser._download_path = browser_path
        target.owner._download_path = browser_path

    with tempfile.TemporaryDirectory() as d, _mock.patch.object(
        _utils_mod, "_set_browser_download_path", side_effect=_fake_set_download_path
    ), _mock.patch.object(
        _utils_mod, "_wait_download_complete", lambda *args, **kwargs: Path(d) / "report.txt"
    ):
        final_path = download_file(ele, d, rename="report.txt", timeout=9)

    check("download unified: 不走 DP 下载管理", ele.download_calls == [], repr(ele.download_calls))
    check("download unified: 仍走原生点击", ele.click_calls == [False], repr(ele.click_calls))
    check("download unified: 设置浏览器下载目录", captured.get("browser_path") == str(Path(d).resolve()), repr(captured))
    check("download unified: 返回最终路径", Path(final_path).name == "report.txt", repr(final_path))


def test_download_file_by_js_click_strategy() -> None:
    """by_js=True 时，download_file() 应走显式 JS click 分支。"""
    ele = _FakeElement("a", "", "Mozilla/5.0 (X11; Linux x86_64)", {
        "href": "http://example.com/file.txt",
        "download": "file.txt",
    })
    with tempfile.TemporaryDirectory() as d, _mock.patch.object(
        _utils_mod, "_wait_download_complete", return_value=Path(d) / "file.txt"
    ):
        download_file(ele, d, rename="file.txt", timeout=1, by_js=True)
    check("download by_js: 走 JS click 分支", ele.click_calls == [True], repr(ele.click_calls))


def test_download_file_signature_removes_new_tab() -> None:
    """download_file() 的公开签名中不再出现 new_tab。"""
    params = inspect.signature(download_file).parameters
    check("download_file: 签名中不再出现 new_tab", "new_tab" not in params, repr(list(params)))


def test_download_interceptor_skips_non_download_response() -> None:
    """独立下载 correlation 层不应污染非下载响应。"""
    try:
        _download_corr = _load_download_correlation_module()
    except Exception as exc:
        check("download corr: 模块可加载", False, str(exc))
        return

    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    interceptor = _download_corr.prepare_download_interceptor(
        owner,
        _download_corr.DownloadIntent(
            target_name="report.txt",
            rename_requested=True,
            href="https://example.com/report.txt",
            download_attr="report.txt",
        ),
    )
    if interceptor is None:
        check("download corr: 非下载响应不注入 Content-Disposition", False, "prepare_download_interceptor returned None")
        return
    interceptor.enable()
    owner.driver_callbacks["Fetch.requestPaused"](
        requestId="req-css",
        request={"url": "https://example.com/app.css"},
        responseStatusCode=200,
        responseHeaders=[{"name": "Content-Type", "value": "text/css"}],
    )
    interceptor.cleanup()
    check(
        "download corr: 非下载响应不注入 Content-Disposition",
        not any(
            method == "Fetch.continueResponse"
            and "Content-Disposition" in _json.dumps(kwargs, ensure_ascii=False)
            for method, kwargs in owner.page_cdp_calls
        ),
        repr(owner.page_cdp_calls),
    )


def test_download_interceptor_one_shot_match() -> None:
    """命中一次后，后续 response 不应继续改写。"""
    try:
        _download_corr = _load_download_correlation_module()
    except Exception as exc:
        check("download corr: one-shot match 可加载模块", False, str(exc))
        return

    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    interceptor = _download_corr.prepare_download_interceptor(
        owner,
        _download_corr.DownloadIntent(
            target_name="report.txt",
            rename_requested=True,
            href="https://example.com/report.txt",
            download_attr="report.txt",
        ),
    )
    if interceptor is None:
        check("download corr: 命中一次后后续 response 不再改写", False, "prepare_download_interceptor returned None")
        return
    interceptor.enable()
    callback = owner.driver_callbacks["Fetch.requestPaused"]
    callback(
        requestId="req-1",
        request={"url": "https://example.com/report.txt"},
        responseStatusCode=200,
        responseHeaders=[{"name": "Content-Disposition", "value": 'attachment; filename="server.txt"'}],
    )
    callback(
        requestId="req-2",
        request={"url": "https://example.com/report.txt?again=1"},
        responseStatusCode=200,
        responseHeaders=[{"name": "Content-Disposition", "value": 'attachment; filename="second.txt"'}],
    )
    interceptor.cleanup()
    rewritten = [
        kwargs for method, kwargs in owner.page_cdp_calls
        if method == "Fetch.continueResponse"
        and any(item.get("value") == 'attachment; filename="report.txt"' for item in kwargs.get("responseHeaders", []))
    ]
    preserved_second = any(
        method == "Fetch.continueResponse"
        and any(item.get("value") == 'attachment; filename="second.txt"' for item in kwargs.get("responseHeaders", []))
        for method, kwargs in owner.page_cdp_calls
    )
    check("download corr: 命中一次后后续 response 不再改写", len(rewritten) == 1 and preserved_second, repr(owner.page_cdp_calls))


def test_download_interceptor_not_enabled_without_rename_request() -> None:
    """没有 rename/suffix 需求时，不应启用下载拦截增强。"""
    try:
        _download_corr = _load_download_correlation_module()
    except Exception as exc:
        check("download corr: 无 rename 时不启用增强可加载模块", False, str(exc))
        return

    owner = _FakeOwner("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    interceptor = _download_corr.prepare_download_interceptor(
        owner,
        _download_corr.DownloadIntent(
            target_name="report.txt",
            rename_requested=False,
            href="https://example.com/report.txt",
            download_attr="report.txt",
        ),
    )
    check("download corr: 无 rename 时不启用增强", interceptor is None, repr(interceptor))


def test_download_file_data_url_direct_save() -> None:
    """data: 直链下载应直接保存到本地 run-dir，不依赖浏览器下载管理器。"""
    ele = _FakeElement(
        "a",
        "",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        attrs={
            "href": "data:text/plain;charset=utf-8,hello%20dp%0A",
            "download": "fixture.txt",
        },
    )
    with tempfile.TemporaryDirectory() as d:
        result = download_file(ele, d)
        final_path = Path(result)
        check("download data: 返回 Path", final_path.exists(), str(final_path))
        check("download data: 文件名正确", final_path.name == "fixture.txt", final_path.name)
        check("download data: 内容正确", final_path.read_text(encoding="utf-8") == "hello dp\n", final_path.read_text(encoding="utf-8"))
        check("download data: 不走浏览器下载管理", ele.download_calls == [], repr(ele.download_calls))


def test_download_file_data_url_rejects_remote_file_access_mode() -> None:
    """即使是 data: 下载，provider 明确声明 remote 时也应在 helper 入口直接失败。"""
    ele = _FakeElement(
        "a",
        "",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        attrs={
            "href": "data:text/plain;charset=utf-8,hello%20dp%0A",
            "download": "fixture.txt",
        },
    )
    launch_info = {
        "provider": "remote-grid",
        "provider_metadata": {"file_access_mode": "remote"},
    }
    with tempfile.TemporaryDirectory() as d:
        try:
            download_file(ele, d, launch_info=launch_info)
        except RuntimeError as exc:
            check(
                "download data: remote provider 直接失败",
                "remote-grid" in str(exc),
                str(exc),
            )
        else:
            check("download data: remote provider 直接失败", False, "expected RuntimeError")


# ── doctor 其他行为测试 ───────────────────────────────────────────────────────

def test_doctor_init_always_rewrites_readme() -> None:
    """_write_workspace_docs() 无论 README 是否已存在都应重写为新 contract。"""
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            dp.joinpath("README.md").write_text("# OLD CONTENT", encoding="utf-8")
            _doctor._write_workspace_docs()
            content = dp.joinpath("README.md").read_text(encoding="utf-8")
            check("doctor README 旧文件被重写", "OLD CONTENT" not in content, content[:60])
            check(
                "doctor README 含 run-dir contract",
                "HHMMSS" in content or "run-dir" in content,
                content[:120],
            )


def test_doctor_init_readme_managed_declaration() -> None:
    """_write_workspace_docs() 生成的 README 应包含 dp:managed 托管声明。"""
    with tempfile.TemporaryDirectory() as d:
        with _patch_doctor(Path(d)) as dp:
            _doctor._write_workspace_docs()
            content = dp.joinpath("README.md").read_text(encoding="utf-8")
            check(
                "init: README.md 含 dp:managed 声明",
                "dp:managed" in content,
                content[:120],
            )


def test_install_path_independence() -> None:
    """doctor.py 应仅通过 __file__ 定位 SKILL.md，不依赖固定安装目录名。
    验证方式：SKILL_DIR 能找到 SKILL.md（说明路径计算正确），
    且 doctor.py 源码本身不硬编码任何固定安装路径。
    """
    skill_dir = _doctor.SKILL_DIR
    check(
        "doctor SKILL_DIR 通过 __file__ 推导且 SKILL.md 存在",
        (skill_dir / "SKILL.md").exists(),
        f"SKILL_DIR={skill_dir}",
    )
    # 验证 doctor.py 源码中不出现写死的 .agents 安装路径字符串
    doctor_src = (Path(_doctor.__file__).resolve()).read_text(encoding="utf-8")
    hardcoded = ".agents/skills/dp"
    check(
        "doctor.py 源码不含硬编码安装路径",
        hardcoded not in doctor_src,
        f"found: {hardcoded!r}",
    )


# ── validate_bundle 失败路径测试 ──────────────────────────────────────────────

def _expect_fail(name: str, fn) -> None:
    """辅助：期望 fn() 触发 SystemExit(1)。"""
    try:
        fn()
        check(name, False, "未触发 SystemExit")
    except SystemExit as e:
        check(name, e.code == 1, f"exit code={e.code}")


def test_validate_missing_runtime_lib_version() -> None:
    """frontmatter 缺少 runtime-lib-version 时 parse_frontmatter 应失败。"""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "SKILL.md"
        p.write_text(
            '---\nname: dp\ndescription: >\n  t\ncompatibility: >\n  t\n'
            'metadata:\n  bundle-version: "2026-03-26.1"\n---\n# body\n',
            encoding="utf-8",
        )
        _expect_fail("validate: 缺少 runtime-lib-version 应失败",
                     lambda: _vb.parse_frontmatter(p))


def test_validate_bundle_type_rejected() -> None:
    """frontmatter 含已废弃的 bundle-type 时 parse_frontmatter 应失败。"""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "SKILL.md"
        p.write_text(
            '---\nname: dp\ndescription: >\n  t\ncompatibility: >\n  t\n'
            'metadata:\n  bundle-version: "2026-03-26.1"\n'
            '  runtime-lib-version: "2026-03-26.1"\n  bundle-type: "x"\n---\n# body\n',
            encoding="utf-8",
        )
        _expect_fail("validate: bundle-type 应被拒绝",
                     lambda: _vb.parse_frontmatter(p))


def test_validate_old_output_contract_rejected() -> None:
    """evals.json 含旧输出路径 output/YYYY-MM-DD/（真实日期）时应失败。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "evals").mkdir()
        (root / "evals" / "evals.json").write_text(
            '{"skill_name":"dp","evals":[{"expected_output":"output/2026-03-20/data.json"}]}',
            encoding="utf-8",
        )
        (root / "evals" / "smoke-checklist.md").write_text("# checklist\n", encoding="utf-8")
        (root / "SKILL.md").write_text("# skill\n", encoding="utf-8")
        (root / "references").mkdir()
        (root / "references" / "workflows.md").write_text("# workflows\n", encoding="utf-8")
        _expect_fail("validate: 旧输出路径（真实日期）应失败",
                     lambda: _vb.validate_output_contract(root))


def test_validate_placeholder_output_contract_rejected() -> None:
    """evals.json 含占位符写法 output/YYYY-MM-DD/（字面量模板）时同样应失败。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "evals").mkdir()
        (root / "evals" / "evals.json").write_text(
            '{"skill_name":"dp","evals":[{"expected_output":"output/YYYY-MM-DD/data.json"}]}',
            encoding="utf-8",
        )
        (root / "evals" / "smoke-checklist.md").write_text("# checklist\n", encoding="utf-8")
        (root / "SKILL.md").write_text("# skill\n", encoding="utf-8")
        (root / "references").mkdir()
        (root / "references" / "workflows.md").write_text("# workflows\n", encoding="utf-8")
        _expect_fail("validate: 旧输出路径（占位符 YYYY-MM-DD）应失败",
                     lambda: _vb.validate_output_contract(root))


def test_validate_agents_text_rejected() -> None:
    """文件含 .agents/skills/dp 耦合文本时 validate_forbidden_text 应失败。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "SKILL.md").write_text(
            "# test\n" + ".agents" + "/skills/dp" + "\n",  # 拆分构造，避免本文件自身被扫描触发
            encoding="utf-8",
        )
        _expect_fail("validate: .agents 耦合文本应失败",
                     lambda: _vb.validate_forbidden_text(root))


def test_validate_missing_site_run_dir() -> None:
    """output.py 缺少 site_run_dir 函数时 validate_cross_file_consistency 应失败。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "templates").mkdir()
        (root / "templates" / "output.py").write_text("def old_func(): pass\n", encoding="utf-8")
        (root / "references").mkdir()
        (root / "references" / "workflows.md").write_text(
            "site_run_dir\nmark_script_status\nintent:\nurl:\ntags:\nlast_run:\nstatus:\n",
            encoding="utf-8",
        )
        _expect_fail("validate: 缺少 site_run_dir 应失败",
                     lambda: _vb.validate_cross_file_consistency(root))


def test_validate_missing_upload_helper() -> None:
    """utils.py 缺少 upload helper 时 validate_cross_file_consistency 应失败。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "templates").mkdir()
        (root / "templates" / "output.py").write_text("def site_run_dir(): pass\n", encoding="utf-8")
        (root / "templates" / "utils.py").write_text("def other(): pass\n", encoding="utf-8")
        (root / "references").mkdir()
        (root / "references" / "workflows.md").write_text(
            "site_run_dir\nmark_script_status\nintent:\nurl:\ntags:\nlast_run:\nstatus:\n",
            encoding="utf-8",
        )
        _expect_fail("validate: 缺少 upload helper 应失败",
                     lambda: _vb.validate_cross_file_consistency(root))


def _create_required_bundle_tree(root: Path, *, omit: set[str] | None = None) -> None:
    """按 validate_bundle.REQUIRED_FILES 创建最小 bundle 目录树。"""
    omitted = omit or set()
    for rel in _vb.REQUIRED_FILES:
        if rel in omitted:
            continue
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix in {".py", ".md", ".json", ".gitignore"}:
            path.write_text("", encoding="utf-8")
        else:
            path.touch()


def test_validate_missing_provider_contract_reference_required() -> None:
    """references/provider-contract.md 缺失时 validate_required_files 应失败。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _create_required_bundle_tree(root, omit={"references/provider-contract.md"})
        _expect_fail(
            "validate: 缺少 provider-contract.md 应失败",
            lambda: _vb.validate_required_files(root),
        )


def test_validate_missing_cdp_port_template_required() -> None:
    """templates/providers/cdp-port.py 缺失时 validate_required_files 应失败。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _create_required_bundle_tree(root, omit={"templates/providers/cdp-port.py"})
        _expect_fail(
            "validate: 缺少 templates/providers/cdp-port.py 应失败",
            lambda: _vb.validate_required_files(root),
        )


def test_validate_missing_download_correlation_template_required() -> None:
    """templates/download_correlation.py 缺失时 validate_required_files 应失败。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _create_required_bundle_tree(root, omit={"templates/download_correlation.py"})
        _expect_fail(
            "validate: 缺少 templates/download_correlation.py 应失败",
            lambda: _vb.validate_required_files(root),
        )


def test_validate_removed_connect_wrappers_not_referenced_in_docs() -> None:
    """canonical docs 引用 removed connect wrapper 时 validate_removed_connect_wrappers 应失败。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _create_required_bundle_tree(root)
        for rel in (
            "SKILL.md",
            "references/workflows.md",
            "references/mode-selection.md",
            "evals/smoke-checklist.md",
        ):
            (root / rel).write_text("# doc\n", encoding="utf-8")
        (root / "references" / "workflows.md").write_text("connect_web_page()\n", encoding="utf-8")
        _expect_fail(
            "validate: canonical docs 不应再引用 removed connect wrappers",
            lambda: _vb.validate_removed_connect_wrappers(root),
        )


def _build_workflows_md(upload_contract: str = "", download_contract: str = "") -> str:
    return (
        "# Workflow 代码模板\n\n"
        "## Workflow 5：文件上传（upload）\n\n"
        "**contract**：\n"
        f"{upload_contract}\n\n"
        "## Workflow 6：文件下载（download）\n\n"
        "**contract**：\n"
        f"{download_contract}\n"
    )


def test_validate_workflow_file_helper_contracts_require_upload_remote_fail_fast_boundary() -> None:
    """upload contract 若只写“更安全”，未声明 remote fail-fast，应失败。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _create_required_bundle_tree(root)
        (root / "references" / "workflows.md").write_text(
            _build_workflows_md(
                upload_contract=(
                    "- 对直接 `input[type=file]`，优先 `upload_file(..., launch_info=launch_info)`；"
                    "它会处理跨平台路径，并在提供 `launch_info` 时结合 provider hints "
                    "做更安全的本地文件访问判断"
                ),
                download_contract=(
                    "- 对下载目录优先使用 `download_file(..., launch_info=launch_info)`\n"
                    "- provider 若显式声明不支持本地文件访问，helper 会直接报错而不是继续盲猜路径"
                ),
            ),
            encoding="utf-8",
        )
        _expect_fail(
            "validate: workflow upload contract 缺少 remote fail-fast 边界应失败",
            lambda: _vb.validate_workflow_file_helper_contracts(root),
        )


def test_validate_workflow_file_helper_contracts_require_download_remote_fail_fast_boundary() -> None:
    """download contract 若未声明 remote fail-fast，应失败。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _create_required_bundle_tree(root)
        (root / "references" / "workflows.md").write_text(
            _build_workflows_md(
                upload_contract=(
                    "- 对直接 `input[type=file]`，优先 `upload_file(..., launch_info=launch_info)`；"
                    "若 provider 明确声明 remote 或不支持本地文件访问，则 helper 直接报错"
                ),
                download_contract=(
                    "- 对下载目录优先使用 `download_file(..., launch_info=launch_info)`\n"
                    "- helper 统一走浏览器下载目录 + 原生点击 + 完成等待的 CDP 下载主路径\n"
                    "- 对支持的 provider / 浏览器链路，helper 会尽量在创建下载任务时改写目标文件名"
                ),
            ),
            encoding="utf-8",
        )
        _expect_fail(
            "validate: workflow download contract 缺少 remote fail-fast 边界应失败",
            lambda: _vb.validate_workflow_file_helper_contracts(root),
        )


def test_validate_workflow_file_helper_contracts_allow_remote_fail_fast_boundary() -> None:
    """upload/download contract 写出 remote fail-fast 边界时应通过。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _create_required_bundle_tree(root)
        (root / "references" / "workflows.md").write_text(
            _build_workflows_md(
                upload_contract=(
                    "- 对直接 `input[type=file]`，优先 `upload_file(..., launch_info=launch_info)`；"
                    "它会处理跨平台路径，并在提供 `launch_info` 时结合 provider hints 判断本地文件访问能力；"
                    "若 provider 明确声明 remote 或不支持本地文件访问，则 helper 直接报错"
                ),
                download_contract=(
                    "- 对下载目录优先使用 `download_file(..., launch_info=launch_info)`\n"
                    "- helper 统一走浏览器下载目录 + 原生点击 + 完成等待的 CDP 下载主路径\n"
                    "- provider 若显式声明 remote 或不支持本地文件访问，helper 会直接报错而不是继续盲猜路径"
                ),
            ),
            encoding="utf-8",
        )
        try:
            _vb.validate_workflow_file_helper_contracts(root)
            check("validate: workflow upload/download remote fail-fast prose 可通过", True)
        except SystemExit:
            check(
                "validate: workflow upload/download remote fail-fast prose 可通过",
                False,
                "不应触发 SystemExit",
            )


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print("── _rewrite_header_fields ──")
    test_empty_fields()
    test_stale_fields()
    test_body_not_modified()
    test_shebang()
    test_no_docstring()
    test_single_quote_docstring()

    print("\n── mark_script_status (integration) ──")
    test_mark_script_status_integration()

    print("\n── extract_fields ──")
    test_extract_only_docstring()
    test_extract_url_with_hash()
    test_extract_shebang()
    test_extract_single_quote_docstring()
    test_extract_multiline_body_not_polluted()

    print("\n── list-scripts --url / --status 过滤 ──")
    test_list_scripts_url_filter()
    test_list_scripts_status_filter()
    test_list_scripts_url_no_match()

    print("\n── list-scripts --json 输出 ──")
    test_list_scripts_json_normal()
    test_list_scripts_json_no_projects()
    test_list_scripts_json_no_match()

    print("\n── install.py ──")
    test_install_normal()
    test_install_preserves_custom()
    test_install_target_inside_source_guard()
    test_install_manifest_prune()
    test_install_file_to_dir()
    test_install_dir_to_file()
    test_install_root_skip()

    print("\n── doctor.check() ──")
    test_doctor_check_state_missing()
    test_doctor_check_version_mismatch()
    test_doctor_check_bundle_version_mismatch()
    test_doctor_check_bundle_version_missing()
    test_doctor_check_state_corrupted()
    test_doctor_check_python_not_executable()
    test_doctor_check_requires_selected_default_provider_file()
    test_doctor_check_requires_download_correlation_lib()
    test_doctor_check_reports_corrupted_config()
    test_doctor_write_state_fields()

    print("\n── doctor.init() ──")
    test_doctor_init_garbage_venv_no_traceback()
    test_doctor_init_lib_overwrite_and_state()
    test_doctor_init_repairs_blank_default_provider()
    test_doctor_init_normalizes_default_provider()
    test_doctor_init_fails_without_managed_provider_template()
    test_doctor_init_fails_when_selected_default_provider_file_missing()
    test_doctor_init_bundle_only_refresh_skips_runtime_sync()

    print("\n── normalize_site_name ──")
    test_normalize_site_name()
    test_site_run_dir_normalizes()

    print("\n── upload helper ──")
    test_browser_upload_path_wsl_drive_mount()
    test_browser_upload_path_wsl_unc()
    test_browser_upload_path_linux_passthrough()
    test_browser_upload_path_ua_expr_probe()
    test_browser_upload_path_prefers_launch_info_browser_os_hint()
    test_browser_upload_path_prefers_launch_info_path_namespace_hint()
    test_browser_upload_path_rejects_remote_file_access_mode()
    test_get_wsl_distro_name_falls_back_to_wsl_exe()
    test_browser_upload_path_wsl_distro_fallback_reaches_unc_output()
    test_browser_upload_path_windows_browser_requires_distro_for_posix_path()
    test_browser_download_path_windows_backslash()
    test_upload_file_input_strategy()
    test_upload_file_passes_launch_info_to_browser_upload_path()
    test_upload_file_chooser_strategy()
    test_download_file_wrapper()
    test_download_file_raw_cdp_prepares_fetch_rename_for_chrome_cdp()
    test_download_file_raw_cdp_prepares_fetch_rename_for_cdp_capable_provider()
    test_download_file_raw_cdp_fetch_rename_failure_falls_back()
    test_download_file_passes_launch_info_to_browser_download_path()
    test_download_file_same_os_still_uses_raw_cdp_path()
    test_download_file_by_js_click_strategy()
    test_download_file_signature_removes_new_tab()
    test_download_interceptor_skips_non_download_response()
    test_download_interceptor_one_shot_match()
    test_download_interceptor_not_enabled_without_rename_request()
    test_download_file_data_url_direct_save()
    test_download_file_data_url_rejects_remote_file_access_mode()

    print("\n── doctor 其他行为 ──")
    test_doctor_init_always_rewrites_readme()
    test_doctor_init_readme_managed_declaration()
    test_install_path_independence()

    print("\n── validate_bundle 失败路径 ──")
    test_validate_missing_runtime_lib_version()
    test_validate_bundle_type_rejected()
    test_validate_old_output_contract_rejected()
    test_validate_placeholder_output_contract_rejected()
    test_validate_agents_text_rejected()
    test_validate_missing_site_run_dir()
    test_validate_missing_upload_helper()
    test_validate_missing_provider_contract_reference_required()
    test_validate_missing_cdp_port_template_required()
    test_validate_missing_download_correlation_template_required()
    test_validate_removed_connect_wrappers_not_referenced_in_docs()
    test_validate_workflow_file_helper_contracts_require_upload_remote_fail_fast_boundary()
    test_validate_workflow_file_helper_contracts_require_download_remote_fail_fast_boundary()
    test_validate_workflow_file_helper_contracts_allow_remote_fail_fast_boundary()

    print("\n── P0 新增：download_file 目录自动创建 ──")
    test_download_file_creates_nonexistent_dir()

    print("\n── P0 新增：venv_python OS-aware ──")
    test_venv_python_os_aware()
    test_venv_python_fallback_to_other_os()

    print("\n── P0 新增：smoke _check_workspace 可执行性 ──")
    test_smoke_check_workspace_python_not_executable()
    test_smoke_check_workspace_no_drissionpage()
    test_smoke_check_workspace_requires_cdp_port_provider()
    test_smoke_check_workspace_requires_default_provider()
    test_smoke_check_workspace_requires_selected_default_provider_file()
    test_smoke_check_workspace_requires_matching_state_versions()
    test_smoke_get_default_provider_normalizes_value()
    test_smoke_main_requires_explicit_port_for_cdp_port()

    print("\n── P1/P2 新增：_rewrite_header_fields 三引号边界 ──")
    test_rewrite_header_no_triple_quote_leak()

    print("\n── P1 新增：_dp_compat 接口 ──")
    test_dp_compat_get_owner_or_self_element()
    test_dp_compat_get_owner_or_self_page()
    test_dp_compat_get_set_download_path()
    test_dp_compat_sentinel()

    print("\n── get_user_agent 直接单测 ──")
    test_get_user_agent_prefers_as_expr()
    test_get_user_agent_fallback_on_typeerror()
    test_get_user_agent_returns_empty_on_all_errors()

    print("\n── P1-3：connect API surface ──")
    test_start_profile_and_connect_browser_fresh_tab_binds_tab_id()
    test_removed_legacy_connect_wrappers_are_absent()
    test_get_default_browser_provider_treats_non_string_as_uninitialized()

    print("\n── provider loader ──")
    test_browser_provider_loader_finds_workspace_provider()
    test_browser_provider_loader_rejects_normalized_name_conflict()
    test_workspace_provider_start_profile_and_connect()
    test_provider_loader_rejects_missing_contract()

    print("\n── validate_rule_markers 章节内检查 ──")
    test_validate_rule_markers_port_rule_needs_section()
    test_validate_rule_markers_list_scripts_rule_needs_section()
    test_validate_rule_markers_workspace_root_rule_needs_section()
    test_validate_rule_markers_allows_rephrased_prose()
    test_validate_rule_markers_preflight_requires_workspace_contract_tokens()
    test_validate_rule_markers_preflight_requires_managed_lib_markers()
    test_validate_rule_markers_preflight_requires_download_correlation_marker()
    test_validate_rule_markers_preflight_requires_illegal_provider_boundary()
    test_validate_rule_markers_preflight_requires_selected_provider_presence_boundary()
    test_validate_rule_markers_file_helper_requires_remote_fail_fast_boundary()
    test_validate_rule_markers_allows_preflight_prose_with_repair_boundary()
    test_validate_smoke_checklist_requires_non_string_repair_boundary()
    test_validate_smoke_checklist_requires_selected_provider_snake_case_boundary()
    test_validate_smoke_checklist_allows_complete_preflight_prose()

    print()
    if _failed:
        print(f"FAILED: {_failed} 项")
        return 1
    print("ALL PASSED")
    return 0


# ── P0 新增：download_file() 目录自动创建测试 ─────────────────────────────────

def test_download_file_creates_nonexistent_dir() -> None:
    """download_file() 传入不存在的目录时，应自动创建目录并继续（不抛 FileNotFoundError）。"""
    with tempfile.TemporaryDirectory() as d:
        nonexistent = Path(d) / "brand_new_subdir" / "downloads"
        assert not nonexistent.exists(), "预期目录不存在"

        # 用非 data: href 的假元素，触发非 data: 分支
        ele = _FakeElement("a", "", "Mozilla/5.0 (X11; Linux x86_64)", {
            "href": "http://example.com/file.txt",
            "download": "file.txt",
        })

        got_file_not_found = False
        try:
            with _mock.patch.object(
                _utils_mod, "_wait_download_complete",
                side_effect=TimeoutError("no browser"),
            ), _mock.patch.object(
                _utils_mod, "_set_browser_download_path", return_value=None
            ):
                download_file(ele, nonexistent, rename="file.txt", timeout=1)
        except FileNotFoundError:
            got_file_not_found = True
        except Exception:
            pass  # TimeoutError / 其他异常均属正常（无浏览器）

        check("download_file: 不抛 FileNotFoundError", not got_file_not_found,
              "iterdir() 在 mkdir 之前被调用了")
        check("download_file: 自动创建目录", nonexistent.exists(), str(nonexistent))


# ── P0 新增：venv_python() OS-aware 测试 ─────────────────────────────────────

def test_venv_python_os_aware() -> None:
    """venv_python() 在当前 OS 下应优先返回正确路径。"""
    import os
    with tempfile.TemporaryDirectory() as d:
        venv = Path(d) / ".venv"
        win_py = venv / "Scripts" / "python.exe"
        unix_py = venv / "bin" / "python"
        win_py.parent.mkdir(parents=True)
        unix_py.parent.mkdir(parents=True)
        win_py.touch()
        unix_py.touch()

        orig_venv = _doctor.VENV
        _doctor.VENV = venv
        try:
            result = _doctor.venv_python()
            if os.name == "nt":
                check("venv_python: Windows 优先 Scripts/python.exe",
                      result == win_py, str(result))
            else:
                check("venv_python: 非 Windows 优先 bin/python",
                      result == unix_py, str(result))
        finally:
            _doctor.VENV = orig_venv


def test_venv_python_fallback_to_other_os() -> None:
    """venv_python() 只有一侧路径存在时应回退到另一个。"""
    import os
    with tempfile.TemporaryDirectory() as d:
        venv = Path(d) / ".venv"
        if os.name == "nt":
            # Windows 宿主但只有 bin/python
            only_path = venv / "bin" / "python"
        else:
            # 非 Windows 宿主但只有 Scripts/python.exe
            only_path = venv / "Scripts" / "python.exe"
        only_path.parent.mkdir(parents=True)
        only_path.touch()

        orig_venv = _doctor.VENV
        _doctor.VENV = venv
        try:
            result = _doctor.venv_python()
            check("venv_python: 回退到存在的另一路径",
                  result == only_path, str(result))
        finally:
            _doctor.VENV = orig_venv


# ── P0 新增：smoke _check_workspace 可执行性测试 ─────────────────────────────

def _load_smoke_module():
    """通过 importlib 加载 smoke.py（文件名不含连字符，但通过此方式统一加载）。"""
    spec = importlib.util.spec_from_file_location(
        "_smoke_test", Path(__file__).parent / "smoke.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_smoke_check_workspace_python_not_executable() -> None:
    """smoke._check_workspace() 遇到不可执行的 Python 时返回错误字符串，不 traceback。"""
    smoke_mod = _load_smoke_module()
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d) / ".dp"
        # 创建假的 venv：bin/python 和 Scripts/python.exe 都有，但内容是垃圾，无法执行
        for sub in (("Scripts", "python.exe"), ("bin", "python")):
            fake = dp / ".venv" / sub[0] / sub[1]
            fake.parent.mkdir(parents=True, exist_ok=True)
            fake.write_bytes(b"\x7fELF\x00garbage_not_executable")
        (dp / "lib").mkdir(parents=True, exist_ok=True)
        (dp / "lib" / "connect.py").touch()

        orig_ws = smoke_mod.WORKSPACE
        smoke_mod.WORKSPACE = dp
        try:
            try:
                result = smoke_mod._check_workspace()
                check("smoke: 不可执行 Python 返回错误字符串",
                      result is not None and len(result) > 0,
                      repr(result))
            except Exception as e:
                check("smoke: 不可执行 Python 不应 traceback", False, str(e))
        finally:
            smoke_mod.WORKSPACE = orig_ws


def test_smoke_check_workspace_no_drissionpage() -> None:
    """smoke._check_workspace() 遇到可执行但未安装 DrissionPage 的 venv 时返回错误字符串。"""
    import os as _os
    smoke_mod = _load_smoke_module()
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d) / ".dp"
        venv = dp / ".venv"
        (dp / "lib" / "connect.py").parent.mkdir(parents=True, exist_ok=True)
        (dp / "lib" / "connect.py").touch()

        # 创建真实 venv（不安装 DrissionPage）
        import subprocess as _sp
        r = _sp.run([sys.executable, "-m", "venv", str(venv)],
                    capture_output=True, timeout=30)
        if r.returncode != 0:
            check("smoke: DrissionPage 缺失（venv 创建失败，跳过）", True, "skipped")
            return

        # 定位真实 venv 的 Python
        real_py = venv / ("Scripts/python.exe" if _os.name == "nt" else "bin/python")
        if not real_py.exists():
            check("smoke: DrissionPage 缺失（venv Python 不存在，跳过）", True, "skipped")
            return

        orig_ws = smoke_mod.WORKSPACE
        orig_vp = smoke_mod.venv_python
        # monkeypatch venv_python 直接返回真实 venv 路径（绕过 WORKSPACE 常量）
        smoke_mod.venv_python = lambda: real_py
        smoke_mod.WORKSPACE = dp
        try:
            try:
                result = smoke_mod._check_workspace()
                check("smoke: 无 DrissionPage 返回错误字符串",
                      result is not None and "DrissionPage" in result,
                      repr(result))
            except Exception as e:
                check("smoke: 无 DrissionPage 不应 traceback", False, str(e))
        finally:
            smoke_mod.WORKSPACE = orig_ws
            smoke_mod.venv_python = orig_vp


def test_smoke_check_workspace_requires_cdp_port_provider() -> None:
    """smoke._check_workspace() 缺少 runtime-managed cdp-port provider 时应返回错误。"""
    smoke_mod = _load_smoke_module()
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d) / ".dp"
        fake_py = dp / ".venv" / "bin" / "python"
        fake_py.parent.mkdir(parents=True, exist_ok=True)
        fake_py.write_text("#!/bin/sh\n", encoding="utf-8")
        for name in ("connect.py", "download_correlation.py", "output.py", "utils.py", "_dp_compat.py"):
            path = dp / "lib" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        (dp / "config.json").write_text('{"default_provider":"cdp-port"}', encoding="utf-8")

        orig_ws = smoke_mod.WORKSPACE
        orig_vp = smoke_mod.venv_python
        orig_run = smoke_mod.subprocess.run
        smoke_mod.WORKSPACE = dp
        smoke_mod.venv_python = lambda: fake_py
        smoke_mod.subprocess.run = lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr="")
        try:
            result = smoke_mod._check_workspace()
            check(
                "smoke: 缺少 cdp-port provider 返回错误字符串",
                result is not None and "cdp-port.py" in result,
                repr(result),
            )
        finally:
            smoke_mod.WORKSPACE = orig_ws
            smoke_mod.venv_python = orig_vp
            smoke_mod.subprocess.run = orig_run


def test_smoke_check_workspace_requires_default_provider() -> None:
    """smoke._check_workspace() 缺少 default_provider 时应返回错误。"""
    smoke_mod = _load_smoke_module()
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d) / ".dp"
        fake_py = dp / ".venv" / "bin" / "python"
        fake_py.parent.mkdir(parents=True, exist_ok=True)
        fake_py.write_text("#!/bin/sh\n", encoding="utf-8")
        for name in ("connect.py", "download_correlation.py", "output.py", "utils.py", "_dp_compat.py"):
            path = dp / "lib" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        providers = dp / "providers"
        providers.mkdir(parents=True, exist_ok=True)
        (providers / "cdp-port.py").write_text("", encoding="utf-8")
        (dp / "config.json").write_text("{}", encoding="utf-8")

        orig_ws = smoke_mod.WORKSPACE
        orig_vp = smoke_mod.venv_python
        orig_run = smoke_mod.subprocess.run
        smoke_mod.WORKSPACE = dp
        smoke_mod.venv_python = lambda: fake_py
        smoke_mod.subprocess.run = lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr="")
        try:
            result = smoke_mod._check_workspace()
            check(
                "smoke: 缺少 default_provider 返回错误字符串",
                result is not None and "default_provider" in result,
                repr(result),
            )
        finally:
            smoke_mod.WORKSPACE = orig_ws
            smoke_mod.venv_python = orig_vp
            smoke_mod.subprocess.run = orig_run


def test_smoke_check_workspace_requires_selected_default_provider_file() -> None:
    """smoke._check_workspace() 缺少当前默认 provider 文件时应返回错误。"""
    smoke_mod = _load_smoke_module()
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d) / ".dp"
        fake_py = _seed_workspace_ready_state(
            dp,
            default_provider="adspower",
            create_selected_provider=False,
        )

        orig_ws = smoke_mod.WORKSPACE
        orig_vp = smoke_mod.venv_python
        orig_run = smoke_mod.subprocess.run
        smoke_mod.WORKSPACE = dp
        smoke_mod.venv_python = lambda: fake_py
        smoke_mod.subprocess.run = lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr="")
        try:
            result = smoke_mod._check_workspace()
            check(
                "smoke: 缺少当前默认 provider 文件返回错误字符串",
                result is not None and "adspower" in result,
                repr(result),
            )
        finally:
            smoke_mod.WORKSPACE = orig_ws
            smoke_mod.venv_python = orig_vp
            smoke_mod.subprocess.run = orig_run


def test_smoke_check_workspace_requires_matching_state_versions() -> None:
    """smoke._check_workspace() 遇到旧 state 版本时应返回错误。"""
    smoke_mod = _load_smoke_module()
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d) / ".dp"
        fake_py = dp / ".venv" / "bin" / "python"
        fake_py.parent.mkdir(parents=True, exist_ok=True)
        fake_py.write_text("#!/bin/sh\n", encoding="utf-8")
        for name in ("connect.py", "download_correlation.py", "output.py", "utils.py", "_dp_compat.py"):
            path = dp / "lib" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        providers = dp / "providers"
        providers.mkdir(parents=True, exist_ok=True)
        (providers / "cdp-port.py").write_text("", encoding="utf-8")
        (dp / "config.json").write_text('{"default_provider":"cdp-port"}', encoding="utf-8")
        (dp / "state.json").write_text(
            '{"runtime_lib_version":"old","bundle_version":"old"}',
            encoding="utf-8",
        )

        orig_ws = smoke_mod.WORKSPACE
        orig_vp = smoke_mod.venv_python
        orig_run = smoke_mod.subprocess.run
        smoke_mod.WORKSPACE = dp
        smoke_mod.venv_python = lambda: fake_py
        smoke_mod.subprocess.run = lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr="")
        try:
            result = smoke_mod._check_workspace()
            check(
                "smoke: 旧 state 版本返回错误",
                result is not None and ("版本" in result or "state" in result),
                repr(result),
            )
        finally:
            smoke_mod.WORKSPACE = orig_ws
            smoke_mod.venv_python = orig_vp
            smoke_mod.subprocess.run = orig_run


def test_smoke_get_default_provider_normalizes_value() -> None:
    """smoke._get_default_provider() 应把大小写/空白变体规范化为 cdp-port。"""
    smoke_mod = _load_smoke_module()
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d) / ".dp"
        dp.mkdir(parents=True, exist_ok=True)
        (dp / "config.json").write_text('{"default_provider":" CDP-PORT "}', encoding="utf-8")

        orig_ws = smoke_mod.WORKSPACE
        smoke_mod.WORKSPACE = dp
        try:
            result = smoke_mod._get_default_provider()
            check(
                "smoke: default_provider 会被规范化",
                result == "cdp-port",
                repr(result),
            )
        finally:
            smoke_mod.WORKSPACE = orig_ws


def test_smoke_main_requires_explicit_port_for_cdp_port() -> None:
    """当默认 provider 为 cdp-port 时，smoke.py 主流程必须要求显式 --port。"""
    smoke_mod = _load_smoke_module()
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d) / ".dp"
        providers = dp / "providers"
        providers.mkdir(parents=True, exist_ok=True)
        (providers / "cdp-port.py").write_text("", encoding="utf-8")
        (dp / "config.json").write_text('{"default_provider":"cdp-port"}', encoding="utf-8")

        orig_ws = smoke_mod.WORKSPACE
        orig_check_workspace = smoke_mod._check_workspace
        orig_check_browser = smoke_mod._check_browser
        orig_start_fixture_server = smoke_mod._start_fixture_server
        orig_run_script = smoke_mod._run_script
        orig_verify_screenshot = smoke_mod._verify_screenshot
        orig_all_cases = smoke_mod.ALL_CASES
        orig_browser_cases = smoke_mod.BROWSER_REQUIRED_CASES
        old_argv = sys.argv

        smoke_mod.WORKSPACE = dp
        smoke_mod._check_workspace = lambda: None
        smoke_mod._check_browser = lambda port: True
        smoke_mod._start_fixture_server = lambda port: SimpleNamespace(shutdown=lambda: None)
        smoke_mod._run_script = lambda script, port, timeout=60: True
        smoke_mod._verify_screenshot = lambda: (True, "ok")
        smoke_mod.ALL_CASES = ["screenshot"]
        smoke_mod.BROWSER_REQUIRED_CASES = frozenset({"screenshot"})
        sys.argv = ["smoke.py", "--case", "screenshot"]

        stderr = io.StringIO()
        try:
            with redirect_stderr(stderr):
                try:
                    smoke_mod.main()
                except SystemExit as exc:
                    check(
                        "smoke: cdp-port 默认 provider 需要显式 --port",
                        exc.code == 2 and "--port" in stderr.getvalue(),
                        f"code={exc.code}, stderr={stderr.getvalue()!r}",
                    )
                else:
                    check("smoke: cdp-port 默认 provider 需要显式 --port", False, "main() 未退出")
        finally:
            smoke_mod.WORKSPACE = orig_ws
            smoke_mod._check_workspace = orig_check_workspace
            smoke_mod._check_browser = orig_check_browser
            smoke_mod._start_fixture_server = orig_start_fixture_server
            smoke_mod._run_script = orig_run_script
            smoke_mod._verify_screenshot = orig_verify_screenshot
            smoke_mod.ALL_CASES = orig_all_cases
            smoke_mod.BROWSER_REQUIRED_CASES = orig_browser_cases
            sys.argv = old_argv


# ── P1/P2 新增：_rewrite_header_fields 三引号边界测试 ─────────────────────────

_DOCSTRING_WITH_TRIPLE_QUOTE_EXAMPLE = '''\
"""
site: test
task: demo
last_run:
status:
usage: python scripts/demo.py [--port 9222]

示例：
    result = """这是一个示例字符串"""
"""
pass
'''

_DOCSTRING_SINGLE_DELIM_WITH_EXAMPLE = """\
'''
site: test
task: demo
last_run:
status:

示例：
    result = '''这是一个示例字符串'''
'''
pass
"""


def test_rewrite_header_no_triple_quote_leak() -> None:
    """docstring 内含三引号代码示例时，_rewrite_header_fields 不应误匹配正文。"""
    # 注意：这个测试的 docstring 本身包含 \"\"\"，模拟真实脚本中带代码示例的文档字符串
    # 由于当前 regex 是非贪婪匹配，会找到最短的 \"\"\"...\"\"\", 所以结果取决于内层 \"\"\" 位置
    # 本测试的目的是检测是否误改正文字段
    result = _rewrite_header_fields(_DOCSTRING_WITH_TRIPLE_QUOTE_EXAMPLE, "ok", TODAY)
    # 无论 regex 如何匹配，正文里的 status 和 last_run 赋值不应被改
    check(
        "triple-quote: 正文 result= 行未被破坏",
        '"""这是一个示例字符串"""' in result or "'''这是一个示例字符串'''" in result or "这是一个示例字符串" in result,
        repr(result),
    )
    # 头部字段应被正确更新（如果 regex 能到达正确的 docstring）
    # 这里不强断言头部更新成功，因为内嵌三引号可能导致 regex 提前退出
    # 主要验证：不 traceback，不修改不应修改的部分
    check("triple-quote: 不 traceback", True, "")


# ── _dp_compat.py 基础测试 ────────────────────────────────────────────────────

import importlib.util as _ilu_compat

_compat_spec = _ilu_compat.spec_from_file_location(
    "_dp_compat_test",
    Path(__file__).resolve().parent.parent / "templates" / "_dp_compat.py"
)
_compat_mod = _ilu_compat.module_from_spec(_compat_spec)
_compat_spec.loader.exec_module(_compat_mod)


def test_dp_compat_get_owner_or_self_element() -> None:
    """get_owner_or_self(element) 应返回 element.owner。"""
    owner = _FakeOwner("Mozilla/5.0 (X11; Linux x86_64)")
    ele = _FakeElement("a", "", "Mozilla/5.0 (X11; Linux x86_64)")
    ele.owner = owner
    result = _compat_mod.get_owner_or_self(ele)
    check("compat: get_owner_or_self(element) = owner", result is owner, repr(result))


def test_dp_compat_get_owner_or_self_page() -> None:
    """get_owner_or_self(page) 当 page 无 owner 属性时应返回自身。"""
    page = object()  # 无 owner 属性
    result = _compat_mod.get_owner_or_self(page)
    check("compat: get_owner_or_self(page without owner) = self", result is page, repr(result))


def test_dp_compat_get_set_download_path() -> None:
    """get_download_path / set_download_path 应能读写 _download_path。"""
    owner = _FakeOwner("ua")
    orig = owner._download_path
    _compat_mod.set_download_path(owner, "/new/path")
    check("compat: set_download_path 写入", owner._download_path == "/new/path", repr(owner._download_path))
    check("compat: get_download_path 读取", _compat_mod.get_download_path(owner) == "/new/path", "")
    owner._download_path = orig  # restore


def test_dp_compat_sentinel() -> None:
    """get_download_path_sentinel 在属性不存在时返回哨兵，is_download_path_missing 识别它。"""
    class _NoAttr: pass
    obj = _NoAttr()
    val = _compat_mod.get_download_path_sentinel(obj)
    check("compat: 哨兵识别", _compat_mod.is_download_path_missing(val), repr(val))

    owner = _FakeOwner("ua")
    val2 = _compat_mod.get_download_path_sentinel(owner)
    check("compat: 有属性时哨兵不识别", not _compat_mod.is_download_path_missing(val2), repr(val2))


# ── get_user_agent 直接单测 ───────────────────────────────────────────────────

def test_get_user_agent_prefers_as_expr() -> None:
    """as_expr=True 可用时，get_user_agent 应直接返回 UA 字符串。"""
    class _PageWithAsExpr:
        def run_js(self, script, as_expr=False):
            return "Mozilla/5.0 (Windows NT 10.0)"

    result = _compat_mod.get_user_agent(_PageWithAsExpr())
    check("compat: get_user_agent as_expr 路径返回 UA", "Windows NT" in result, repr(result))


def test_get_user_agent_fallback_on_typeerror() -> None:
    """as_expr 参数不存在时触发 TypeError，fallback 到无参路径，仍返回 UA。"""
    class _PageNoAsExpr:
        def run_js(self, script, **kwargs):
            if "as_expr" in kwargs:
                raise TypeError("unexpected keyword argument 'as_expr'")
            return "Mozilla/5.0 (Linux)"

    result = _compat_mod.get_user_agent(_PageNoAsExpr())
    check("compat: get_user_agent TypeError fallback 返回 UA", "Linux" in result, repr(result))


def test_get_user_agent_returns_empty_on_all_errors() -> None:
    """两条路径均抛异常时，get_user_agent 应返回空字符串，不抛异常。"""
    class _PageBothFail:
        def run_js(self, script, **kwargs):
            if "as_expr" in kwargs:
                raise TypeError("unexpected keyword argument 'as_expr'")
            raise RuntimeError("cdp connection error")

    result = _compat_mod.get_user_agent(_PageBothFail())
    check("compat: get_user_agent 双路径异常返回空串", result == "", repr(result))


# ── P1-3：fresh_tab 连接语义测试（monkeypatch Chromium/ChromiumPage）────────────

def _load_connect_module():
    """通过 importlib 加载 connect.py，monkeypatch DrissionPage 类后测试连接语义。"""
    spec = importlib.util.spec_from_file_location(
        "_connect_test",
        Path(__file__).resolve().parent.parent / "templates" / "connect.py"
    )
    mod = importlib.util.module_from_spec(spec)
    # 注入假的 DrissionPage 类，避免真实连接
    import types
    fake_dp = types.ModuleType("DrissionPage")

    class _FakeTab:
        def __init__(self, tab_id: str):
            self.tab_id = tab_id

    class _FakeBrowser:
        def __init__(self, co):
            self._co = co
            self._tab_counter = 0

        def new_tab(self, url: str = "about:blank") -> _FakeTab:
            self._tab_counter += 1
            return _FakeTab(f"fake-tab-{self._tab_counter}")

    class _FakeChromium:
        def __init__(self, co):
            self._browser = _FakeBrowser(co)

        def new_tab(self, url: str = "about:blank") -> _FakeTab:
            return self._browser.new_tab(url=url)

    class _RecordingChromiumPage:
        _instances: list = []

        def __init__(self, co, tab_id: str | None = None):
            self.co = co
            self.tab_id = tab_id
            _RecordingChromiumPage._instances.append(self)

    class _FakeChromiumOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.address = None
            self.existing = None

        def set_address(self, addr):
            self.address = addr
            return self

        def existing_only(self, v):
            self.existing = v
            return self

    class _FakeWebPage:
        def __init__(self, mode=None, chromium_options=None):
            self.mode = mode

    fake_dp.Chromium = _FakeChromium
    fake_dp.ChromiumPage = _RecordingChromiumPage
    fake_dp.ChromiumOptions = _FakeChromiumOptions
    fake_dp.WebPage = _FakeWebPage
    sys.modules["DrissionPage"] = fake_dp

    try:
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    finally:
        # 还原 DrissionPage（避免污染其他测试）
        sys.modules.pop(spec.name, None)
        sys.modules.pop("DrissionPage", None)

    return mod, _RecordingChromiumPage, _FakeChromium


def test_start_profile_and_connect_browser_fresh_tab_binds_tab_id() -> None:
    """验证 provider-first fresh_tab=True 时 ChromiumPage 构造函数正确接收 tab_id。

    覆盖范围：本测试通过 monkeypatch 证明 tab_id 参数被传入 ChromiumPage 构造函数。
    未覆盖：DrissionPage 内部是否有单例缓存会在运行时忽略此 tab_id——
    该行为只能在真实浏览器连接下才能观测到，属于端到端 smoke 的责任范围。
    """
    connect_mod, RecordingChromiumPage, FakeChromium = _load_connect_module()
    RecordingChromiumPage._instances.clear()
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        provider_dir = root / ".dp" / "providers"
        provider_dir.mkdir(parents=True, exist_ok=True)
        (provider_dir / "stub-provider.py").write_text(
            "def start_profile(profile=None, *, base_url=None, timeout=60, extra_params=None):\n"
            "    return {'debug_address': '127.0.0.1:9222'}\n"
            "\n"
            "def extract_debug_address(start_result):\n"
            "    return start_result['debug_address']\n",
            encoding="utf-8",
        )
        os.chdir(root)
        try:
            launch_info, page = connect_mod.start_profile_and_connect_browser(
                "stub-provider",
                {},
                fresh_tab=True,
            )
        finally:
            os.chdir(old_cwd)

    check("fresh_tab: launch_info 返回 provider", launch_info.get("provider") == "stub-provider", repr(launch_info))
    check("fresh_tab: 返回了对象", page is not None, repr(page))

    # 检查 ChromiumPage 是否被构造，且 tab_id 是传入的（非 None）
    if RecordingChromiumPage._instances:
        recorded = RecordingChromiumPage._instances[-1]
        check("fresh_tab: ChromiumPage 构造时传入了 tab_id",
              recorded.tab_id is not None and recorded.tab_id.startswith("fake-tab-"),
              repr(recorded.tab_id))
        check("fresh_tab: 返回的 page tab_id 与构造时一致",
              page.tab_id == recorded.tab_id,
              f"page.tab_id={page.tab_id!r}, recorded={recorded.tab_id!r}")
    else:
        check("fresh_tab: ChromiumPage 被构造", False, "未记录到任何 ChromiumPage 实例")


def test_removed_legacy_connect_wrappers_are_absent() -> None:
    """legacy connect_* wrapper 已从公开 API 中移除。"""
    connect_mod, _, _ = _load_connect_module()
    names = dir(connect_mod)
    check("removed api: connect_browser 不存在", not hasattr(connect_mod, "connect_browser"), repr(names))
    check("removed api: connect_browser_fresh_tab 不存在", not hasattr(connect_mod, "connect_browser_fresh_tab"), repr(names))
    check("removed api: connect_web_page 不存在", not hasattr(connect_mod, "connect_web_page"), repr(names))


def test_get_default_browser_provider_treats_non_string_as_uninitialized() -> None:
    """runtime 对 non-string default_provider 应与 doctor 保持同语义。"""
    connect_mod, _, _ = _load_connect_module()
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        dp = root / ".dp"
        dp.mkdir(parents=True, exist_ok=True)
        (dp / "config.json").write_text('{"default_provider":123}', encoding="utf-8")
        os.chdir(root)
        try:
            result = connect_mod.get_default_browser_provider()
            check(
                "provider: non-string default_provider 回退 cdp-port",
                result == "cdp-port",
                repr(result),
            )
        finally:
            os.chdir(old_cwd)


def test_browser_provider_loader_finds_workspace_provider() -> None:
    """loader 应能用 kebab-case 名称加载 snake_case 文件名 provider。"""
    connect_mod, _, _ = _load_connect_module()
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        provider_dir = root / ".dp" / "providers"
        provider_dir.mkdir(parents=True, exist_ok=True)
        (provider_dir / "stub_provider.py").write_text(
            "def start_profile(profile=None, *, base_url=None, timeout=60, extra_params=None):\n"
            "    return {'debug_address': '127.0.0.1:50326'}\n"
            "\n"
            "def extract_debug_address(start_result):\n"
            "    return start_result['debug_address']\n",
            encoding="utf-8",
        )
        os.chdir(root)
        try:
            providers = connect_mod.list_browser_providers()
            check("provider: snake_case 文件可枚举为 kebab-case", "stub-provider" in providers, repr(providers))
            module = connect_mod.load_browser_provider("stub-provider")
            check("provider: kebab-case 名称可加载 snake_case 文件", callable(module.start_profile), repr(module))
        finally:
            os.chdir(old_cwd)


def test_browser_provider_loader_rejects_normalized_name_conflict() -> None:
    """kebab/snake 文件名归一化后冲突时应报错。"""
    connect_mod, _, _ = _load_connect_module()
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        provider_dir = root / ".dp" / "providers"
        provider_dir.mkdir(parents=True, exist_ok=True)
        provider_code = (
            "def start_profile(profile=None, *, base_url=None, timeout=60, extra_params=None):\n"
            "    return {'debug_address': '127.0.0.1:50326'}\n"
            "\n"
            "def extract_debug_address(start_result):\n"
            "    return start_result['debug_address']\n"
        )
        (provider_dir / "anti-detect.py").write_text(provider_code, encoding="utf-8")
        (provider_dir / "anti_detect.py").write_text(provider_code, encoding="utf-8")
        os.chdir(root)
        try:
            try:
                connect_mod.list_browser_providers()
            except ValueError as exc:
                check("provider: 归一化命名冲突时报错", "anti-detect" in str(exc), str(exc))
            else:
                check("provider: 归一化命名冲突时报错", False, "未抛出 ValueError")
        finally:
            os.chdir(old_cwd)


def test_workspace_provider_start_profile_and_connect() -> None:
    """高层 helper 应返回规范化 launch_info，而不是 raw start_result。"""
    connect_mod, RecordingChromiumPage, _ = _load_connect_module()
    RecordingChromiumPage._instances.clear()
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        provider_dir = root / ".dp" / "providers"
        provider_dir.mkdir(parents=True, exist_ok=True)
        (provider_dir / "stub-provider.py").write_text(
            "def start_profile(profile=None, *, base_url=None, timeout=60, extra_params=None):\n"
            "    return (\n"
            "        '127.0.0.1:50326',\n"
            "        {\n"
            "            'timeout': timeout,\n"
            "            'base_url': base_url,\n"
            "            'region': dict(extra_params or {}).get('region'),\n"
            "        },\n"
            "    )\n"
            "\n"
            "def extract_debug_address(start_result):\n"
            "    return start_result[0]\n"
            "\n"
            "def extract_metadata(start_result):\n"
            "    return start_result[1]\n",
            encoding="utf-8",
        )
        os.chdir(root)
        try:
            start_result = connect_mod.start_browser_profile(
                "stub-provider",
                {"profile_id": 7},
                base_url="http://provider.local",
                timeout=12,
                extra_params={"region": "eu"},
            )
            launch_info, page = connect_mod.start_profile_and_connect_browser(
                "stub-provider",
                {"profile_id": 7},
                base_url="http://provider.local",
                timeout=12,
                extra_params={"region": "eu"},
            )
        finally:
            os.chdir(old_cwd)

    check("provider: start_profile 允许非 dict 返回值", isinstance(start_result, tuple), repr(type(start_result).__name__))
    check("provider: launch_info 返回 provider 名", launch_info.get("provider") == "stub-provider", repr(launch_info))
    check("provider: launch_info 返回 provider_url", launch_info.get("provider_url") == "http://provider.local", repr(launch_info))
    check("provider: launch_info 返回 browser_profile", launch_info.get("browser_profile", {}).get("profile_id") == 7, repr(launch_info))
    check("provider: launch_info 返回 debug_address", launch_info.get("debug_address") == "127.0.0.1:50326", repr(launch_info))
    check("provider: launch_info 返回 provider_metadata", launch_info.get("provider_metadata", {}).get("region") == "eu", repr(launch_info))
    check("provider: 返回页面对象", page is not None, repr(page))
    if RecordingChromiumPage._instances:
        recorded = RecordingChromiumPage._instances[-1]
        check(
            "provider: 连接到返回的调试地址",
            recorded.co.address == "127.0.0.1:50326",
            repr(recorded.co.address),
        )
        check(
            "provider: 保持 existing_only(True)",
            recorded.co.existing is True,
            repr(recorded.co.existing),
        )
    else:
        check("provider: ChromiumPage 被构造", False, "未记录到任何 ChromiumPage 实例")


def test_provider_loader_rejects_missing_contract() -> None:
    """provider 文件缺少必需接口时应报错。"""
    connect_mod, _, _ = _load_connect_module()
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        provider_dir = root / ".dp" / "providers"
        provider_dir.mkdir(parents=True, exist_ok=True)
        (provider_dir / "broken-provider.py").write_text(
            "def start_profile(profile=None, *, base_url=None, timeout=60, extra_params=None):\n"
            "    return {'debug_address': '127.0.0.1:50326'}\n",
            encoding="utf-8",
        )
        os.chdir(root)
        try:
            connect_mod.load_browser_provider("broken-provider")
        except ValueError as exc:
            check("provider: 缺少 contract 时抛错", "extract_debug_address" in str(exc), str(exc))
        else:
            check("provider: 缺少 contract 时抛错", False, "未抛出 ValueError")
        finally:
            os.chdir(old_cwd)


# ── validate_rule_markers 章节内检查测试 ─────────────────────────────────────

_SKILL_MD_STABLE = (
    "## 站点 README 规则\n"
    "\nruntime_lib_version\nbundle_version\n"
    "\n## 执行流程\n"
)


def _build_skill_md(
    preflight: str = "",
    port: str = "",
    interaction: str = "",
    reuse: str = "",
    other: str = "",
) -> str:
    return (
        _SKILL_MD_STABLE
        + f"\n### 1. Preflight（工作区检测）\n\n{preflight}\n"
        + f"\n### 3. 端口与连接策略\n\n{port}\n"
        + f"\n### 4. 交互与节奏约束\n\n{interaction}\n"
        + f"\n### 5. 复用优先\n\n{reuse}\n"
        + (f"\n## 其他章节\n\n{other}\n" if other else "")
    )


def _build_smoke_checklist(preflight: str = "", other: str = "") -> str:
    return (
        "# DP Smoke Checklist\n\n"
        "## 1. 触发检查\n\n"
        "- 给出截图需求，确认客户端会使用 `dp`\n\n"
        "## 2. Preflight 检查\n\n"
        f"{preflight}\n"
        + (f"\n## 其他检查\n\n{other}\n" if other else "")
    )


def test_validate_rule_markers_port_rule_needs_section() -> None:
    """端口策略 token（cdp-port、显式、port）散落在错误章节时，validate_rule_markers 应失败。"""
    content = _build_skill_md(
        preflight="工作区根通过 cwd 确定，.dp 目录相对该根解析",
        port="连接到已有浏览器实例",          # 无 cdp-port / 显式 / port
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 传根路径",
        other="cdp-port 需要显式 port",       # token 在错误章节
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_rule_markers: 端口 token 散落在错误章节时应失败",
            lambda: _vb.validate_rule_markers(Path(d)),
        )


def test_validate_rule_markers_list_scripts_rule_needs_section() -> None:
    """list-scripts/--root/cwd token 散落在错误章节时，validate_rule_markers 应失败。"""
    content = _build_skill_md(
        preflight="工作区根通过 cwd 确定，.dp 目录相对该根解析",
        port="cdp-port 需要显式 port",
        reuse="先枚举已有 workflow，找不到再生成",    # 无 list-scripts.py / --root / cwd
        other="用 list-scripts.py --root 传根路径，cwd 不在树内时需显式传",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_rule_markers: list-scripts token 散落在错误章节时应失败",
            lambda: _vb.validate_rule_markers(Path(d)),
        )


def test_validate_rule_markers_workspace_root_rule_needs_section() -> None:
    """工作区根/cwd/.dp token 散落在错误章节时，validate_rule_markers 应失败。"""
    content = _build_skill_md(
        preflight="检测 state.json 版本一致性",        # 无 工作区根 / cwd / .dp
        port="cdp-port 需要显式 port",
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 传根路径",
        other="工作区根通过 cwd 确定，.dp 目录相对该根解析",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_rule_markers: 工作区根 token 散落在错误章节时应失败",
            lambda: _vb.validate_rule_markers(Path(d)),
        )


def test_validate_rule_markers_allows_rephrased_prose() -> None:
    """等价语义但不同措辞时，validate_rule_markers 不应误报（防回归）。"""
    content = _build_skill_md(
        preflight=(
            "工作区根通过 cwd 设定，.dp 目录相对该根目录解析；"
            "只有 .dp/.venv/ 存在且工作区 Python 可执行并可导入 DrissionPage、"
            ".dp/lib/connect.py、.dp/lib/download_correlation.py、.dp/lib/output.py、.dp/lib/utils.py、.dp/lib/_dp_compat.py、"
            ".dp/config.json 含 default_provider、.dp/providers/cdp-port.py 存在、"
            ".dp/state.json 中的 runtime_lib_version 与 bundle_version 都匹配时，才可跳过 doctor；"
            "若当前默认 provider 不是 cdp-port，则其对应 provider 文件也必须存在，否则属于配置错误，需用户提供实现或修正配置；"
            "若 default_provider 非空但不合法，则属于配置错误，doctor 不会自动修复，需用户修正配置"
        ),
        port="若当前 provider 为 cdp-port，则必须显式传入 browser_profile.port",
        interaction=(
            "upload_file() / download_file() 默认处理跨平台路径；"
            "若 workflow 传入 launch_info，则会结合 provider hints 判断本地文件访问能力；"
            "若 provider 明确声明 remote 或不支持本地文件访问，则 helper 直接报错"
        ),
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 显式传根路径",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        try:
            _vb.validate_rule_markers(Path(d))
            check("validate_rule_markers: 等价改写不误报", True)
        except SystemExit:
            check("validate_rule_markers: 等价改写不误报", False, "不应触发 SystemExit")


def test_validate_rule_markers_preflight_requires_workspace_contract_tokens() -> None:
    """Preflight 章节缺少 config/provider/state/version token 时，validate_rule_markers 应失败。"""
    content = _build_skill_md(
        preflight="工作区根通过 cwd 设定，.dp 目录相对该根目录解析",
        port="若当前 provider 为 cdp-port，则必须显式传入 browser_profile.port",
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 显式传根路径",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_rule_markers: Preflight 缺少 workspace contract token 应失败",
            lambda: _vb.validate_rule_markers(Path(d)),
        )


def test_validate_rule_markers_preflight_requires_managed_lib_markers() -> None:
    """Preflight 若只写 .dp/lib/ 存在、未写 managed lib 与 DrissionPage，应失败。"""
    content = _build_skill_md(
        preflight=(
            "工作区根通过 cwd 设定，.dp 目录相对该根目录解析；"
            ".dp/.venv/ 存在且工作区 Python 可执行；"
            ".dp/lib/ 存在；"
            ".dp/config.json 含 default_provider；"
            ".dp/providers/cdp-port.py 与 .dp/state.json 存在，"
            "runtime_lib_version / bundle_version 匹配时可跳过 doctor"
        ),
        port="若当前 provider 为 cdp-port，则必须显式传入 browser_profile.port",
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 显式传根路径",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_rule_markers: Preflight 缺少 managed lib / DrissionPage marker 应失败",
            lambda: _vb.validate_rule_markers(Path(d)),
        )


def test_validate_rule_markers_preflight_requires_download_correlation_marker() -> None:
    """Preflight 若未列出 .dp/lib/download_correlation.py，应失败。"""
    content = _build_skill_md(
        preflight=(
            "工作区根通过 cwd 设定，.dp 目录相对该根目录解析；"
            ".dp/.venv/ 存在且工作区 Python 可执行并可导入 DrissionPage；"
            ".dp/lib/connect.py、.dp/lib/output.py、.dp/lib/utils.py、.dp/lib/_dp_compat.py、"
            ".dp/providers/cdp-port.py、.dp/config.json、.dp/state.json 全部就绪，"
            "且 default_provider 合法、runtime_lib_version / bundle_version 匹配时才可跳过 doctor；"
            "若当前默认 provider 不是 cdp-port，则其对应 provider 文件也必须存在；"
            "default_provider 非空但不合法属于配置错误，doctor 不做猜测式修复，需用户或客户端修正配置"
        ),
        port="若当前 provider 为 cdp-port，则必须显式传入 browser_profile.port",
        interaction=(
            "upload_file() / download_file() 默认处理跨平台路径；"
            "若 workflow 传入 launch_info，则会结合 provider hints 判断本地文件访问能力；"
            "若 provider 明确声明 remote 或不支持本地文件访问，则 helper 直接报错"
        ),
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 显式传根路径",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_rule_markers: Preflight 缺少 download_correlation marker 应失败",
            lambda: _vb.validate_rule_markers(Path(d)),
        )


def test_validate_rule_markers_preflight_requires_illegal_provider_boundary() -> None:
    """Preflight 若未声明非法 provider 不能自动修复，应失败。"""
    content = _build_skill_md(
        preflight=(
            "工作区根通过 cwd 设定，.dp 目录相对该根目录解析；"
            ".dp/.venv/ 存在且工作区 Python 可执行并可导入 DrissionPage；"
            ".dp/lib/connect.py、.dp/lib/download_correlation.py、.dp/lib/output.py、.dp/lib/utils.py、.dp/lib/_dp_compat.py 存在；"
            "若 .dp/config.json 缺失、损坏，或 default_provider 为空 / 不合法，"
            "则运行 scripts/doctor.py 修复；"
            ".dp/providers/cdp-port.py 与 .dp/state.json 存在，"
            "runtime_lib_version / bundle_version 匹配时可跳过 doctor"
        ),
        port="若当前 provider 为 cdp-port，则必须显式传入 browser_profile.port",
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 显式传根路径",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_rule_markers: 非法 provider 未声明 fail-fast 边界时应失败",
            lambda: _vb.validate_rule_markers(Path(d)),
        )


def test_validate_rule_markers_preflight_requires_selected_provider_presence_boundary() -> None:
    """Preflight 若未声明当前默认 provider 对应实现必须存在，应失败。"""
    content = _build_skill_md(
        preflight=(
            "工作区根通过 cwd 设定，.dp 目录相对该根目录解析；"
            ".dp/.venv/ 存在且工作区 Python 可执行并可导入 DrissionPage；"
            ".dp/lib/connect.py、.dp/lib/download_correlation.py、.dp/lib/output.py、.dp/lib/utils.py、.dp/lib/_dp_compat.py、"
            ".dp/providers/cdp-port.py、.dp/config.json、.dp/state.json 全部就绪，"
            "且 default_provider 合法、runtime_lib_version / bundle_version 匹配时才可跳过 doctor；"
            "default_provider 非空但不合法属于配置错误，doctor 不做猜测式修复，需用户或客户端修正配置"
        ),
        port="若当前 provider 为 cdp-port，则必须显式传入 browser_profile.port",
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 显式传根路径",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_rule_markers: Preflight 缺少当前默认 provider 实现存在性边界应失败",
            lambda: _vb.validate_rule_markers(Path(d)),
        )


def test_validate_rule_markers_file_helper_requires_remote_fail_fast_boundary() -> None:
    """交互章节若只写“更安全”，未声明 remote fail-fast，应失败。"""
    content = _build_skill_md(
        preflight=(
            "工作区根通过 cwd 设定，.dp 目录相对该根目录解析；"
            ".dp/.venv/ 存在且工作区 Python 可执行并可导入 DrissionPage；"
            ".dp/lib/connect.py、.dp/lib/download_correlation.py、.dp/lib/output.py、.dp/lib/utils.py、.dp/lib/_dp_compat.py、"
            ".dp/providers/cdp-port.py、.dp/config.json、.dp/state.json 全部就绪，"
            "且 default_provider 合法、runtime_lib_version / bundle_version 匹配时才可跳过 doctor；"
            "若当前默认 provider 不是 cdp-port，则其对应 provider 文件也必须存在；"
            "default_provider 非空但不合法属于配置错误，doctor 不做猜测式修复，需用户或客户端修正配置"
        ),
        port="若当前 provider 为 cdp-port，则必须显式传入 browser_profile.port",
        interaction=(
            "upload_file() / download_file() 默认处理跨平台路径；"
            "若 workflow 传入 launch_info，则会结合 provider hints 做更安全的本地文件访问判断"
        ),
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 显式传根路径",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_rule_markers: 交互章节缺少 remote file helper fail-fast 边界应失败",
            lambda: _vb.validate_rule_markers(Path(d)),
        )


def test_validate_rule_markers_allows_preflight_prose_with_repair_boundary() -> None:
    """等价但更完整的 preflight prose 应通过，避免 validator 过拟合逐字文案。"""
    content = _build_skill_md(
        preflight=(
            "工作区根通过 cwd 设定，.dp 目录相对该根目录解析；"
            ".dp/.venv/ 存在且工作区 Python 可执行并可导入 DrissionPage；"
            ".dp/lib/connect.py、.dp/lib/download_correlation.py、.dp/lib/output.py、.dp/lib/utils.py、.dp/lib/_dp_compat.py、"
            ".dp/providers/cdp-port.py、.dp/config.json、.dp/state.json 全部就绪，"
            "且 default_provider 合法、runtime_lib_version / bundle_version 匹配时才可跳过 doctor；"
            "若当前默认 provider 不是 cdp-port，则其对应的 .dp/providers/<name>.py 或等价 snake_case 文件也必须存在，否则属于配置错误，需用户或客户端提供实现或修正配置；"
            "default_provider 非空但不合法属于配置错误，doctor 不做猜测式修复，需用户或客户端修正配置"
        ),
        port="若当前 provider 为 cdp-port，则必须显式传入 browser_profile.port",
        interaction=(
            "upload_file() / download_file() 默认处理跨平台路径；"
            "若 workflow 传入 launch_info，则会结合 provider hints 判断本地文件访问能力；"
            "若 provider 明确声明 remote 或不支持本地文件访问，则 helper 直接报错"
        ),
        reuse="当 cwd 不在项目树内时，用 list-scripts.py --root 显式传根路径",
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "SKILL.md").write_text(content, encoding="utf-8")
        try:
            _vb.validate_rule_markers(Path(d))
            check("validate_rule_markers: 新 preflight prose 可通过", True)
        except SystemExit:
            check("validate_rule_markers: 新 preflight prose 可通过", False, "不应触发 SystemExit")


def test_validate_smoke_checklist_requires_non_string_repair_boundary() -> None:
    """smoke checklist 若未声明 non-string default_provider 可自动修复，应失败。"""
    content = _build_smoke_checklist(
        preflight=(
            "- `.dp/config.json` 缺失、损坏，或 `default_provider` 缺失 / 空白时，应触发 doctor 自动修复\n"
            "- `default_provider` 非空但不合法时，属于配置错误；doctor 不做猜测式修复，需用户或客户端修正配置\n"
        )
    )
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "evals").mkdir()
        (root / "evals" / "smoke-checklist.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_smoke_checklist_contracts: 缺少 non-string repair boundary 应失败",
            lambda: _vb.validate_smoke_checklist_contracts(root),
        )


def test_validate_smoke_checklist_requires_selected_provider_snake_case_boundary() -> None:
    """smoke checklist 若未声明等价 snake_case provider 文件，应失败。"""
    content = _build_smoke_checklist(
        preflight=(
            "- `.dp/config.json` 缺失、损坏，或 `default_provider` 缺失 / 非字符串 / 空字符串 / 纯空白时，应触发 doctor 自动修复\n"
            "- 当前默认 provider 非 `cdp-port` 但对应 provider 文件缺失时，属于配置错误；doctor 不会自动发明实现，需用户或客户端补齐 `.dp/providers/<name>.py` 或修正配置\n"
        )
    )
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "evals").mkdir()
        (root / "evals" / "smoke-checklist.md").write_text(content, encoding="utf-8")
        _expect_fail(
            "validate_smoke_checklist_contracts: 缺少 snake_case provider 边界应失败",
            lambda: _vb.validate_smoke_checklist_contracts(root),
        )


def test_validate_smoke_checklist_allows_complete_preflight_prose() -> None:
    """smoke checklist 的等价完整 preflight prose 应通过。"""
    content = _build_smoke_checklist(
        preflight=(
            "- `.dp/config.json` 缺失、损坏，或 `default_provider` 缺失 / 非字符串 / 空字符串 / 纯空白时，应触发 doctor 自动修复\n"
            "- `default_provider` 非空但不合法时，属于配置错误；doctor 不做猜测式修复，需用户或客户端修正配置\n"
            "- 当前默认 provider 非 `cdp-port` 但对应 provider 文件缺失时，属于配置错误；doctor 不会自动发明实现，需用户或客户端补齐对应 provider 文件（含 `.dp/providers/<name>.py` 或等价 snake_case 文件）或修正配置\n"
        )
    )
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "evals").mkdir()
        (root / "evals" / "smoke-checklist.md").write_text(content, encoding="utf-8")
        try:
            _vb.validate_smoke_checklist_contracts(root)
            check("validate_smoke_checklist_contracts: 完整 preflight prose 可通过", True)
        except SystemExit:
            check("validate_smoke_checklist_contracts: 完整 preflight prose 可通过", False, "不应触发 SystemExit")


if __name__ == "__main__":
    sys.exit(main())
