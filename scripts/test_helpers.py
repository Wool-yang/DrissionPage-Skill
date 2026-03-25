#!/usr/bin/env python3
"""
_rewrite_header_fields / mark_script_status 最小回归测试。
无第三方依赖，直接调真实实现。退出码 0=全过，1=有失败。
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

# 将 templates/ 加入 sys.path，使 utils 可在无 DrissionPage 环境下 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "templates"))
from utils import _rewrite_header_fields, mark_script_status  # noqa: E402

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

    print()
    if _failed:
        print(f"FAILED: {_failed} 项")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
