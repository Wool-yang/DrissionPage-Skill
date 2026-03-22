#!/usr/bin/env python3
"""列出 .dp/projects/ 下所有已保存的脚本。"""
from __future__ import annotations

import argparse
from pathlib import Path


def find_projects_dir(start: Path) -> Path | None:
    """从给定目录向上查找 .dp/projects。"""
    base = start.resolve()
    for candidate in (base, *base.parents):
        projects = candidate / ".dp" / "projects"
        if projects.exists():
            return projects
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", default=None, help="显式指定目标项目根目录")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = Path(args.root).expanduser() if args.root else Path.cwd()
    projects_dir = find_projects_dir(start)

    if not projects_dir:
        print("（暂无已保存的脚本）")
        return

    scripts = sorted(projects_dir.glob("*/scripts/*.py"))
    if not scripts:
        print("（暂无已保存的脚本）")
        return

    for f in scripts:
        site = f.parent.parent.name
        task = ""
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("task:"):
                    task = line.split("task:", 1)[1].strip()
                    break
        except Exception:
            pass
        suffix = f"  — {task}" if task else ""
        print(f"  {site}/{f.name}{suffix}")


if __name__ == "__main__":
    main()
