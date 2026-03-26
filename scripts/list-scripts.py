#!/usr/bin/env python3
"""列出 .dp/projects/ 下所有已保存的脚本，输出结构化 index 供 LLM 或人工查阅。"""
from __future__ import annotations

import argparse
import json
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
    """只从脚本头第一个 docstring 中提取字段，不扫描正文。"""
    fields: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
        m = re.search(r'(\'\'\'|""")(.*?)\1', text, re.DOTALL)
        if not m:
            return fields
        for line in m.group(2).splitlines():
            stripped = line.strip()
            for key in _FIELDS:
                if stripped.startswith(f"{key}:"):
                    val = stripped[len(key) + 1:].strip()
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
    parser.add_argument("--url", default=None, help="只列出 url 字段以指定前缀开头的脚本")
    parser.add_argument("--status", default=None, help="只列出 status 字段精确匹配的脚本（如 broken、ok）")
    parser.add_argument("--json", dest="json_output", action="store_true", help="以 JSON 数组格式输出（替代默认文本格式）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = Path(args.root).expanduser() if args.root else Path.cwd()
    projects_dir = find_projects_dir(start)

    if not projects_dir:
        print("[]" if args.json_output else "（暂无已保存的脚本）")
        return

    scripts = sorted(projects_dir.glob("*/scripts/*.py"))
    if not scripts:
        print("[]" if args.json_output else "（暂无已保存的脚本）")
        return

    shown = 0
    results_json: list[dict] = []

    for f in scripts:
        site = f.parent.parent.name

        # --site 过滤
        if args.site and site != args.site:
            continue

        fields = extract_fields(f)

        # --intent 过滤（子串匹配，方便人工查询）
        if args.intent and args.intent.lower() not in fields.get("intent", "").lower():
            continue

        # --url 过滤（前缀匹配，对应 SKILL.md 三级匹配第二优先级）
        if args.url and not fields.get("url", "").startswith(args.url):
            continue

        # --status 过滤（精确匹配）
        if args.status and fields.get("status", "") != args.status:
            continue

        # 输出：文件路径 + 各字段
        if args.json_output:
            results_json.append({
                "site": site,
                "file": f.name,
                "path": str(f.resolve()),
                "task": fields.get("task", ""),
                "intent": fields.get("intent", ""),
                "url": fields.get("url", ""),
                "tags": fields.get("tags", ""),
                "status": fields.get("status", ""),
                "last_run": fields.get("last_run", ""),
            })
        else:
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

    if args.json_output:
        print(json.dumps(results_json, ensure_ascii=False, indent=2))
    elif shown == 0:
        print("（没有匹配的脚本）")

if __name__ == "__main__":
    main()
