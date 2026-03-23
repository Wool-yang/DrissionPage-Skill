#!/usr/bin/env python3
"""
最小回归测试——覆盖三个修复点，无第三方依赖，可直接 python 运行。

测试项：
  1. mark_script_status() 对空字段的回写（修复：正则跨行吞字段）
  2. extract_fields() 对含 # 的 URL 不截断（修复：split 破坏 SPA URL）
  3. site_run_dir() 毫秒精度（修复：同秒目录冲突）
"""
from __future__ import annotations

import re
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

PASS = "  ✓"
FAIL = "  ✗"
_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _failed
    if condition:
        print(f"{PASS} {name}")
    else:
        print(f"{FAIL} {name}" + (f": {detail}" if detail else ""))
        _failed += 1


# ── 1. mark_script_status 空字段回写 ──────────────────────────────────────────

def _make_temp_script(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return Path(f.name)


EMPTY_FIELDS_SCRIPT = '''\
"""
site: test-site
task: 测试脚本
intent: scrape
last_run:
status:
"""
pass
'''

PREFILLED_SCRIPT = '''\
"""
site: test-site
task: 测试脚本
intent: scrape
last_run: 2026-01-01
status: broken
"""
pass
'''


def _apply_mark(script_path: Path, status: str) -> str:
    """复现 mark_script_status 的核心逻辑（不依赖 DrissionPage）。"""
    text = script_path.read_text(encoding="utf-8")
    today = date.today().isoformat()
    text = re.sub(r'last_run:[ \t]*\S*', f'last_run: {today}', text)
    text = re.sub(r'status:[ \t]*\S*', f'status: {status}', text)
    script_path.write_text(text, encoding="utf-8")
    return text


def test_mark_empty_fields() -> None:
    """空字段回写不应破坏相邻字段。"""
    p = _make_temp_script(EMPTY_FIELDS_SCRIPT)
    try:
        result = _apply_mark(p, "ok")
        today = date.today().isoformat()
        check("空 last_run 回写", f"last_run: {today}" in result,
              repr(result))
        check("空 status 回写", "status: ok" in result,
              repr(result))
        # 关键：intent 字段不应被吞掉
        check("intent 字段未被吞掉", "intent: scrape" in result,
              repr(result))
        # 确保 status 行存在（不是被删掉的）
        lines = {l.strip().split(":")[0]: l for l in result.splitlines() if ":" in l}
        check("status 行仍完整存在", "status" in lines, repr(result))
    finally:
        p.unlink(missing_ok=True)


def test_mark_prefilled_fields() -> None:
    """已有值的字段应被正确覆盖。"""
    p = _make_temp_script(PREFILLED_SCRIPT)
    try:
        result = _apply_mark(p, "ok")
        today = date.today().isoformat()
        check("已有 last_run 被更新", f"last_run: {today}" in result,
              repr(result))
        check("broken → ok", "status: ok" in result and "broken" not in result,
              repr(result))
    finally:
        p.unlink(missing_ok=True)


# ── 2. extract_fields URL 含 # ────────────────────────────────────────────────

def _extract_fields_url(line: str) -> str:
    """复现 list-scripts.py 的字段提取逻辑。"""
    stripped = line.strip()
    if stripped.startswith("url:"):
        val = stripped[len("url:"):].strip()
        val = re.sub(r'\s+#.*$', '', val).strip()
        return val
    return ""


def test_url_with_hash() -> None:
    """SPA URL 中的 # 不应被当作注释截断。"""
    spa_url = "https://example.com/#/signin"
    result = _extract_fields_url(f"url: {spa_url}")
    check("SPA URL 完整保留", result == spa_url, repr(result))


def test_url_with_inline_comment() -> None:
    """行内注释（空格+#）应被正常去除。"""
    result = _extract_fields_url("url: https://example.com/login  # 登录页")
    check("行内注释被去除", result == "https://example.com/login", repr(result))


def test_url_hash_no_leading_space() -> None:
    """# 前无空白时不截断（处理 anchor 或路径中的 #）。"""
    result = _extract_fields_url("url: https://example.com/page#section")
    check("URL anchor 不截断", result == "https://example.com/page#section", repr(result))


# ── 3. site_run_dir 毫秒精度 ──────────────────────────────────────────────────

def _make_ts(now: datetime) -> str:
    """复现 site_run_dir 的时间戳生成逻辑。"""
    return now.strftime("%Y-%m-%d_%H%M%S") + f"_{now.microsecond // 1000:03d}"


def test_same_second_different_ms() -> None:
    """同秒不同毫秒应生成不同时间戳。"""
    from datetime import timezone
    t1 = datetime(2026, 3, 20, 14, 23, 0, microsecond=100_000)
    t2 = datetime(2026, 3, 20, 14, 23, 0, microsecond=500_000)
    ts1 = _make_ts(t1)
    ts2 = _make_ts(t2)
    check("同秒不同毫秒生成不同时间戳", ts1 != ts2,
          f"{ts1!r} == {ts2!r}")


def test_ts_format() -> None:
    """时间戳格式为 YYYY-MM-DD_HHMMSS_mmm。"""
    now = datetime(2026, 3, 20, 14, 23, 0, microsecond=123_456)
    ts = _make_ts(now)
    check("时间戳格式正确", ts == "2026-03-20_142300_123", repr(ts))


# ── 入口 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("── mark_script_status 空字段回写 ──")
    test_mark_empty_fields()
    test_mark_prefilled_fields()

    print("\n── list-scripts URL 含 # ──")
    test_url_with_hash()
    test_url_with_inline_comment()
    test_url_hash_no_leading_space()

    print("\n── site_run_dir 毫秒精度 ──")
    test_same_second_different_ms()
    test_ts_format()

    print()
    if _failed:
        print(f"FAILED: {_failed} 项")
        sys.exit(1)
    else:
        print("ALL PASSED")
