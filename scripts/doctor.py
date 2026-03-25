#!/usr/bin/env python3
"""
dp doctor —— 检测并初始化 .dp/ 工作空间。

运行方式：
  python <skill-root>/scripts/doctor.py
  python <skill-root>/scripts/doctor.py --check   # 只检测，不修复
  python <skill-root>/scripts/doctor.py --force   # 强制重新初始化

退出码：
  0  一切就绪
  1  检测到问题（--check 模式时）
  2  初始化失败
"""
from __future__ import annotations

import ast
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(".dp")
VENV = WORKSPACE / ".venv"
LIB = WORKSPACE / "lib"
STATE = WORKSPACE / "state.json"
SKILL_DIR = Path(__file__).parent.parent  # <skill-root>/
TEMPLATES = SKILL_DIR / "templates"

MIN_PYTHON = (3, 10)


# ── 状态文件 ──────────────────────────────────────────────────────────────────

def _parse_frontmatter() -> dict[str, str]:
    """提取 SKILL.md frontmatter block（--- 之间）中的 key: value 对，不扫描正文。"""
    try:
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        m = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
        if not m:
            return {}
        result: dict[str, str] = {}
        for line in m.group(1).splitlines():
            kv = re.match(r'^\s*([a-zA-Z0-9_-]+):\s*["\']?([^"\'\n]+?)["\']?\s*$', line)
            if kv:
                result[kv.group(1)] = kv.group(2)
        return result
    except Exception:
        return {}


def _read_bundle_version() -> str:
    """从 SKILL.md frontmatter 读取当前 bundle 版本。"""
    return _parse_frontmatter().get("bundle-version", "unknown")


def _read_runtime_lib_version() -> str:
    """从 SKILL.md frontmatter 读取 runtime-lib-version，缺失时回退到 bundle-version。"""
    fm = _parse_frontmatter()
    return fm.get("runtime-lib-version") or fm.get("bundle-version", "unknown")


