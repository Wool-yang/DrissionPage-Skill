#!/usr/bin/env python3
"""
dp local smoke runner — 验证 dp skill 在真实浏览器环境的运行态 contract。

运行前提：
  1. .dp/ 已初始化（运行过 scripts/doctor.py）
  2. 浏览器已以调试端口运行（外层工作区可用 start-chrome-cdp.bat 启动）

用法：
  python <skill-root>/scripts/smoke.py
  python <skill-root>/scripts/smoke.py --port 9222 --fixture-port 18080
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
FIXTURES_DIR = SKILL_ROOT / "evals" / "fixtures"
WORKSPACE = Path(".dp")
SITE = "dp-smoke"   # smoke 专用 site name，便于查找和清理


# ── 工具 ──────────────────────────────────────────────────────────────────────

def _venv_python() -> Path:
    win = WORKSPACE / ".venv" / "Scripts" / "python.exe"
    unix = WORKSPACE / ".venv" / "bin" / "python"
    return win if win.exists() else unix


def _check_workspace() -> str | None:
    """返回首个发现的问题；无问题返回 None。"""
    if not WORKSPACE.exists():
        return ".dp/ 不存在，请先运行 scripts/doctor.py 初始化工作区"
    py = _venv_python()
    try:
        if not py.exists():
            return ".dp/.venv/ 不存在，请先运行 scripts/doctor.py"
    except OSError:
        return ".dp/.venv/ 不可访问"
    if not (WORKSPACE / "lib" / "connect.py").exists():
        return ".dp/lib/ 缺失，请先运行 scripts/doctor.py"
    return None


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


def _run_script(script: str, port: str, timeout: int = 60) -> bool:
    """将 script 写入 .dp/tmp/_smoke_case.py，用 venv Python 执行，返回是否成功。"""
    tmp = WORKSPACE / "tmp" / "_smoke_case.py"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(script, encoding="utf-8")
    try:
        result = subprocess.run(
            [str(_venv_python()), "-B", str(tmp), "--port", port],
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
from connect import connect_browser_fresh_tab, parse_port
from output import site_run_dir
from utils import native_click, native_input, screenshot, save_json, mark_script_status, upload_file, download_file
page = connect_browser_fresh_tab(parse_port())
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
    upload_file(page.ele("#file-input"), r"{upload_file}")
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
    )
    if not isinstance(mission, Path):
        page.browser.wait.downloads_done(timeout=30)
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
from connect import connect_web_page, parse_port
from output import site_run_dir
from utils import save_json, mark_script_status
'''


def _script_web_page_sync(base_url: str) -> str:
    return _lib_loader_web_page() + f'''\
import json as _json
try:
    run = site_run_dir("{SITE}", "web-page-sync")
    page = connect_web_page(parse_port())   # d 模式（浏览器）

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
    files = list(run.iterdir())
    if not files:
        return False, "run-dir 为空，下载文件未落入"
    return True, f"下载文件 → {files[0]}"


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

ALL_CASES = ["screenshot", "scrape", "form", "upload", "download", "newtab", "web-page-sync", "custom"]


def main() -> None:
    parser = argparse.ArgumentParser(description="dp local smoke runner")
    parser.add_argument("--port", default="9222", help="浏览器远程调试端口（默认 9222）")
    parser.add_argument("--fixture-port", type=int, default=18080, help="本地 fixture HTTP 端口（默认 18080）")
    parser.add_argument("--case", default=None, choices=ALL_CASES, help="只运行指定 case")
    args = parser.parse_args()

    # 1. 环境检查
    ws_issue = _check_workspace()
    if ws_issue:
        print(f"[dp smoke] {ws_issue}", file=sys.stderr)
        sys.exit(2)

    if not _check_browser(args.port):
        print(f"[dp smoke] 无法连接到浏览器（端口 {args.port}）。", file=sys.stderr)
        print("[dp smoke] 请先运行 start-chrome-cdp.bat（或等效脚本）启动带调试端口的 Chrome。", file=sys.stderr)
        sys.exit(2)

    # 2. 清理将要运行的 case 的历史产物，防止脚本失败时旧产物误报 PASS
    import shutil
    cases_to_run = [args.case] if args.case else ALL_CASES
    for case in cases_to_run:
        case_dir = WORKSPACE / "projects" / SITE / "output" / case
        if case_dir.exists():
            shutil.rmtree(case_dir)

    # 3. 启动 fixture server
    base_url = f"http://127.0.0.1:{args.fixture_port}"
    server = _start_fixture_server(args.fixture_port)
    print(f"[dp smoke] fixture server @ {base_url}")
    time.sleep(0.3)  # 等 server 就绪

    # 4. 准备 upload 测试文件
    upload_tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    upload_tmp.write("dp smoke upload test\n")
    upload_tmp.close()
    upload_file = upload_tmp.name

    # 5. 运行 cases
    scripts = {
        "screenshot":   lambda: _script_screenshot(base_url),
        "scrape":       lambda: _script_scrape(base_url),
        "form":         lambda: _script_form(base_url),
        "upload":       lambda: _script_upload(base_url, upload_file),
        "download":     lambda: _script_download(base_url),
        "newtab":       lambda: _script_newtab(base_url),
        "web-page-sync": lambda: _script_web_page_sync(base_url),
        "custom":       lambda: _script_custom(base_url),
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
    }

    results: list[tuple[str, bool, str]] = []
    for case in cases_to_run:
        print(f"\n[dp smoke] ── {case} ──")
        script_ok = _run_script(scripts[case](), args.port)
        ok, detail = verifiers[case]()
        status = "PASS" if (script_ok and ok) else "FAIL"
        results.append((case, status == "PASS", detail if ok else f"脚本{'OK' if script_ok else '失败'}，contract：{detail}"))
        print(f"  {status}  {detail if ok else detail}")

    # 6. 清理
    server.shutdown()
    Path(upload_file).unlink(missing_ok=True)

    # 7. 汇总
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
