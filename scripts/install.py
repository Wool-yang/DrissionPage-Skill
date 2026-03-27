#!/usr/bin/env python3
"""将 dp skill bundle 安装或更新到目标目录。

同步规则：
- source 有的文件 → 覆盖写入 target（始终更新 upstream 内容）
- target 独有且不在 manifest 中的文件 → 保留（用户自定义文件）
- manifest 记录但 source 已删除的文件 → 自动清理（upstream 旧文件）
- 文件清理后变为空的 upstream 目录 → 自动清理（rmdir 只删空目录）

manifest 文件（target/.dp-install-manifest）记录上次安装的文件列表，用于
精确区分"upstream 旧文件"和"用户自定义文件"。

首次运行时若目标目录无 .dp-install-manifest（旧版安装或手动安装），
本次不做旧文件清理，但会写出 manifest 供后续升级使用。

用法：
  python scripts/install.py --target <target_dir>

退出码：0 成功，1 失败。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
MANIFEST_FILE = ".dp-install-manifest"

_EXCLUDE_NAMES = {".git", ".github", "__pycache__", ".dp", ".venv", ".gitignore"}
_EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
# 仅排除 source root 顶层的运行态目录；不传入递归调用，允许合法子目录使用同名
_EXCLUDE_ROOT_NAMES: frozenset[str] = frozenset({"projects", "output"})


def _read_manifest(target: Path) -> set[str]:
    """读取已安装文件的相对路径集合。文件不存在或解析失败时返回空集合。"""
    try:
        data = json.loads((target / MANIFEST_FILE).read_text(encoding="utf-8"))
        return set(data.get("files", []))
    except Exception:
        return set()


def _write_manifest(target: Path, files: list[str]) -> None:
    """写出安装清单（按路径排序）。"""
    (target / MANIFEST_FILE).write_text(
        json.dumps({"files": sorted(files)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _collect_source_files(src: Path, base: Path | None = None,
                          root_skip: frozenset[str] = frozenset()) -> list[str]:
    """收集 src 中所有要复制的文件的相对路径列表（使用正斜杠）。

    root_skip 仅在第一层生效（不传入递归调用），用于排除 source root 顶层运行态目录。
    """
    if base is None:
        base = src
    result = []
    for item in src.iterdir():
        if item.name in _EXCLUDE_NAMES or item.suffix in _EXCLUDE_SUFFIXES:
            continue
        if item.name in root_skip:
            continue
        if item.is_dir():
            result.extend(_collect_source_files(item, base))
        else:
            result.append(item.relative_to(base).as_posix())
    return result


def _sync_dir(src: Path, dst: Path, root_skip: frozenset[str] = frozenset()) -> int:
    """递归同步 src 到 dst。

    只写入 src 中存在的文件，不删除 dst 中独有的文件（保护客户端自定义）。
    root_skip 仅在第一层生效（不传入递归调用），用于排除 source root 顶层运行态目录。
    返回更新的文件数。
    """
    # 类型冲突：dst 当前是文件，但 src 是目录 → 先删文件，再 mkdir
    if dst.exists() and not dst.is_dir():
        dst.unlink()
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in src.iterdir():
        if item.name in _EXCLUDE_NAMES or item.suffix in _EXCLUDE_SUFFIXES:
            continue
        if item.name in root_skip:
            continue
        dest = dst / item.name
        if item.is_dir():
            count += _sync_dir(item, dest)  # root_skip 不传入递归调用
        else:
            # 类型冲突：dest 当前是目录，但 src 是文件 → 先删目录，再复制
            if dest.is_dir():
                shutil.rmtree(dest)
            shutil.copy2(item, dest)
            count += 1
    return count


def install(target: Path) -> None:
    """将 skill bundle 同步到 target 目录。"""
    # guard: target 不能位于 source 内部（防止无限递归）
    target_resolved = target.resolve()
    source_resolved = SKILL_DIR.resolve()
    if target_resolved == source_resolved or target_resolved.is_relative_to(source_resolved):
        raise ValueError(
            f"target ({target_resolved}) 不能位于 source 目录 ({source_resolved}) 内部，"
            "请指定 source 树之外的路径。"
        )

    # 读取旧 manifest（无 manifest 时为空集合，不做 prune，向后兼容旧版安装）
    old_manifest = _read_manifest(target)

    # 同步 source → target
    count = _sync_dir(SKILL_DIR, target, root_skip=_EXCLUDE_ROOT_NAMES)

    # 收集当前 source 文件集合（使用正斜杠路径，与 manifest 一致）
    new_files = _collect_source_files(SKILL_DIR, root_skip=_EXCLUDE_ROOT_NAMES)
    new_files_set = set(new_files)

    # 删除 manifest 记录中存在但 source 中已不存在的文件（upstream 删除的旧文件）
    pruned = 0
    for rel in old_manifest:
        if rel not in new_files_set:
            stale = target / rel
            if stale.is_file():          # 只删文件；路径已变目录说明是 file→dir 升级，不动
                stale.unlink()
                pruned += 1

    # 清理 manifest 路径树下 upstream 删除后遗留的空目录（安全：rmdir 只删空目录）
    old_dirs: set[str] = set()
    for rel in old_manifest:
        for parent in Path(rel).parents:
            s = parent.as_posix()
            if s != ".":
                old_dirs.add(s)
    for rel_dir in sorted(old_dirs, key=lambda x: x.count("/"), reverse=True):
        d = target / rel_dir
        if d.is_dir():
            try:
                d.rmdir()
                pruned += 1
            except OSError:
                pass  # 非空（含新文件或用户文件），跳过

    # 写出新 manifest
    _write_manifest(target, new_files)

    summary = f"[dp] 已同步 {count} 个文件到 {target.resolve()}"
    if pruned:
        summary += f"（清理 {pruned} 个旧文件）"
    print(summary)


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
