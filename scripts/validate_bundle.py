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
    "templates/download_correlation.py",
    "templates/output.py",
    "templates/utils.py",
    "templates/_dp_compat.py",
    "templates/providers/cdp-port.py",
    "references/interface.md",
    "references/mode-selection.md",
    "references/provider-contract.md",
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
REMOVED_CONNECT_WRAPPER_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_])connect_browser\("),
    re.compile(r"(?<![A-Za-z0-9_])connect_browser_fresh_tab\("),
    re.compile(r"(?<![A-Za-z0-9_])connect_web_page\("),
)


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


_FORBIDDEN_TEXT_SKIP = {
    "scripts/validate_bundle.py",
    "scripts/test_helpers.py",
    # README 是面向用户的文档，允许举例说明各客户端的适配文件（如 openai.yaml）
    "README.md",
    "README_EN.md",
}


def validate_forbidden_text(root: Path) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in _FORBIDDEN_TEXT_SKIP:
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
        "templates/download_correlation.py",
        "templates/output.py",
        "templates/utils.py",
        "templates/_dp_compat.py",
        "templates/providers/cdp-port.py",
    ):
        path = root / rel
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")


def _extract_section(text: str, heading: str) -> str:
    """提取 markdown 中指定标题的章节文本，直到下一个同级或更高级标题为止。"""
    heading_level = len(heading) - len(heading.lstrip('#'))
    lines = text.splitlines()
    in_section = False
    result = []
    for line in lines:
        if not in_section:
            if line.strip() == heading.strip():
                in_section = True
        else:
            if line.startswith('#') and (len(line) - len(line.lstrip('#'))) <= heading_level:
                break
            result.append(line)
    return '\n'.join(result)


def validate_rule_markers(root: Path) -> None:
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    # 稳定 contract token / 导航锚点：保持硬检查
    if "站点 README 规则" not in skill:
        fail("SKILL.md 缺少站点 README 规则")
    if "runtime_lib_version" not in skill:
        fail("SKILL.md 缺少 runtime_lib_version preflight 描述")
    if "bundle_version" not in skill:
        fail("SKILL.md 缺少 bundle_version preflight 描述")
    # 章节内多要素检查：token 必须出现在对应章节，不接受散落在全文的假阳性
    port_sec = _extract_section(skill, "### 3. 端口与连接策略")
    if "cdp-port" not in port_sec or "显式" not in port_sec or "port" not in port_sec:
        fail("SKILL.md 端口策略章节缺少 cdp-port 显式端口说明（应在该章节内同时提到 cdp-port、显式 与 port）")
    reuse_sec = _extract_section(skill, "### 5. 复用优先")
    if "list-scripts.py" not in reuse_sec or "--root" not in reuse_sec or "cwd" not in reuse_sec:
        fail("SKILL.md 复用优先章节缺少 list-scripts 显式根路径说明（应在该章节内同时提到 list-scripts.py、--root 与 cwd）")
    preflight_sec = _extract_section(skill, "### 1. Preflight（工作区检测）")
    required_preflight_tokens = (
        "工作区根",
        "cwd",
        ".dp",
        ".dp/config.json",
        "default_provider",
        ".dp/providers/cdp-port.py",
        ".dp/state.json",
        "runtime_lib_version",
        "bundle_version",
    )
    missing_preflight_tokens = [token for token in required_preflight_tokens if token not in preflight_sec]
    if missing_preflight_tokens:
        fail(
            "SKILL.md Preflight 章节缺少 workspace contract 关键项："
            + ", ".join(missing_preflight_tokens)
        )

    managed_readiness_tokens = (
        "DrissionPage",
        ".dp/lib/connect.py",
        ".dp/lib/download_correlation.py",
        ".dp/lib/output.py",
        ".dp/lib/utils.py",
        ".dp/lib/_dp_compat.py",
    )
    missing_managed_readiness_tokens = [token for token in managed_readiness_tokens if token not in preflight_sec]
    if missing_managed_readiness_tokens:
        fail(
            "SKILL.md Preflight 章节缺少 managed lib / DrissionPage ready 条件："
            + ", ".join(missing_managed_readiness_tokens)
        )

    has_illegal_provider_boundary = (
        "default_provider" in preflight_sec
        and "不合法" in preflight_sec
        and ("配置错误" in preflight_sec or "非法" in preflight_sec)
        and ("不做猜测式修复" in preflight_sec or "不会自动修复" in preflight_sec)
        and ("需用户" in preflight_sec or "需客户端" in preflight_sec or "需修正配置" in preflight_sec)
    )
    if not has_illegal_provider_boundary:
        fail(
            "SKILL.md Preflight 章节缺少非法 default_provider 的 fail-fast 边界"
            "（应说明其属于配置错误、doctor 不会自动修复，且需用户或客户端修正配置）"
        )

    has_selected_provider_boundary = (
        "cdp-port" in preflight_sec
        and ("当前默认 provider" in preflight_sec or "default_provider" in preflight_sec)
        and (
            "对应 provider 文件" in preflight_sec
            or ".dp/providers/<name>.py" in preflight_sec
            or ".dp/providers/" in preflight_sec
        )
        and ("必须存在" in preflight_sec or "也必须存在" in preflight_sec)
        and ("配置错误" in preflight_sec or "提供实现" in preflight_sec or "修正配置" in preflight_sec)
    )
    if not has_selected_provider_boundary:
        fail(
            "SKILL.md Preflight 章节缺少当前默认 provider 实现存在性边界"
            "（应说明非 cdp-port 默认 provider 需要对应实现文件存在，缺失时需用户或客户端提供实现或修正配置）"
        )

    interaction_sec = _extract_section(skill, "### 4. 交互与节奏约束")
    has_file_helper_fail_fast_boundary = (
        ("upload_file()" in interaction_sec or "download_file()" in interaction_sec)
        and "launch_info" in interaction_sec
        and ("provider hints" in interaction_sec or "本地文件访问" in interaction_sec or "file_access_mode" in interaction_sec)
        and ("remote" in interaction_sec or "不支持本地文件访问" in interaction_sec)
        and ("直接报错" in interaction_sec or "直接失败" in interaction_sec or "fail fast" in interaction_sec)
    )
    if not has_file_helper_fail_fast_boundary:
        fail(
            "SKILL.md 交互章节缺少 remote file helper 的 fail-fast 边界"
            "（应说明 upload/download 在传入 launch_info 后若 provider 明确不支持本地文件访问则直接报错）"
        )


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


