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
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

WORKSPACE = Path(".dp")
VENV = WORKSPACE / ".venv"
LIB = WORKSPACE / "lib"
CONFIG = WORKSPACE / "config.json"
STATE = WORKSPACE / "state.json"
SKILL_DIR = Path(__file__).parent.parent  # <skill-root>/
TEMPLATES = SKILL_DIR / "templates"
PROVIDER_TEMPLATES = TEMPLATES / "providers"
DEFAULT_FALLBACK_PROVIDER = "cdp-port"

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


def _state_runtime_version(state: dict[str, Any]) -> str | None:
    """从 state.json 兼容读取 runtime 版本字段。"""
    if not isinstance(state, dict):
        return None
    return state.get("runtime_lib_version") or state.get("lib_version")


def _read_config() -> dict:
    """读取 .dp/config.json，失败返回空字典。"""
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def normalize_provider_name(raw: str) -> str:
    """把 provider 名规范化为 kebab-case；非法值直接报错。"""
    key = (raw or "").strip().lower()
    if not key:
        raise ValueError("default_provider 不能为空。")
    if not re.fullmatch(r"[a-z0-9-]+", key):
        raise ValueError(f"default_provider 不合法：{raw!r}")
    return key


def _write_default_config() -> None:
    """初始化工作区默认配置；修复未初始化值，拒绝显式非法 provider。"""
    config = _read_config()
    if not isinstance(config, dict):
        config = {}
    raw = config.get("default_provider")
    if not isinstance(raw, str) or not raw.strip():
        config["default_provider"] = DEFAULT_FALLBACK_PROVIDER
    else:
        config["default_provider"] = normalize_provider_name(raw)
    CONFIG.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
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


def resolve_venv_python(venv: Path) -> Path:
    """按宿主 OS 返回指定 venv 的优先 Python 路径。"""
    if os.name == "nt":
        preferred = venv / "Scripts" / "python.exe"
        fallback = venv / "bin" / "python"
    else:
        preferred = venv / "bin" / "python"
        fallback = venv / "Scripts" / "python.exe"
    return preferred if preferred.exists() else fallback


def venv_python() -> Path:
    """按宿主 OS 优先返回 venv Python 路径。

    Windows 宿主优先 Scripts/python.exe；非 Windows（Linux/WSL/macOS）优先 bin/python。
    这样在 WSL 接管 Windows venv 时不会选到不可执行的 .exe。
    """
    return resolve_venv_python(VENV)


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


def _required_source_assets() -> list[Path]:
    """返回 doctor 初始化工作区前必须存在的 source bundle 资产。"""
    return [
        TEMPLATES / "connect.py",
        TEMPLATES / "download_correlation.py",
        TEMPLATES / "output.py",
        TEMPLATES / "utils.py",
        TEMPLATES / "_dp_compat.py",
        PROVIDER_TEMPLATES / "cdp-port.py",
    ]


def _workspace_paths(workspace: Path) -> dict[str, Path]:
    """按工作区根生成 doctor 会用到的关键路径。"""
    return {
        "workspace": workspace,
        "venv": workspace / ".venv",
        "lib": workspace / "lib",
        "config": workspace / "config.json",
        "state": workspace / "state.json",
        "providers": workspace / "providers",
    }


def _provider_file_candidates(name: str, providers_dir: Path) -> tuple[Path, ...]:
    """返回与 runtime loader 一致的 provider 文件候选路径。"""
    snake = name.replace("-", "_")
    candidates = [providers_dir / f"{name}.py"]
    if snake != name:
        candidates.append(providers_dir / f"{snake}.py")
    return tuple(candidates)


def _selected_provider_issue(name: str, providers_dir: Path) -> str | None:
    """校验当前选中的默认 provider 是否存在实现文件。"""
    if name == DEFAULT_FALLBACK_PROVIDER:
        return None
    candidates = _provider_file_candidates(name, providers_dir)
    if any(path.is_file() for path in candidates):
        return None
    searched = " / ".join(str(path) for path in candidates)
    return (
        f".dp/config.json default_provider={name!r} 对应的 provider 文件不存在"
        f"（已检查：{searched}），需用户或客户端提供实现或修正配置"
    )


