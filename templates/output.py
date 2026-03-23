"""统一输出路径管理——每次执行对应一个带时间戳的 run 目录。"""
from datetime import datetime
from pathlib import Path


def workspace_root() -> Path:
    """返回 .dp/ 工作区根目录，按库文件所在位置解析，不依赖当前 cwd。"""
    return Path(__file__).resolve().parent.parent


def site_run_dir(site: str, script_name: str) -> Path:
    """
    创建并返回本次执行的输出目录。
    路径：.dp/projects/<site>/output/<script-name>/YYYY-MM-DD_HHMMSS_mmm/

    一个目录对应一次执行，单文件或多文件输出结构一致。
    在目录下直接用语义文件名，如 run / "data.json"、run / "screenshot.png"。
    时间戳精确到毫秒，避免同秒重试时落到同一目录。

    例：site_run_dir("hn", "scrape-top")
        → .dp/projects/hn/output/scrape-top/2026-03-18_142300_123/
    """
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d_%H%M%S") + f"_{now.microsecond // 1000:03d}"
    path = (
        workspace_root()
        / "projects"
        / site
        / "output"
        / script_name
        / ts
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def tmp_out(filename: str) -> Path:
    """返回临时输出路径：.dp/tmp/_out/<filename>（未归档时使用）。"""
    path = workspace_root() / "tmp" / "_out" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
