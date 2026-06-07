# 站点 README 规则

当需要创建或维护 `.dp/projects/<site>/README.md` 时，读取本文。

站点 README 是面向人的 workflow 索引，不是脚本 metadata 的唯一真源。
它采用混合托管模型：`## Scripts` 区块由 Agent 自动维护，其余章节由人工维护。
这样既能让脚本索引保持更新，也不会覆盖用户手写的站点说明、登录备注或注意事项。

Workflow discovery 的证据默认写入 discovery run-dir 中的 `workflow-draft.md`，不是直接写入 README。
如需长期站点级草案索引，可写入 `workflow-drafts/<intent>.md`，但它只保存稳定结论和 evidence run-dir 链接。
只有已经达到可复用条件的 readiness、probe、inspect 或业务 workflow 脚本，才进入 README 的托管
`## Scripts` 区。

## 最小骨架（必需）

```md
# <site-name>

## Scripts

<!-- dp:scripts:start -->
<!-- dp:scripts:end -->

## Notes

## Last Updated
```

## Scripts 托管区

`## Scripts` 区块使用托管标记。Agent 只更新标记之间的内容：

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

脚本头 docstring 里的 `site`、`workflow_summary`、`intent`、`url`、`tags`、`status`、`last_run`
仍然是机器可读真源。`workflow_summary` 是 workflow 的一句话摘要，也是 README 条目的主要展示文本。
README 是展示层，方便人和 Agent 快速理解站点已有能力。

## 托管区操作规则

- 新增已沉淀脚本：在 `<!-- dp:scripts:end -->` 前插入条目
- 修改已沉淀脚本：更新对应条目内容和 `updated:` 日期，同时更新 `## Last Updated`
- 删除已沉淀脚本：移除对应条目
- 临时脚本和一次性探索脚本：不写入 README
- Discovery 产物和中间结论：默认写入 discovery run-dir 的 `workflow-draft.md`
- 站点级 discovery 草案索引：可选写入 `workflow-drafts/<intent>.md`
- Agent 不重写整份 README，不触碰托管区之外的任何内容
- 只有用户明确要求维护 README，或当前任务就是 README 维护时，才建议或改写人工章节
- 若托管区标记损坏或缺失，Agent 只输出 warning，不强制重写整份文件

## 可选章节

只有站点复杂度需要时再增加。这些章节由人工维护，Agent 不自动改写：

- `## Login`
- `## Common Selectors`
- `## Output Fields`
- `## Caveats`

## 分工

| 区块 | 维护方 | 说明 |
|---|---|---|
| `## Scripts`（托管区） | Agent 自动维护 | 只改标记内内容 |
| `## Notes` / `## Login` 等 | 人工维护 | Agent 不触碰 |
| `## Last Updated` | Agent 可随脚本索引更新 | 反映 README 索引更新时间 |
| discovery run-dir `workflow-draft.md` | Agent 可维护 | 保存单次 discovery 证据、候选选择器和沉淀建议 |
| `workflow-drafts/<intent>.md` | Agent 可维护 | 可选长期索引，只写稳定结论和 evidence run-dir 链接 |

## README 维护边界

Discovery 可以提出 README 更新建议，但不自动改写人工章节。若用户要求整理站点文档，
Agent 可以把 discovery run-dir 或 `workflow-drafts/<intent>.md` 中已经验证的稳定信息迁移到 README 的人工章节；
否则只维护 `## Scripts` 托管区。