def _validate_default_provider(raw: Any) -> tuple[str | None, str | None]:
    """校验并规范化 default_provider；返回 (provider, issue)。"""
    if raw is None:
        return None, ".dp/config.json 缺少 default_provider"
    if not isinstance(raw, str):
        return None, ".dp/config.json 缺少 default_provider"
    if not raw.strip():
        return None, ".dp/config.json 缺少 default_provider"
    try:
        return normalize_provider_name(raw), None
    except ValueError:
        return None, f".dp/config.json default_provider 不合法：{raw!r}"


# ── 核心操作 ──────────────────────────────────────────────────────────────────

def create_venv(use_uv: bool) -> bool:
    """创建虚拟环境，返回是否成功。"""
    print("[dp] 创建虚拟环境...")
    ver_str = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"

    # 若 venv 目录已存在（损坏或不可用），尝试删除再重建
    if VENV.exists():
        try:
            shutil.rmtree(VENV)
        except Exception:
            # Windows 下 junction/symlink 可能需要系统命令删除
            try:
                subprocess.run(
                    ["cmd", "/c", "rmdir", "/s", "/q", str(VENV)],
                    timeout=30, capture_output=True,
                )
            except Exception:
                pass  # 尽力而为；后续 uv/venv 命令失败会给出错误

    try:
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
    except (OSError, PermissionError) as e:
        print(f"[dp] 错误：创建虚拟环境时工具不可执行：{e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[dp] 错误：创建虚拟环境失败：{e}", file=sys.stderr)
        return False

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
        # 已验证版本范围：>=4.1.1,<4.2（本地实测 4.1.1.2）
        # 本 skill 依赖 DrissionPage 私有 API（_browser, _download_path, _run_cdp 等）。
        # 版本范围收紧是为了防止上游小版本重构时私有 API 静默失效。
        # 若需升级，请先检查 templates/_dp_compat.py 中各函数的注释。
        print("[dp] 从 PyPI 安装 DrissionPage（已验证范围 >=4.1.1,<4.2）...")
        pkg_args = ["DrissionPage>=4.1.1,<4.2"]

    if use_uv:
        cmd = ["uv", "pip", "install", "--python", str(VENV)] + pkg_args
    else:
        pip = VENV / "Scripts" / "pip.exe"
        if not pip.exists():
            pip = VENV / "bin" / "pip"
        cmd = [str(pip), "install"] + pkg_args

    try:
        result = subprocess.run(cmd, timeout=120)
        return result.returncode == 0
    except (OSError, PermissionError) as e:
        print(f"[dp] 错误：安装工具不可执行：{e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[dp] 错误：安装 DrissionPage 失败：{e}", file=sys.stderr)
        return False


# ── 检测与初始化 ──────────────────────────────────────────────────────────────