def _read_state() -> dict:
    """读取 .dp/state.json，失败返回空字典。"""
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(bundle_version: str, runtime_lib_version: str) -> None:
    """写入 .dp/state.json，记录版本和最后初始化时间。"""
    from datetime import datetime, timezone
    STATE.write_text(
        json.dumps({
            "bundle_version": bundle_version,
            "runtime_lib_version": runtime_lib_version,
            "last_doctor_ok_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def has_uv() -> bool:
    """检测 uv 是否在 PATH 中可用。"""
    return shutil.which("uv") is not None


def acquire_uv() -> bool:
    """检测 uv 是否可用；不可用时打印提示，返回 False（不自动安装，避免污染宿主环境）。"""
    if has_uv():
        return True
    print(
        "[dp] 未检测到 uv，将使用传统 venv 方式。"
        "（推荐安装 uv 以获得更快的依赖解析：https://docs.astral.sh/uv/getting-started/installation/）",
        file=sys.stderr,
    )
    return False


def find_python() -> str:
    """找到满足最低版本要求的 Python 解释器（uv 不可用时的 fallback）。"""
    for candidate in ("python", "python3", "python3.12", "python3.11", "python3.10"):
        path = shutil.which(candidate)
        if not path:
            continue
        try:
            result = subprocess.run(
                [path, "-c", "import sys; print(sys.version_info[:2])"],
                capture_output=True, text=True, timeout=5,
            )
            ver = ast.literal_eval(result.stdout.strip())
            if ver >= MIN_PYTHON:
                return path
        except Exception:
            continue
    return ""


def venv_python() -> Path:
    """返回 venv 中的 Python 路径（跨平台）。"""
    win = VENV / "Scripts" / "python.exe"
    unix = VENV / "bin" / "python"
    return win if win.exists() else unix


def is_drissionpage_source(cwd: Path | None = None) -> bool:
    """
    判断指定目录（默认为 git root）是否是 DrissionPage 源码仓库。
    不依赖调用时的 CWD，用脚本自身路径向上推断项目根目录。
    """
    base = cwd or _find_project_root()
    return (base / "DrissionPage" / "__init__.py").exists()


def _find_project_root() -> Path:
    """从 doctor.py 所在位置向上查找 git root；找不到则返回 CWD。"""
    candidate = SKILL_DIR
    for _ in range(6):  # 最多向上 6 层
        if (candidate / ".git").exists():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return Path.cwd()


# ── 核心操作 ──────────────────────────────────────────────────────────────────

def create_venv(use_uv: bool) -> bool:
    """创建虚拟环境，返回是否成功。"""
    print("[dp] 创建虚拟环境...")
    ver_str = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"

    if use_uv:
        print(f"[dp] uv venv（Python {ver_str}+）")
        result = subprocess.run(
            ["uv", "venv", str(VENV), "--python", ver_str],
            timeout=60,
        )
    else:
        python_exe = find_python()
        if not python_exe:
            print(f"[dp] 错误：未找到 Python {ver_str}+ 解释器", file=sys.stderr)
            return False
        print(f"[dp] python -m venv（{python_exe}）")
        result = subprocess.run([python_exe, "-m", "venv", str(VENV)], timeout=60)

    if result.returncode != 0:
        print("[dp] 错误：创建虚拟环境失败", file=sys.stderr)
        return False
    return True


def install_drissionpage(use_uv: bool) -> bool:
    """安装 DrissionPage：源码仓库内可编辑安装，其余从 PyPI 安装。"""
    if is_drissionpage_source(_find_project_root()):
        print("[dp] 检测到 DrissionPage 源码，执行可编辑安装...")
        pkg_args = ["-e", "."]
    else:
        print("[dp] 从 PyPI 安装 DrissionPage...")
        pkg_args = ["DrissionPage"]

    if use_uv:
        # 传入 venv 目录，uv 自动识别并安装到该 venv
        cmd = ["uv", "pip", "install", "--python", str(VENV)] + pkg_args
    else:
        pip = VENV / "Scripts" / "pip.exe"
        if not pip.exists():
            pip = VENV / "bin" / "pip"
        cmd = [str(pip), "install"] + pkg_args

    result = subprocess.run(cmd, timeout=120)
    return result.returncode == 0


# ── 检测与初始化 ──────────────────────────────────────────────────────────────

def check() -> list[str]:
    """检测环境，返回问题列表（空列表代表一切正常）。"""
    issues: list[str] = []

    if not WORKSPACE.exists():
        issues.append(".dp/ 工作空间不存在")
        return issues

    py = venv_python()
    if not py.exists():
        issues.append(".dp/.venv/ 虚拟环境不存在或已损坏")
    else:
        try:
            result = subprocess.run(
                [str(py), "-c", "import DrissionPage"],
                capture_output=True, timeout=10,
            )
            if result.returncode != 0:
                issues.append("DrissionPage 未安装到 .dp/.venv/")
        except (OSError, PermissionError):
            issues.append(".dp/.venv/ Python 不可执行（权限问题或文件损坏）")
        except Exception as e:
            issues.append(f".dp/.venv/ 检测失败：{e}")

    for name in ("connect.py", "output.py", "utils.py"):
        if not (LIB / name).exists():
            issues.append(f".dp/lib/{name} 缺失")

    runtime_v = _read_runtime_lib_version()
    if not STATE.exists():
        issues.append(".dp/state.json 不存在（工作区需要重新初始化）")
    else:
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
            # 兼容旧 lib_version 字段
            state_v = state.get("runtime_lib_version") or state.get("lib_version")
            if state_v is None:
                issues.append(".dp/state.json 缺少版本信息，需要重新初始化")
            elif state_v != runtime_v:
                issues.append(
                    f".dp/lib runtime 版本 {state_v!r} 与当前 {runtime_v!r} 不一致，需要升级"
                )
        except Exception:
            issues.append(".dp/state.json 损坏，无法解析，需要重新初始化")

    return issues


def init(force: bool = False) -> bool:
    """初始化或修复工作空间，返回是否成功。"""
    use_uv = acquire_uv()

    # 1. 目录结构
    for d in [WORKSPACE / "projects", WORKSPACE / "tmp" / "_out", LIB]:
        d.mkdir(parents=True, exist_ok=True)

    # .dp/ 根目录的 .gitignore：忽略 venv 和临时区
    root_gitignore = WORKSPACE / ".gitignore"
    if not root_gitignore.exists():
        root_gitignore.write_text(".venv/\ntmp/\n")

    gitignore = WORKSPACE / "tmp" / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")

    # 2. 虚拟环境
    if not venv_python().exists() or force:
        if not create_venv(use_uv):
            return False

    # 3. DrissionPage 安装
    try:
        already_installed = subprocess.run(
            [str(venv_python()), "-c", "import DrissionPage"],
            capture_output=True, timeout=10,
        ).returncode == 0
    except (OSError, PermissionError) as e:
        print(f"[dp] 错误：.dp/.venv/ Python 不可执行：{e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[dp] 错误：检测 DrissionPage 失败：{e}", file=sys.stderr)
        return False

    if not already_installed or force:
        if not install_drissionpage(use_uv):
            print("[dp] 错误：安装 DrissionPage 失败", file=sys.stderr)
            return False

    # 4. lib 模板文件（始终覆盖，确保与当前 bundle 版本一致）
    (LIB / "__init__.py").touch(exist_ok=True)
    for name in ("connect.py", "output.py", "utils.py"):
        src, dst = TEMPLATES / name, LIB / name
        if src.exists():
            shutil.copy2(src, dst)
            print(f"[dp] 同步 {dst}")

    # 5. 工作空间文档（首次）
    _write_workspace_docs()

    # 6. 写入/更新持久状态
    bundle_v = _read_bundle_version()
    runtime_v = _read_runtime_lib_version()
    _write_state(bundle_v, runtime_v)

    print("[dp] ✓ 工作空间就绪：.dp/")
    print(f"[dp]   Python: {venv_python()}")
    print(f"[dp]   bundle: {bundle_v} / runtime-lib: {runtime_v}")
    return True


def _write_workspace_docs() -> None:
    readme = WORKSPACE / "README.md"
    if not readme.exists():
        readme.write_text(
            "# .dp/ — DrissionPage 工作空间\n\n"
            "| 路径 | 用途 |\n|---|---|\n"
            "| `.venv/` | Python 虚拟环境（uv 或标准 venv） |\n"
            "| `lib/` | 共用库（connect / output / utils） |\n"
            "| `projects/<site>/` | 按网站存放脚本和输出 |\n"
            "| `tmp/` | 临时区（gitignore: *） |\n\n"
            "输出结构：`projects/<site>/output/<script-name>/YYYY-MM-DD_HHMMSS_mmm/`\n"
            "每个目录对应一次执行，目录内文件用语义名称（data.json、screenshot.png 等）。\n",
            encoding="utf-8",
        )


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="dp workspace doctor")
    parser.add_argument("--check", action="store_true", help="只检测，不修复")
    parser.add_argument("--force", action="store_true", help="强制重新初始化")
    args = parser.parse_args()

    if args.check:
        issues = check()
        if issues:
            print("[dp] 检测到以下问题：")
            for issue in issues:
                print(f"  ✗ {issue}")
            sys.exit(1)
        print("[dp] ✓ 环境正常")
        sys.exit(0)

    issues = check()
    if issues and not args.force:
        print("[dp] 检测到问题，开始修复...")
    elif not issues and not args.force:
        print("[dp] ✓ 环境已就绪，无需初始化")
        sys.exit(0)

    sys.exit(0 if init(force=args.force) else 2)


if __name__ == "__main__":
    main()