def validate_removed_connect_wrappers(root: Path) -> None:
    """canonical docs 不应再引用已移除的 legacy connect wrapper。"""
    for rel in (
        "SKILL.md",
        "references/workflows.md",
        "references/mode-selection.md",
        "evals/smoke-checklist.md",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        for pattern in REMOVED_CONNECT_WRAPPER_PATTERNS:
            if pattern.search(text):
                fail(f"{rel} 不应再引用已移除的 legacy connect API：{pattern.pattern}")


def _extract_same_level_heading_section(text: str, heading: str) -> str:
    """按同级 heading 提取章节，避免被代码块里的 # 注释提前截断。"""
    marker = f"{heading}\n"
    start = text.find(marker)
    if start < 0:
        return ""
    remainder = text[start + len(marker):]
    match = re.search(r"^## ", remainder, re.MULTILINE)
    return remainder[:match.start()] if match else remainder


def validate_workflow_file_helper_contracts(root: Path) -> None:
    """canonical workflows 的 upload/download contract 不应弱化 remote fail-fast 边界。"""
    workflows = (root / "references" / "workflows.md").read_text(encoding="utf-8")

    upload_sec = _extract_same_level_heading_section(workflows, "## Workflow 5：文件上传（upload）")
    has_upload_boundary = (
        "upload_file" in upload_sec
        and "launch_info" in upload_sec
        and ("provider hints" in upload_sec or "本地文件访问" in upload_sec or "file_access_mode" in upload_sec)
        and ("remote" in upload_sec or "不支持本地文件访问" in upload_sec)
        and ("直接报错" in upload_sec or "直接失败" in upload_sec or "fail fast" in upload_sec)
    )
    if not has_upload_boundary:
        fail(
            "references/workflows.md 的 upload contract 缺少 remote file helper 的 fail-fast 边界"
            "（应说明 upload_file(..., launch_info=launch_info) 在 provider 明确不支持本地文件访问时直接报错）"
        )

    download_sec = _extract_same_level_heading_section(workflows, "## Workflow 6：文件下载（download）")
    has_download_boundary = (
        "download_file" in download_sec
        and "launch_info" in download_sec
        and ("remote" in download_sec or "不支持本地文件访问" in download_sec)
        and ("直接报错" in download_sec or "直接失败" in download_sec or "fail fast" in download_sec)
    )
    if not has_download_boundary:
        fail(
            "references/workflows.md 的 download contract 缺少 remote file helper 的 fail-fast 边界"
            "（应说明 download_file(..., launch_info=launch_info) 在 provider 明确不支持本地文件访问时直接报错）"
        )


def validate_smoke_checklist_contracts(root: Path) -> None:
    """smoke checklist 的 preflight prose 不应弱化已收口的公共 contract。"""
    checklist = (root / "evals" / "smoke-checklist.md").read_text(encoding="utf-8")
    preflight_sec = _extract_same_level_heading_section(checklist, "## 2. Preflight 检查")

    has_non_string_repair_boundary = (
        "default_provider" in preflight_sec
        and "非字符串" in preflight_sec
        and ("自动修复" in preflight_sec or "触发 doctor" in preflight_sec)
    )
    if not has_non_string_repair_boundary:
        fail(
            "evals/smoke-checklist.md 的 Preflight 检查缺少 non-string default_provider 的 repair 边界"
            "（应说明 default_provider 为非字符串时也属于 doctor 可自动修复的未初始化状态）"
        )

    has_selected_provider_snake_case_boundary = (
        ("当前默认 provider" in preflight_sec or "default_provider" in preflight_sec)
        and ("对应 provider 文件" in preflight_sec or ".dp/providers/<name>.py" in preflight_sec)
        and "snake_case" in preflight_sec
    )
    if not has_selected_provider_snake_case_boundary:
        fail(
            "evals/smoke-checklist.md 的 Preflight 检查缺少等价 snake_case provider 文件边界"
            "（应说明非 cdp-port 默认 provider 除 `.dp/providers/<name>.py` 外，也接受等价 snake_case 文件）"
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
    validate_removed_connect_wrappers(root)
    validate_workflow_file_helper_contracts(root)
    validate_smoke_checklist_contracts(root)
    run_unit_tests(root)
    cleanup_bytecode(root)  # 清除测试运行可能产生的字节码
    print("[OK] bundle looks clean")


if __name__ == "__main__":
    main()
