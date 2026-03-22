"""统一输出路径管理——确保每次输出都有规范的文件名和目录结构。"""
from datetime import datetime
from pathlib import Path


def workspace_root() -> Path:
    """返回 .dp/ 工作区根目录，按库文件所在位置解析，不依赖当前 cwd。"""
    return Path(__file__).resolve().parent.parent


def site_output(site: str, type_: str, desc: str = "", ext: str = "png") -> Path:
    """
    返回归档输出路径：.dp/projects/<site>/output/YYYY-MM-DD/<type>_HHMMSS[_desc].<ext>

    例：site_output("hn", "screenshot", "full") -> .dp/projects/hn/output/2026-03-18/screenshot_142300_full.png
    """
    now = datetime.now()
    name = f"{type_}_{now.strftime('%H%M%S')}"
    if desc:
        name += f"_{desc}"
    path = workspace_root() / "projects" / site / "output" / now.strftime("%Y-%m-%d") / f"{name}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def tmp_out(filename: str) -> Path:
    """返回临时输出路径：.dp/tmp/_out/<filename>（未归档时使用）。"""
    path = workspace_root() / "tmp" / "_out" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
