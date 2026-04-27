# Contributing

**[English](CONTRIBUTING_EN.md)**

本仓库的 source of truth 是当前目录中的 source bundle。发布前请确保 `.dp/`、虚拟环境、
浏览器 profile、临时输出和本地运行状态都没有进入仓库。

## 版本规范

`SKILL.md` frontmatter 中维护两个版本字段：

| 字段 | 含义 | 触发条件 |
|------|------|----------|
| `runtime-lib-version` | 工作区运行时库版本 | 修改 `templates/` 下任意运行时代码 |
| `bundle-version` | 整个 source bundle 版本 | 任意会被分发的文件发生变化 |

格式：`YYYY-MM-DD.N`，表示当天第 N 次发布。

## 如何 bump

- 只改 README、references、evals、scripts 或其他非运行时代码：只 bump `bundle-version`
- 修改 `templates/connect.py`、`templates/output.py`、`templates/utils.py`、
  `templates/download_correlation.py`、`templates/_dp_compat.py` 或 provider 模板：
  同时 bump `runtime-lib-version` 和 `bundle-version`
- 如果同一天已经发布过，递增 `.N`，不要复用旧版本号

## Doctor 刷新语义

`doctor.py` 通过 `.dp/state.json` 判断工作区是否需要刷新：

- `runtime-lib-version` 变化时，doctor 会同步 `.dp/lib/` 和 runtime-managed provider，
  并更新 `.dp/state.json`
- 只有 `bundle-version` 变化时，doctor 只刷新工作区文档/状态，不重建 venv，
  也不同步 runtime-managed 代码

因此，改动运行时模板但忘记 bump `runtime-lib-version` 会导致已有工作区继续使用旧 helper。
这是发布错误，不是 doctor 的行为问题。

## 发布检查

1. 修改 source bundle 文件
2. 按上面的规则 bump `SKILL.md`
3. 运行 bundle 校验：
   ```bash
   python scripts/validate_bundle.py
   ```
4. 如需本机安装副本测试，用安装脚本从 source bundle 单向同步：
   ```bash
   python scripts/install.py --target /path/to/skills/dp
   ```
5. 在目标工作区运行 doctor 或 smoke，确认安装副本和 `.dp/state.json` 已反映新版本

## 文档原则

- `SKILL.md` 写 Agent 必须遵守的执行 contract，不写成宣传页
- `README*.md` 面向人类读者，解释设计模型、安装、使用和目录结构
- `references/*.md` 按主题承载细节，供 Agent 渐进披露式读取
- `evals/*` 保持可操作的验收语言，避免只写抽象原则
- 不为了“短”而删除关键边界；文档应优先合理、准确、可执行