def evaluate_workspace(workspace: Path | None = None) -> dict[str, Any]:
    """结构化检测工作区，供 doctor/smoke 复用同一套 readiness contract。"""
    paths = _workspace_paths(workspace or WORKSPACE)
    issues: list[str] = []
    default_provider: str | None = None
    state_runtime_v: str | None = None
    state_bundle_v: str | None = None
    runtime_v = _read_runtime_lib_version()
    bundle_v = _read_bundle_version()

    if not paths["workspace"].exists():
        issues.append(".dp/ 工作空间不存在")
        return {
            "issues": issues,
            "default_provider": default_provider,
            "runtime_lib_version": runtime_v,
            "bundle_version": bundle_v,
            "state_runtime_lib_version": state_runtime_v,
            "state_bundle_version": state_bundle_v,
        }

    py = resolve_venv_python(paths["venv"])
    try:
        py_exists = py.exists()
    except OSError:
        py_exists = False  # 文件存在但不可访问（如 Windows 下不可读的 symlink）
    if not py_exists:
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

    for name in ("connect.py", "download_correlation.py", "output.py", "utils.py", "_dp_compat.py"):
        if not (paths["lib"] / name).exists():
            issues.append(f".dp/lib/{name} 缺失")

    if not (paths["providers"] / "cdp-port.py").exists():
        issues.append(".dp/providers/cdp-port.py 缺失")

    if not paths["config"].exists():
        issues.append(".dp/config.json 不存在（工作区默认 provider 未初始化）")
    else:
        try:
            config = json.loads(paths["config"].read_text(encoding="utf-8"))
        except Exception:
            config = None
            issues.append(".dp/config.json 损坏或格式错误，需要重新初始化")
        if config is None:
            pass
        elif not isinstance(config, dict):
            issues.append(".dp/config.json 损坏或格式错误，需要重新初始化")
        else:
            default_provider, config_issue = _validate_default_provider(config.get("default_provider"))
            if config_issue:
                issues.append(config_issue)
            elif default_provider:
                provider_issue = _selected_provider_issue(default_provider, paths["providers"])
                if provider_issue:
                    issues.append(provider_issue)

    if not paths["state"].exists():
        issues.append(".dp/state.json 不存在（工作区需要重新初始化）")
    else:
        try:
            state = json.loads(paths["state"].read_text(encoding="utf-8"))
            # 兼容旧 lib_version 字段
            state_runtime_v = state.get("runtime_lib_version") or state.get("lib_version")
            if state_runtime_v is None:
                issues.append(".dp/state.json 缺少版本信息，需要重新初始化")
            elif state_runtime_v != runtime_v:
                issues.append(
                    f".dp/lib runtime 版本 {state_runtime_v!r} 与当前 {runtime_v!r} 不一致，需要升级"
                )
            # bundle_version 差异：触发工作区文档与状态刷新（init 不重建 venv，影响极小）
            state_bundle_v = state.get("bundle_version", "")
            if bundle_v not in ("", "unknown") and state_bundle_v != bundle_v:
                issues.append(
                    f".dp bundle 版本 {state_bundle_v!r} 与当前 {bundle_v!r} 不一致，"
                    "工作区文档与状态需要刷新"
                )
        except Exception:
            issues.append(".dp/state.json 损坏，无法解析，需要重新初始化")

    return {
        "issues": issues,
        "default_provider": default_provider,
        "runtime_lib_version": runtime_v,
        "bundle_version": bundle_v,
        "state_runtime_lib_version": state_runtime_v,
        "state_bundle_version": state_bundle_v,
    }


def check() -> list[str]:
    """检测环境，返回问题列表（空列表代表一切正常）。"""
    return list(evaluate_workspace()["issues"])


