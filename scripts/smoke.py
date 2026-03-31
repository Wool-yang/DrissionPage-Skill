#!/usr/bin/env python3
"""
dp local smoke runner — 验证 dp skill 在真实浏览器环境的运行态 contract。

运行前提：
  1. .dp/ 已初始化（运行过 scripts/doctor.py）
  2. 若工作区默认 provider 为 cdp-port，浏览器已在你将显式传入的调试端口上运行

用法：
  python <skill-root>/scripts/smoke.py
  python <skill-root>/scripts/smoke.py --port <port> --fixture-port 18080
  python <skill-root>/scripts/smoke.py --case screenshot

退出码：
  0  全部通过
  1  有 case 失败
  2  环境未就绪（.dp/ 或浏览器未就绪）
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True

SKILL_ROOT = Path(__file__).resolve().parent.parent
# 通过 importlib 复用 doctor.py 的 venv_python()，避免重复维护 OS-aware 逻辑
import importlib.util as _ilu
_doctor_spec = _ilu.spec_from_file_location("_doctor_smoke", Path(__file__).parent / "doctor.py")
_doctor_mod = _ilu.module_from_spec(_doctor_spec)
_doctor_spec.loader.exec_module(_doctor_mod)
venv_python = _doctor_mod.venv_python
FIXTURES_DIR = SKILL_ROOT / "evals" / "fixtures"
WORKSPACE = Path(".dp")
SITE = "dp-smoke"   # smoke 专用 site name，便于查找和清理
DEFAULT_FALLBACK_PROVIDER = "cdp-port"


# ── 工具 ──────────────────────────────────────────────────────────────────────

def _evaluate_workspace() -> dict:
    """复用 doctor 的结构化 readiness 判定。"""
    return _doctor_mod.evaluate_workspace(WORKSPACE)


def _get_default_provider() -> str | None:
    """返回 doctor 视角下规范化后的工作区默认 provider。"""
    value = _evaluate_workspace().get("default_provider")
    return value if isinstance(value, str) and value else None


def _normalize_port(port: str | None) -> str | None:
    value = (port or "").strip()
    return value or None


def _check_workspace() -> str | None:
    """返回首个发现的问题；无问题返回 None。"""
    issues = _evaluate_workspace().get("issues", [])
    if not isinstance(issues, list) or not issues:
        return None
    return str(issues[0])


def _check_browser(port: str) -> bool:
    """尝试连接浏览器 DevTools 端点，返回是否可连。"""
    try:
        import urllib.request
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3)
        return True
    except Exception:
        return False


def _latest_run_dir(case: str) -> Path | None:
    """返回 dp-smoke/output/<case>/ 下最新的时间戳目录，不存在返回 None。"""
    base = WORKSPACE / "projects" / SITE / "output" / case
    if not base.exists():
        return None
    dirs = sorted(base.iterdir(), key=lambda p: p.name, reverse=True)
    return dirs[0] if dirs else None


def _run_script(script: str, port: str | None, timeout: int = 60) -> bool:
    """将 script 写入 .dp/tmp/_smoke_case.py，用 venv Python 执行，返回是否成功。"""
    tmp = WORKSPACE / "tmp" / "_smoke_case.py"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(script, encoding="utf-8")
    try:
        cmd = [str(venv_python()), "-B", str(tmp)]
        if port:
            cmd.extend(["--port", port])
        result = subprocess.run(
            cmd,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            capture_output=True, text=True, encoding="utf-8",
            timeout=timeout,
        )
        if result.returncode != 0:
            if result.stdout.strip():
                print(f"    [stdout] {result.stdout.strip()[:300]}")
            print(f"    [stderr] {result.stderr.strip()[:300]}")
        return result.returncode == 0
    except subprocess.TimeoutExpired as e:
        if e.stdout:
            stdout = e.stdout.decode("utf-8", "ignore") if isinstance(e.stdout, bytes) else e.stdout
            print(f"    [stdout] {stdout.strip()[:300]}")
        if e.stderr:
            stderr = e.stderr.decode("utf-8", "ignore") if isinstance(e.stderr, bytes) else e.stderr
            print(f"    [stderr] {stderr.strip()[:300]}")
        print(f"    [timeout] case 超时（>{timeout}s），已强制终止", file=sys.stderr)
        return False
    except (OSError, PermissionError) as e:
        print(f"    [error] venv Python 不可执行：{e}", file=sys.stderr)
        return False


# ── Fixture HTTP Server ────────────────────────────────────────────────────────

class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_): pass   # 屏蔽 access log

    def do_GET(self):
        if self.path == "/cookie-echo":
            import json as _json
            body = _json.dumps({"cookies": self.headers.get("Cookie", "")}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/download-file":
            body = b"dp smoke test file\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="smoke-test.txt"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()


def _start_fixture_server(fixture_port: int) -> http.server.HTTPServer:
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", fixture_port),
        lambda *args, **kw: _SilentHandler(*args, directory=str(FIXTURES_DIR), **kw),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ── Smoke Case 脚本模板 ────────────────────────────────────────────────────────

def _lib_loader() -> str:
    """通用 lib 加载代码段。"""
    return f'''\
import sys
from pathlib import Path
sys.path.insert(0, r"{WORKSPACE / 'lib'}")
from connect import (
    build_default_browser_profile,
    get_default_browser_provider,
    parse_port,
    start_profile_and_connect_browser,
)
from output import site_run_dir
from utils import native_click, native_input, screenshot, save_json, mark_script_status, upload_file, download_file
provider = get_default_browser_provider()
browser_profile = build_default_browser_profile(provider, parse_port())
launch_info, page = start_profile_and_connect_browser(provider, browser_profile, fresh_tab=True)
'''


def _script_screenshot(base_url: str) -> str:
    return _lib_loader() + f'''\
try:
    page.get("{base_url}/basic.html")
    page.wait.doc_loaded()
    run = site_run_dir("{SITE}", "screenshot")
    screenshot(page, run / "full.png")
    print(f"[smoke] screenshot -> {{run / 'full.png'}}")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
'''


def _script_scrape(base_url: str) -> str:
    return _lib_loader() + f'''\
try:
    page.get("{base_url}/basic.html")
    page.wait.doc_loaded()
    run = site_run_dir("{SITE}", "scrape")
    items = [{{
        "text": ele.ele("tag:a").text,
        "href": ele.ele("tag:a").attr("href"),
    }} for ele in page.eles(".item")]
    save_json(items, run / "data.json")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
'''


def _script_form(base_url: str) -> str:
    return _lib_loader() + f'''\
try:
    page.get("{base_url}/basic.html")
    page.wait.doc_loaded()
    run = site_run_dir("{SITE}", "form")
    native_input(page.ele("#name"), "smoke-user")
    native_click(page.ele("#submit-btn"))
    page.wait(0.5)
    screenshot(page, run / "result.png")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
'''


def _script_upload(base_url: str, upload_file: str) -> str:
    return _lib_loader() + f'''\
try:
    page.get("{base_url}/upload.html")
    page.wait.doc_loaded()
    run = site_run_dir("{SITE}", "upload")
    expected_name = Path(r"{upload_file}").name
    upload_file(page.ele("#file-input"), r"{upload_file}", launch_info=launch_info)
    result_text = ""
    for _ in range(40):
        result_text = page.run_js(
            "(document.getElementById('upload-result') && "
            "document.getElementById('upload-result').textContent) || ''",
            as_expr=True,
        ) or ""
        if expected_name in result_text:
            break
        page.wait(0.25)
    assert expected_name in result_text, f"upload result missing: {{result_text!r}}"
    save_json({{"result_text": result_text}}, run / "result.json")
    page.ele("#upload-result").get_screenshot(path=str(run), name="result.png")
    page.get("about:blank")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
'''


def _script_download(base_url: str) -> str:
    return _lib_loader() + f'''\
try:
    page.get("{base_url}/download.html")
    page.wait.doc_loaded()
    run = site_run_dir("{SITE}", "download")
    mission = download_file(
        page.ele("#download-btn"),
        run,
        rename="smoke-test.txt",
        launch_info=launch_info,
    )
    print(f"[smoke] download -> {{run}}")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
'''


def _script_newtab(base_url: str) -> str:
    return _lib_loader() + f'''\
try:
    page.get("{base_url}/newtab.html")
    page.wait.doc_loaded()
    run = site_run_dir("{SITE}", "newtab")
    screenshot(page, run / "before.png")
    new_tab = page.ele("#open-tab").click.for_new_tab()
    new_tab.wait.doc_loaded()
    screenshot(new_tab, run / "newtab.png")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
'''


def _lib_loader_web_page() -> str:
    """WebPage 专用 lib 加载（导入 connect_web_page 而非 connect_browser）。"""
    return f'''\
import sys
from pathlib import Path
sys.path.insert(0, r"{WORKSPACE / 'lib'}")
from connect import (
    build_default_browser_profile,
    get_default_browser_provider,
    parse_port,
    start_profile_and_connect_web_page,
)
from output import site_run_dir
from utils import save_json, mark_script_status
'''


def _script_web_page_sync(base_url: str) -> str:
    return _lib_loader_web_page() + f'''\
import json as _json
try:
    run = site_run_dir("{SITE}", "web-page-sync")
    provider = get_default_browser_provider()
    browser_profile = build_default_browser_profile(provider, parse_port())
    _, page = start_profile_and_connect_web_page(provider, browser_profile, mode="d")

    # 在 d 模式下导航到 fixture 域（建立 cookie 上下文）
    page.get("{base_url}/basic.html")
    page.wait.doc_loaded()

    # 在浏览器里种一个标记 cookie
    page.run_js(\'document.cookie = "dp_smoke_cookie=sync_ok; path=/"\')

    # 切换到 session 模式，DrissionPage 应同步浏览器 cookies
    page.change_mode("s")

    # 请求 cookie-echo 端点，验证 cookie 出现在 request 里
    page.get("{base_url}/cookie-echo")
    data = _json.loads(page.html)
    cookies_str = data.get("cookies", "")
    assert "dp_smoke_cookie=sync_ok" in cookies_str, f"cookie 同步失败：{{cookies_str!r}}"

    save_json({{"synced": True, "cookies": cookies_str}}, run / "data.json")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
'''


def _script_custom(base_url: str) -> str:
    return _lib_loader() + f'''\
try:
    page.get("{base_url}/basic.html")
    page.wait.doc_loaded()
    run = site_run_dir("{SITE}", "custom")   # 整个任务只调用一次
    screenshot(page, run / "list.png")
    native_click(page.ele(".item"))
    page.wait(0.3)
    screenshot(page, run / "detail.png")
    save_json({{"title": page.title, "url": page.url}}, run / "detail.json")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
'''


def _script_login(base_url: str) -> str:
    return _lib_loader() + f'''\
try:
    page.get("{base_url}/login.html")
    page.wait.doc_loaded()
    run = site_run_dir("{SITE}", "login")
    native_input(page.ele("#username"), "smoke-user")
    native_input(page.ele("#password"), "smoke-pass")
    native_click(page.ele("#login-btn"))
    page.wait(0.5)
    screenshot(page, run / "result.png")
    result_ele = page.ele("#login-result")
    result_text = result_ele.text if result_ele else ""
    assert "smoke-user" in result_text or "success" in result_text.lower(), f"登录结果未包含预期文字：{{result_text!r}}"
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
'''


def _lib_loader_session_page() -> str:
    """SessionPage 专用 lib 加载（不需要浏览器连接）。"""
    return f'''\
import sys
from pathlib import Path
sys.path.insert(0, r"{WORKSPACE / 'lib'}")
from output import site_run_dir
from utils import save_json, mark_script_status
from DrissionPage import SessionPage
'''


def _script_session_page(base_url: str) -> str:
    return _lib_loader_session_page() + f'''\
import json as _json
try:
    run = site_run_dir("{SITE}", "session-page")
    page = SessionPage()
    page.get("{base_url}/cookie-echo")
    data = _json.loads(page.html)
    assert isinstance(data, dict), f"响应不是 JSON dict: {{page.html[:200]!r}}"
    save_json(data, run / "data.json")
    mark_script_status("ok")
except Exception:
    mark_script_status("broken")
    raise
'''


# ── Case 验证逻辑 ──────────────────────────────────────────────────────────────

def _verify_screenshot() -> tuple[bool, str]:
    run = _latest_run_dir("screenshot")
    if not run:
        return False, "run-dir 不存在"
    if not (run / "full.png").exists():
        return False, f"缺少 full.png（run-dir={run}）"
    return True, str(run / "full.png")


def _verify_scrape() -> tuple[bool, str]:
    run = _latest_run_dir("scrape")
    if not run:
        return False, "run-dir 不存在"
    data_file = run / "data.json"
    if not data_file.exists():
        return False, "缺少 data.json"
    try:
        data = json.loads(data_file.read_text(encoding="utf-8"))
        if not isinstance(data, list) or len(data) < 3:
            return False, f"data.json items < 3（got {len(data) if isinstance(data, list) else type(data)}）"
    except Exception as e:
        return False, f"data.json 无效 JSON：{e}"
    return True, f"{len(data)} items → {data_file}"


def _verify_form() -> tuple[bool, str]:
    run = _latest_run_dir("form")
    if not run:
        return False, "run-dir 不存在"
    if not (run / "result.png").exists():
        return False, "缺少 result.png"
    return True, str(run / "result.png")


def _verify_upload(upload_file: str) -> tuple[bool, str]:
    run = _latest_run_dir("upload")
    if not run:
        return False, "run-dir 不存在"
    if not (run / "result.png").exists():
        return False, "缺少 result.png"
    result_json = run / "result.json"
    if not result_json.exists():
        return False, "缺少 result.json"
    try:
        data = json.loads(result_json.read_text(encoding="utf-8"))
        result_text = data.get("result_text", "")
    except Exception as e:
        return False, f"result.json 无效 JSON：{e}"
    # 被上传文件不应出现在 run-dir 内
    uploaded_name = Path(upload_file).name
    if (run / uploaded_name).exists():
        return False, f"contract 违反：被上传文件 {uploaded_name} 出现在 run-dir 内"
    if uploaded_name not in result_text:
        return False, f"上传结果未包含文件名：{result_text!r}"
    return True, f"result.png/result.json OK，{uploaded_name} 未进入 run-dir"


def _verify_download() -> tuple[bool, str]:
    run = _latest_run_dir("download")
    if not run:
        return False, "run-dir 不存在"
    target = run / "smoke-test.txt"
    if not target.exists():
        files = list(run.iterdir())
        return False, f"缺少 smoke-test.txt（run-dir 有：{[f.name for f in files]}）"
    try:
        content = target.read_text(encoding="utf-8")
        if "dp smoke test file" not in content:
            return False, f"smoke-test.txt 内容不符合预期：{content!r}"
    except Exception as e:
        return False, f"读取 smoke-test.txt 失败：{e}"
    return True, f"smoke-test.txt OK（{len(content)} bytes）"


def _verify_newtab() -> tuple[bool, str]:
    run = _latest_run_dir("newtab")
    if not run:
        return False, "run-dir 不存在"
    missing = [f for f in ("before.png", "newtab.png") if not (run / f).exists()]
    if missing:
        return False, f"缺少文件：{missing}"
    # 验证两个截图在同一 run-dir（已由 _latest_run_dir 保证）
    return True, f"both in {run}"


def _verify_custom() -> tuple[bool, str]:
    run = _latest_run_dir("custom")
    if not run:
        return False, "run-dir 不存在"
    missing = [f for f in ("list.png", "detail.png", "detail.json") if not (run / f).exists()]
    if missing:
        return False, f"缺少文件：{missing}"
    # 验证只有一个 run-dir
    base = WORKSPACE / "projects" / SITE / "output" / "custom"
    count = sum(1 for _ in base.iterdir() if _.is_dir())
    if count != 1:
        return False, f"run-dir 数量应为 1，实际为 {count}"
    return True, f"单一 run-dir，3 个输出文件 OK"


def _verify_login() -> tuple[bool, str]:
    run = _latest_run_dir("login")
    if not run:
        return False, "run-dir 不存在"
    if not (run / "result.png").exists():
        return False, "缺少 result.png"
    return True, f"result.png OK → {run}"


def _verify_session_page() -> tuple[bool, str]:
    run = _latest_run_dir("session-page")
    if not run:
        return False, "run-dir 不存在"
    data_file = run / "data.json"
    if not data_file.exists():
        return False, "缺少 data.json"
    try:
        data = json.loads(data_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return False, f"data.json 不是 dict：{type(data)}"
    except Exception as e:
        return False, f"data.json 无效 JSON：{e}"
    return True, f"SessionPage 响应已保存 → {data_file}"


def _verify_web_page_sync() -> tuple[bool, str]:
    run = _latest_run_dir("web-page-sync")
    if not run:
        return False, "run-dir 不存在"
    data_file = run / "data.json"
    if not data_file.exists():
        return False, "缺少 data.json"
    try:
        data = json.loads(data_file.read_text(encoding="utf-8"))
        if not data.get("synced"):
            return False, f"cookie 同步失败：{data}"
    except Exception as e:
        return False, f"data.json 无效 JSON：{e}"
    return True, f"cookie 同步验证通过 → {data_file}"


# ── 主流程 ────────────────────────────────────────────────────────────────────

ALL_CASES = ["screenshot", "scrape", "form", "upload", "download", "newtab", "web-page-sync", "custom", "login", "session-page"]
# session-page 使用 SessionPage()，不需要连接浏览器；其余 case 均需要浏览器
BROWSER_REQUIRED_CASES = frozenset(ALL_CASES) - {"session-page"}


def main() -> None:
    parser = argparse.ArgumentParser(description="dp local smoke runner")
    parser.add_argument("--port", default=None, help="当默认 provider 为 cdp-port 时必填的浏览器远程调试端口")
    parser.add_argument("--fixture-port", type=int, default=18080, help="本地 fixture HTTP 端口（默认 18080）")
    parser.add_argument("--case", default=None, choices=ALL_CASES, help="只运行指定 case")
    args = parser.parse_args()

    # 1. 环境检查
    ws_issue = _check_workspace()
    if ws_issue:
        print(f"[dp smoke] {ws_issue}", file=sys.stderr)
        sys.exit(2)

    # 2. 计算 cases_to_run
    cases_to_run = [args.case] if args.case else ALL_CASES

    # 3. 按 case 判断是否需要浏览器
    need_browser = any(c in BROWSER_REQUIRED_CASES for c in cases_to_run)
    default_provider = _get_default_provider()
    port = _normalize_port(args.port)
    if need_browser and default_provider == DEFAULT_FALLBACK_PROVIDER:
        if port is None:
            print(
                "[dp smoke] 当前工作区默认 provider 为 cdp-port，必须显式传入 --port <port>。",
                file=sys.stderr,
            )
            sys.exit(2)
        if not _check_browser(port):
            print(f"[dp smoke] 无法连接到浏览器（端口 {port}）。", file=sys.stderr)
            print("[dp smoke] 请先运行 start-chrome-cdp.bat（或等效脚本）启动带调试端口的 Chrome。", file=sys.stderr)
            sys.exit(2)

    # 4. 清理将要运行的 case 的历史产物，防止脚本失败时旧产物误报 PASS
    import shutil
    for case in cases_to_run:
        case_dir = WORKSPACE / "projects" / SITE / "output" / case
        if case_dir.exists():
            shutil.rmtree(case_dir)

    # 5. 启动 fixture server
    base_url = f"http://127.0.0.1:{args.fixture_port}"
    server = _start_fixture_server(args.fixture_port)
    print(f"[dp smoke] fixture server @ {base_url}")
    time.sleep(0.3)  # 等 server 就绪

    # 6. 准备 upload 测试文件
    upload_tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    upload_tmp.write("dp smoke upload test\n")
    upload_tmp.close()
    upload_file = upload_tmp.name

    # 7. 运行 cases
    scripts = {
        "screenshot":   lambda: _script_screenshot(base_url),
        "scrape":       lambda: _script_scrape(base_url),
        "form":         lambda: _script_form(base_url),
        "upload":       lambda: _script_upload(base_url, upload_file),
        "download":     lambda: _script_download(base_url),
        "newtab":       lambda: _script_newtab(base_url),
        "web-page-sync": lambda: _script_web_page_sync(base_url),
        "custom":       lambda: _script_custom(base_url),
        "login":         lambda: _script_login(base_url),
        "session-page":  lambda: _script_session_page(base_url),
    }
    verifiers = {
        "screenshot":   _verify_screenshot,
        "scrape":       _verify_scrape,
        "form":         _verify_form,
        "upload":       lambda: _verify_upload(upload_file),
        "download":     _verify_download,
        "newtab":       _verify_newtab,
        "web-page-sync": _verify_web_page_sync,
        "custom":       _verify_custom,
        "login":         _verify_login,
        "session-page":  _verify_session_page,
    }

    results: list[tuple[str, bool, str]] = []
    for case in cases_to_run:
        print(f"\n[dp smoke] ── {case} ──")
        script_ok = _run_script(scripts[case](), port)
        ok, detail = verifiers[case]()
        status = "PASS" if (script_ok and ok) else "FAIL"
        results.append((case, status == "PASS", detail if ok else f"脚本{'OK' if script_ok else '失败'}，contract：{detail}"))
        print(f"  {status}  {detail if ok else detail}")

    # 8. 清理
    server.shutdown()
    Path(upload_file).unlink(missing_ok=True)

    # 9. 汇总
    print("\n" + "=" * 44)
    passed = sum(1 for _, ok, _ in results if ok)
    for case, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        print(f"  {mark}  {case:<12}  {detail}")
    print("=" * 44)
    print(f"  {passed}/{len(results)} passed")

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
