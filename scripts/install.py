#!/usr/bin/env python3
"""将 dp skill bundle 安装或更新到目标目录。

同步规则：
- source 有的文件 → 覆盖写入 target（始终更新 upstream 内容）
- target 独有的文件 → 保留不动（保护客户端自定义文件）
- source 删除的文件 → target 中保留（不自动删除，需客户端手动清理）

用法：
  python scripts/install.py --target <target_dir>

  target_dir：skill 的安装目标目录。
  若目标目录已存在，逐项覆盖更新；若不存在，完整创建。

退出码：0 成功，1 失败。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent

_EXCLUDE_NAMES = {".git", "__pycache__", ".dp", ".venv"}
_EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _sync_dir(src: Path, dst: Path) -> int:
    """递归同步 src 到 dst。

    只写入 src 中存在的文件，不删除 dst 中独有的文件（保护客户端自定义）。
    返回更新的文件数。
    """
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in src.iterdir():
        if item.name in _EXCLUDE_NAMES or item.suffix in _EXCLUDE_SUFFIXES:
            continue
        dest = dst / item.name
        if item.is_dir():
            count += _sync_dir(item, dest)
        else:
            shutil.copy2(item, dest)
            count += 1
    return count


def install(target: Path) -> None:
    """将 skill bundle 同步到 target 目录。"""
    count = _sync_dir(SKILL_DIR, target)
    print(f"[dp] 已同步 {count} 个文件到 {target.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="安装或更新 dp skill bundle 到目标目录",
        add_help=True,
    )
    parser.add_argument(
        "--target",
        required=True,
        help="目标安装目录",
    )
    args = parser.parse_args()
    target = Path(args.target).expanduser()
    try:
        install(target)
    except Exception as e:
        print(f"[dp] 安装失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
