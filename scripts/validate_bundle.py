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
    "scripts/list-scripts.py",
    "scripts/validate_bundle.py",
    "templates/connect.py",
    "templates/output.py",
    "templates/utils.py",
    "references/interface.md",
    "references/mode-selection.md",
    "references/workflows.md",
    "references/site-readme.md",
    "evals/evals.json",
    "evals/smoke-checklist.md",
]
FORBIDDEN_TEXT_PATTERNS = [
    "CLAUDE_SKILL_DIR",
    "$ARGUMENTS",
    "!`",
    ".claude/skills/dp",
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

    return {"name": name}


def validate_required_files(root: Path) -> None:
    for rel in REQUIRED_FILES:
        path = root / rel
        if not path.exists():
            fail(f"缺少必需文件：{rel}")


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
        "scripts/list-scripts.py",
        "scripts/validate_bundle.py",
        "templates/connect.py",
        "templates/output.py",
        "templates/utils.py",
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
    parse_frontmatter(root / "SKILL.md")
    validate_forbidden_paths(root)
    validate_forbidden_text(root)
    validate_json(root)
    validate_python(root)
    validate_rule_markers(root)
    run_unit_tests(root)
    print("[OK] bundle looks clean")


if __name__ == "__main__":
    main()