def init(force: bool = False) -> bool:
    """初始化或修复工作空间，返回是否成功。"""
    use_uv = acquire_uv()

    missing_assets = [path for path in _required_source_assets() if not path.exists()]
    if missing_assets:
        for path in missing_assets:
            print(f"[dp] 错误：缺少 source bundle 资产：{path}", file=sys.stderr)
        return False

    # 1. 目录结构
    for d in [WORKSPACE / "projects", WORKSPACE / "tmp" / "_out", LIB, WORKSPACE / "providers"]:
        d.mkdir(parents=True, exist_ok=True)

    # .dp/ 根目录的 .gitignore：忽略 venv 和临时区
    root_gitignore = WORKSPACE / ".gitignore"
    if not root_gitignore.exists():
        root_gitignore.write_text(".venv/\ntmp/\n")

    gitignore = WORKSPACE / "tmp" / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")

    runtime_v = _read_runtime_lib_version()
    bundle_v = _read_bundle_version()
    state = _read_state()
    state_runtime_v = _state_runtime_version(state)
    state_bundle_v = state.get("bundle_version", "") if isinstance(state, dict) else ""
    providers_dir = WORKSPACE / "providers"
    runtime_asset_missing = any(
        not (LIB / name).exists()
        for name in ("connect.py", "download_correlation.py", "output.py", "utils.py", "_dp_compat.py")
    ) or not (providers_dir / "cdp-port.py").exists()

    try:
        venv_ok = venv_python().exists()
    except OSError:
        venv_ok = False  # 文件存在但不可访问（如 Windows 下不可读的 symlink）

    drissionpage_ready = False
    if venv_ok:
        try:
            drissionpage_ready = subprocess.run(
                [str(venv_python()), "-c", "import DrissionPage"],
                capture_output=True,
                timeout=10,
            ).returncode == 0
        except Exception:
            drissionpage_ready = False

    bundle_only_refresh = (
        not force
        and venv_ok
        and drissionpage_ready
        and not runtime_asset_missing
        and state_runtime_v == runtime_v
        and bundle_v not in ("", "unknown")
        and state_bundle_v != bundle_v
    )

    def _finalize_workspace() -> bool:
        # 工作空间文档每次 init 成功都重写，确保不会停留在旧 contract
        _write_workspace_docs()

        # 默认配置（保留用户修改）
        try:
            _write_default_config()
        except ValueError as e:
            print(f"[dp] 错误：{e}", file=sys.stderr)
            return False

        config = _read_config()
        try:
            selected_provider = normalize_provider_name(str(config.get("default_provider", "")))
        except ValueError as e:
            print(f"[dp] 错误：{e}", file=sys.stderr)
            return False
        provider_issue = _selected_provider_issue(selected_provider, providers_dir)
        if provider_issue:
            print(f"[dp] 错误：{provider_issue}", file=sys.stderr)
            return False

        _write_state(bundle_v, runtime_v)
        print("[dp] ✓ 工作空间就绪：.dp/")
        print(f"[dp]   Python: {venv_python()}")
        print(f"[dp]   bundle: {bundle_v} / runtime-lib: {runtime_v}")
        return True

    if bundle_only_refresh:
        return _finalize_workspace()

    # 2. 虚拟环境
    if not venv_ok or force:
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
    for name in ("connect.py", "download_correlation.py", "output.py", "utils.py", "_dp_compat.py"):
        src, dst = TEMPLATES / name, LIB / name
        shutil.copy2(src, dst)
        print(f"[dp] 同步 {dst}")

    # 4b. runtime-managed provider 模板
    (providers_dir / "__init__.py").touch(exist_ok=True)
    managed_provider = PROVIDER_TEMPLATES / "cdp-port.py"
    dst = providers_dir / "cdp-port.py"
    shutil.copy2(managed_provider, dst)
    print(f"[dp] 同步 {dst}")

    return _finalize_workspace()


def _write_workspace_docs() -> None:
    readme = WORKSPACE / "README.md"
    # 每次 init 成功都重写，确保工作区文档不停留在旧 contract
    readme.write_text(
        "<!-- dp:managed — 本文件由 dp doctor 自动管理，每次 init 后覆盖重写。"
        "如需保存站点备注，请使用 .dp/projects/<site>/README.md -->\n\n"
        "# .dp/ — DrissionPage 工作空间\n\n"
        "| 路径 | 用途 |\n|---|---|\n"
        "| `.venv/` | Python 虚拟环境（uv 或标准 venv） |\n"
        "| `lib/` | 共用库（connect / download_correlation / output / utils） |\n"
        "| `providers/` | 工作区 browser providers（含 runtime-managed `cdp-port.py`） |\n"
        "| `projects/<site>/` | 按网站存放脚本和输出 |\n"
        "| `tmp/` | 临时区（gitignore: *） |\n\n"
        "输出结构（run-dir contract）：\n"
        "`projects/<site>/output/<script-name>/YYYY-MM-DD_HHMMSS_mmm/`\n"
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
