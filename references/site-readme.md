# 站点 README 规则

` .dp/projects/<site>/README.md ` 是站点级 workflow 索引。它是强约定，但不要求由脚本自动生成。

## 最小骨架（必需）

```md
# <site-name>

## Scripts

## Notes

## Last Updated
```

## Scripts 条目规则

每个已沉淀脚本至少记录：

- 文件名
- 一句话用途
- 推荐复用场景
- 最后更新时间

推荐格式：

```md
- `scripts/login.py` - 登录并进入报表页；适用于需要复用登录态的场景；updated: 2026-03-20
```

## 可选扩展（按需披露）

只有在站点复杂度需要时再增加：

- `## Login`
- `## Common Selectors`
- `## Output Fields`
- `## Caveats`

## 更新义务

- 新增已沉淀脚本 -> 加条目
- 修改已沉淀脚本 -> 更新条目和 `Last Updated`
- 删除已沉淀脚本 -> 删除条目
- 临时脚本 -> 不写入 README
