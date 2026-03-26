# 站点 README 规则

`.dp/projects/<site>/README.md` 是站点级 workflow 索引。它是强约定，**采用混合托管模型**：
`## Scripts` 区块由 Agent 自动维护，其余章节由人工维护。

## 最小骨架（必需）

```md
# <site-name>

## Scripts

<!-- dp:scripts:start -->
<!-- dp:scripts:end -->

## Notes

## Last Updated
```

## Scripts 托管区规则

`## Scripts` 区块使用托管标记，Agent 只更新标记之间的内容：

```md
## Scripts

<!-- dp:scripts:start -->
- `scripts/login.py` - 登录并进入报表页；适用于需要复用登录态的场景；updated: 2026-03-26
- `scripts/scrape-orders.py` - 抓取订单列表并保存 JSON；适用于定期数据导出；updated: 2026-03-26
<!-- dp:scripts:end -->
```

每个已沉淀脚本至少记录：

- 文件名
- 一句话用途
- 推荐复用场景
- 最后更新时间（`updated: YYYY-MM-DD`）

**真源**：脚本头 docstring 里的 `task`、`intent`、`url`、`tags`、`status`、`last_run` 字段；
README 是面向人的展示层，不作为唯一真源。

## 托管区操作规则

- 新增已沉淀脚本 → 在 `<!-- dp:scripts:end -->` 前插入条目
- 修改已沉淀脚本 → 更新对应条目内容和 `updated:` 日期，同时更新 `## Last Updated`
- 删除已沉淀脚本 → 移除对应条目
- 临时脚本和一次性探索脚本 → 不写入 README
- **Agent 不重写整份 README，不触碰托管区之外的任何内容**
- 若托管区标记损坏或缺失，Agent 只输出 warning，不强制重写整份文件

## 可选扩展（按需披露）

只有在站点复杂度需要时再增加（这些章节完全由人工维护，Agent 不修改）：

- `## Login`
- `## Common Selectors`
- `## Output Fields`
- `## Caveats`

**分工说明**：

| 区块 | 维护方 | 说明 |
|---|---|---|
| `## Scripts`（托管区） | Agent 自动维护 | 只改标记内内容 |
| `## Notes` / `## Login` 等 | 人工维护 | Agent 不触碰 |
| `## Last Updated` | 修改脚本时顺带更新 | Agent 可一并更新 |
