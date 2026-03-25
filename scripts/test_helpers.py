#!/usr/bin/env python3
"""
_rewrite_header_fields / mark_script_status / extract_fields / doctor.check 最小回归测试。
无第三方依赖，直接调真实实现。退出码 0=全过，1=有失败。
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True

# templates/ 加入 sys.path，使 utils / output 可在无 DrissionPage 环境下 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "templates"))
from utils import _rewrite_header_fields, mark_script_status  # noqa: E402
from output import normalize_site_name  # noqa: E402
import output as _output_mod  # noqa: E402

# list-scripts.py 文件名含连字符，用 importlib 加载
_ls_spec = importlib.util.spec_from_file_location(
    "list_scripts", Path(__file__).parent / "list-scripts.py"
)
_ls_mod = importlib.util.module_from_spec(_ls_spec)
_ls_spec.loader.exec_module(_ls_mod)
extract_fields = _ls_mod.extract_fields

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


# ── doctor.check() 行为测试 ───────────────────────────────────────────────────

import json as _json  # noqa: E402（已在顶层有 json，这里显式别名避免歧义）


def _patch_doctor(tmp: Path):
    """返回 context manager，临时将 doctor 模块的工作区全局变量指向 tmp/.dp。"""
    import contextlib

    @contextlib.contextmanager
    def ctx():
        dp = tmp / ".dp"
        dp.mkdir(parents=True, exist_ok=True)
        saved = {k: getattr(_doctor, k) for k in ("WORKSPACE", "VENV", "LIB", "STATE")}
        _doctor.WORKSPACE = dp
        _doctor.VENV = dp / ".venv"
        _doctor.LIB = dp / "lib"
        _doctor.STATE = dp / "state.json"
        try:
            yield dp
        finally:
            for k, v in saved.items():
                setattr(_doctor, k, v)

    return ctx()


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
            for name in ("connect.py", "output.py", "utils.py"):
                content = (lib_dir / name).read_text(encoding="utf-8")
                check(f"init: lib/{name} 已覆盖",
                      content != "# STALE CONTENT",
                      f"content[:40]={content[:40]!r}")

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
    """evals.json 含旧输出路径 output/YYYY-MM-DD/ 时 validate_output_contract 应失败。"""
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
        _expect_fail("validate: 旧输出路径应失败",
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

    print("\n── doctor.check() ──")
    test_doctor_check_state_missing()
    test_doctor_check_version_mismatch()
    test_doctor_check_state_corrupted()
    test_doctor_check_python_not_executable()
    test_doctor_write_state_fields()

    print("\n── doctor.init() ──")
    test_doctor_init_garbage_venv_no_traceback()
    test_doctor_init_lib_overwrite_and_state()

    print("\n── normalize_site_name ──")
    test_normalize_site_name()
    test_site_run_dir_normalizes()

    print("\n── doctor 其他行为 ──")
    test_doctor_init_always_rewrites_readme()
    test_install_path_independence()

    print("\n── validate_bundle 失败路径 ──")
    test_validate_missing_runtime_lib_version()
    test_validate_bundle_type_rejected()
    test_validate_old_output_contract_rejected()
    test_validate_agents_text_rejected()
    test_validate_missing_site_run_dir()

    print()
    if _failed:
        print(f"FAILED: {_failed} 项")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
