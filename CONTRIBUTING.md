# Contributing

**[English](CONTRIBUTING_EN.md)**

## 版本规范

`SKILL.md` 头部维护两个版本字段，每次发布前按下表更新：

| 字段 | 含义 | 触发条件 |
|------|------|----------|
| `runtime-lib-version` | 运行时库版本 | 修改 `templates/` 下任意文件 |
| `bundle-version` | Bundle 整体版本 | 任何文件变更 |

格式：`YYYY-MM-DD.N`（当天第 N 次发布）

两个字段同时 bump 时（templates/ 有变更），需重跑 `doctor.py` 更新工作区 `.dp/lib/`；
只 bump `bundle-version` 时（文档/脚本变更），doctor 可跳过。

## 发布流程

1. 修改源文件
2. 按上表 bump `SKILL.md` 中的对应字段
3. 运行 `scripts/validate_bundle.py` 校验 bundle 完整性
4. 同步安装副本（如有本地测试需求）：
   ```bash
   python scripts/install.py --target /path/to/skills/dp
   ```
