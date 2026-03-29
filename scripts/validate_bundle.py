#!/usr/bin/env python3
"""对 dp source bundle 做无第三方依赖的快速自查。"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True

SKILL_ROOT = Path(__file__).resolve().parent.parent
ALLOWED_FRONTMATTER_KEYS = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "compatibility",
}
REQUIRED_FILES = [
    "SKILL.md",
    "scripts/doctor.py",
    "scripts/install.py",
    "scripts/list-scripts.py",
    "scripts/smoke.py",
    "scripts/validate_bundle.py",
    "scripts/test_helpers.py",
    "templates/connect.py",
    "templates/output.py",
    "templates/utils.py",
    "templates/_dp_compat.py",
    "references/interface.md",
    "references/mode-selection.md",
    "references/workflows.md",
    "references/site-readme.md",
    "evals/evals.json",
    "evals/smoke-checklist.md",
    "evals/fixtures/basic.html",
    "evals/fixtures/upload.html",
    "evals/fixtures/download.html",
    "evals/fixtures/newtab.html",
    "evals/fixtures/login.html",
]
FORBIDDEN_TEXT_PATTERNS = [
    "CLAUDE_SKILL_DIR",
    "$ARGUMENTS",
    "!`",
    ".claude/skills/dp",
    ".agents/skills/dp",
    "canonical source bundle",
    "canonical-source",
    "运行 /dp",
    "openai.yaml",
]
FORBIDDEN_PATH_PARTS = {"__pycache__"}
FORBIDDEN_FILENAMES = {"list-scripts.sh"}


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def parse_frontmatter(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        fail("SKILL.md 缺少合法 YAML frontmatter")

    frontmatter = match.group(1)
    keys = []
    for line in frontmatter.splitlines():
        if not line or line.startswith((" ", "\t")):
            continue
        item = re.match(r"^([A-Za-z0-9_-]+):", line)
        if item:
            keys.append(item.group(1))

    unexpected = sorted(set(keys) - ALLOWED_FRONTMATTER_KEYS)
    if unexpected:
        fail(f"SKILL.md frontmatter 出现未允许字段：{', '.join(unexpected)}")

    for required in ("name", "description", "compatibility", "metadata"):
        if required not in keys:
            fail(f"SKILL.md frontmatter 缺少必需字段：{required}")

    name_match = re.search(r"^name:\s*([^\n]+)$", frontmatter, re.MULTILINE)
    if not name_match:
        fail("无法解析 frontmatter 中的 name")
    name = name_match.group(1).strip().strip("'\"")
    if not re.fullmatch(r"[a-z0-9-]+", name):
        fail("frontmatter.name 必须是 kebab-case")

    if "bundle-version:" not in frontmatter:
        fail("metadata 中缺少 bundle-version")

    if "runtime-lib-version:" not in frontmatter:
        fail("metadata 中缺少 runtime-lib-version")

    if "bundle-type:" in frontmatter:
        fail("SKILL.md frontmatter 不应包含已废弃的 bundle-type 字段")

    return {"name": name}


def validate_required_files(root: Path) -> None:
    for rel in REQUIRED_FILES:
        path = root / rel
        if not path.exists():
            fail(f"缺少必需文件：{rel}")


_FORBIDDEN_ROOT_DIRS = {"projects", "output", ".dp"}


def validate_source_root_layout(root: Path) -> None:
    """检测 source root 下不允许出现的运行态目录。"""
    for name in _FORBIDDEN_ROOT_DIRS:
        if (root / name).exists():
            fail(f"source root 出现不应存在的运行态目录：{name}/，请删除后再发布")


def cleanup_bytecode(root: Path) -> None:
    for path in root.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)
    for path in root.rglob("*.pyc"):
        if path.is_file():
            path.unlink()


def validate_forbidden_paths(root: Path) -> None:
    for path in root.rglob("*"):
        if any(part in FORBIDDEN_PATH_PARTS for part in path.parts):
            fail(f"存在不应分发的缓存目录：{path}")
        if path.name in FORBIDDEN_FILENAMES:
            fail(f"存在废弃文件：{path}")
        if path.suffix == ".pyc":
            fail(f"存在不应分发的字节码文件：{path}")


def validate_forbidden_text(root: Path) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path == root / "scripts" / "validate_bundle.py":
            continue
        if path == root / "scripts" / "test_helpers.py":
            continue
        if path.suffix not in {".md", ".py", ".json", ".gitignore"}:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_TEXT_PATTERNS:
            if pattern in text:
                fail(f"文件 {path.relative_to(root)} 含有不应出现的耦合文本：{pattern}")


def validate_json(root: Path) -> None:
    evals = root / "evals" / "evals.json"
    obj = json.loads(evals.read_text(encoding="utf-8"))
    if obj.get("skill_name") != "dp":
        fail("evals/evals.json 的 skill_name 必须为 dp")
    if not isinstance(obj.get("evals"), list) or not obj["evals"]:
        fail("evals/evals.json 必须至少包含一个 eval")


def validate_python(root: Path) -> None:
    for rel in (
        "scripts/doctor.py",
        "scripts/install.py",
        "scripts/list-scripts.py",
        "scripts/smoke.py",
        "scripts/validate_bundle.py",
        "templates/connect.py",
        "templates/output.py",
        "templates/utils.py",
        "templates/_dp_compat.py",
    ):
        path = root / rel
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")


def validate_rule_markers(root: Path) -> None:
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    if "站点 README 规则" not in skill:
        fail("SKILL.md 缺少站点 README 规则")
    if "默认远程调试端口是 `9222`" not in skill:
        fail("SKILL.md 缺少默认端口规则")
    if "scripts/list-scripts.py --root <project-root>" not in skill:
        fail("SKILL.md 缺少 list-scripts 显式根路径说明")
    if "runtime_lib_version" not in skill:
        fail("SKILL.md 缺少 runtime_lib_version preflight 描述")
    if "bundle_version" not in skill:
        fail("SKILL.md 缺少 bundle_version preflight 描述")
    if "当前会话工作区 cwd 作为工作区根" not in skill:
        fail("SKILL.md 缺少工作区根 contract 说明")


def validate_output_contract(root: Path) -> None:
    """检查关键文件不含旧的 output/YYYY-MM-DD/ 路径格式。

    同时拦截两类写法：
    - 真实日期：output/2026-03-20/      （正则 [0-9]{4}-[0-9]{2}-[0-9]{2}）
    - 占位符  ：output/YYYY-MM-DD/      （字面量模板写法，同样是旧 contract）
    """
    import re as _re
    # 旧格式：output 后直接跟 YYYY-MM-DD 形式（真实日期或字面占位符），中间无 script-name 层
    old_pattern = _re.compile(r'output/(\d{4}-\d{2}-\d{2}|YYYY-MM-DD)/')
    for rel in (
        "evals/evals.json",
        "evals/smoke-checklist.md",
        "SKILL.md",
        "references/workflows.md",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        if old_pattern.search(text):
            fail(f"{rel} 含有旧的输出路径格式 output/YYYY-MM-DD/，应改为 output/<script-name>/YYYY-MM-DD_HHMMSS_mmm/")


def validate_cross_file_consistency(root: Path) -> None:
    """跨文件一致性校验：output.py 函数签名 / workflows.md 字段与导入。"""
    output_py = (root / "templates" / "output.py").read_text(encoding="utf-8")
    if "def site_run_dir" not in output_py:
        fail("templates/output.py 缺少 site_run_dir() 函数")
    if "def site_output" in output_py:
        fail("templates/output.py 不应再存在旧的 site_output() 函数")

    utils_py = (root / "templates" / "utils.py").read_text(encoding="utf-8")
    if "def browser_upload_path" not in utils_py:
        fail("templates/utils.py 缺少 browser_upload_path() 函数")
    if "def upload_file" not in utils_py:
        fail("templates/utils.py 缺少 upload_file() 函数")
    if "def browser_download_path" not in utils_py:
        fail("templates/utils.py 缺少 browser_download_path() 函数")
    if "def download_file" not in utils_py:
        fail("templates/utils.py 缺少 download_file() 函数")

    workflows = (root / "references" / "workflows.md").read_text(encoding="utf-8")
    if "site_run_dir" not in workflows:
        fail("references/workflows.md 未引用 site_run_dir")
    if "upload_file" not in workflows:
        fail("references/workflows.md 未使用 upload_file()")
    if "download_file" not in workflows:
        fail("references/workflows.md 未使用 download_file()")
    for field in ("site:", "task:", "created:", "updated:", "intent:", "url:", "tags:", "last_run:", "status:"):
        if field not in workflows:
            fail(f"references/workflows.md 通用脚本头缺少字段: {field}")
    if "mark_script_status" not in workflows:
        fail("references/workflows.md 未使用 mark_script_status()")

    # 下载 contract 校验：download_file() 已内置等待，禁止在其后再调下载管理器等待方法。
    # 校验范围：workflow 模板（用户参照物）+ smoke 脚本（bundled 示例）。
    _download_wait_ban = "page.browser.wait.downloads_done"
    for _rel in ("references/workflows.md", "scripts/smoke.py"):
        if _download_wait_ban in (root / _rel).read_text(encoding="utf-8"):
            fail(
                f"{_rel} 不应包含 {_download_wait_ban}()——"
                "download_file() 已内置等待逻辑，raw-CDP 分支调用会立即报错"
            )


def run_unit_tests(root: Path) -> None:
    import subprocess
    result = subprocess.run(
        [sys.executable, "-B", str(root / "scripts" / "test_helpers.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        fail(f"单元测试失败：\n{result.stdout}{result.stderr}")


def main() -> None:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else SKILL_ROOT
    if not root.exists():
        fail(f"skill root 不存在：{root}")

    print(f"[INFO] quick-check {root}")
    cleanup_bytecode(root)
    validate_required_files(root)
    validate_source_root_layout(root)
    parse_frontmatter(root / "SKILL.md")
    validate_forbidden_paths(root)
    validate_forbidden_text(root)
    validate_json(root)
    validate_python(root)
    validate_rule_markers(root)
    validate_output_contract(root)
    validate_cross_file_consistency(root)
    run_unit_tests(root)
    cleanup_bytecode(root)  # 清除测试运行可能产生的字节码
    print("[OK] bundle looks clean")


if __name__ == "__main__":
    main()
