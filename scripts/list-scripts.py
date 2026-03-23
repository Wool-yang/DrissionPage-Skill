#!/usr/bin/env python3
"""列出 .dp/projects/ 下所有已保存的脚本，输出结构化 index 供 LLM 或人工查阅。"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

# 从脚本 docstring 中提取的字段列表（按顺序）
_FIELDS = ("task", "intent", "url", "tags", "status", "last_run")


def find_projects_dir(start: Path) -> Path | None:
    """从给定目录向上查找 .dp/projects。"""
    base = start.resolve()
    for candidate in (base, *base.parents):
        projects = candidate / ".dp" / "projects"
        if projects.exists():
            return projects
    return None


def extract_fields(path: Path) -> dict[str, str]:
    """从脚本文件头的 docstring 中提取字段，返回字典。"""
    fields: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            for key in _FIELDS:
                prefix = f"{key}:"
                if stripped.startswith(prefix):
                    val = stripped[len(prefix):].strip()
                    # 只有 # 前有空白时才视为行内注释，避免截断 URL 中的 # (如 /#/page)
                    val = re.sub(r'\s+#.*$', '', val).strip()
                    if val:
                        fields[key] = val
                    break
    except Exception:
        pass
    return fields


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="列出 .dp/projects/ 下所有已保存的脚本",
        add_help=True,
    )
    parser.add_argument("--root", default=None, help="显式指定目标项目根目录")
    parser.add_argument("--site", default=None, help="只列出指定站点的脚本")
    parser.add_argument("--intent", default=None, help="只列出包含指定 intent 关键词的脚本")
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

    shown = 0
    for f in scripts:
        site = f.parent.parent.name

        # --site 过滤
        if args.site and site != args.site:
            continue

        fields = extract_fields(f)

        # --intent 过滤（子串匹配，方便人工查询）
        if args.intent and args.intent.lower() not in fields.get("intent", "").lower():
            continue

        # 输出：文件路径 + 各字段
        print(f"{site}/scripts/{f.name}")
        for key in _FIELDS:
            val = fields.get(key, "")
            if not val:
                continue
            # status 和 last_run 拼在一行
            if key == "last_run":
                continue
            if key == "status":
                last_run = fields.get("last_run", "")
                suffix = f"   last_run: {last_run}" if last_run else ""
                print(f"  {key + ':':<10} {val}{suffix}")
            else:
                print(f"  {key + ':':<10} {val}")
        print()
        shown += 1

    if shown == 0:
        print("（没有匹配的脚本）")


if __name__ == "__main__":
    main()
