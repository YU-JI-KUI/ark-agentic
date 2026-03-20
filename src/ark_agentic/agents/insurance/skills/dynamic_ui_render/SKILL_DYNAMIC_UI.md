---
name: 动态UI渲染参考
description: render_a2ui 块类型和 Transform DSL 语法参考。不直接触发，仅供其他技能引用。
version: "5.0.0"
invocation_policy: always
group: insurance
tags:
  - a2ui
  - dynamic
  - rendering
required_tools:
  - render_a2ui
---

# 动态 UI 渲染参考

本技能是 `render_a2ui` 工具的**语法参考**。具体场景请参考：
- 个人信息 / 保单列表 → `view_info` 技能
- 取款总览 / 具体方案 / 方案调整 → `withdraw_money` 技能

## 块类型速查

| 类型 | 数据槽 | 说明 |
|------|--------|------|
| `SummaryHeader` | `title, value, subtitle?, note?` | 顶部汇总（居中大字） |
| `SectionCard` | `title, tag?, total, items` | 分组卡片（标题栏 + 总计 + KV 列表） |
| `InfoCard` | `title, body` | 简单信息卡片 |
| `AdviceCard` | `icon?, title, texts[]` | 建议/提示卡片 |
| `KeyValueList` | `items` 或 `rowCount + rowPrefix` | 独立 label:value 列表 |
| ~~`DataTable`~~ | ~~`columns[], data`~~ | ~~表格~~ **已废弃，用 SectionCard 堆叠替代** |
| `ItemList` | `items, titleField, tagField?, valueField, subtitleField?` | 项目列表 |
| `ActionButton` | `text, action, variant?` | 主操作按钮 |
| `ButtonGroup` | `buttons[]` | 多按钮行 |
| `Divider` | _(无)_ | 分割线 |
| `TagRow` | `tags[]` | 标签行 |
| `ImageBanner` | `url, fit?` | 图片横幅 |
| `StatusRow` | `label, value, status?` | 状态行（success/warning/error/info） |

### DataTable 废弃说明

`DataTable` 存在结构性问题（表头用 CSS Grid，数据行用 Flexbox，对齐不可靠）。新技能应使用以下替代模式：

- **多条记录详情展示** → **SectionCard 堆叠**（每条记录一个 SectionCard）
- **简单列表展示** → **ItemList**

### 数据绑定

- `"$field_name"` → 引用 transforms 计算出的字段
- 纯字符串 → 静态值

### Action 格式

```json
{"name": "query", "args": "$action_args"}
```

## Transform DSL

所有数值通过 Transform DSL 从 context 原始数据确定性计算，**绝不由 LLM 直接生成数字**。

| 操作 | 语法 | 说明 |
|------|------|------|
| `get` | `{"get": "field.path", "format": "currency"}` | 取值+格式化 |
| `literal` | `{"literal": "静态文本"}` | 静态值（支持字符串、数组、对象） |
| `sum` | `{"sum": "array.field", "format": "currency"}` | 数组字段求和 |
| `count` | `{"count": "array", "where": {...}}` | 条件计数 |
| `concat` | `{"concat": ["前缀", {"get": "field"}, "后缀"]}` | 拼接 |
| `select` | `{"select": "array", "where": {...}, "map": {...}}` | 筛选+投影 |
| `switch` | `{"switch": "$.field", "cases": {...}, "default": "other"}` | 条件映射 |

格式化：`currency` → `¥ 12,000.00`，`percent` → `5%`，`int` → 整数

Where 条件：`{"field": "> 0"}`，`{"or": [{...}, {...}]}`

## 常用模式

### 模式 1：SectionCard 堆叠（详情列表）

当需要展示多条记录的详细信息时，为每条记录生成一个 `SectionCard`。

```
blocks=[
  {"type": "SummaryHeader", "data": {"title": "$title", "value": "$summary"}},
  {"type": "SectionCard", "data": {"title": "$r1_name", "tag": "$r1_id", "total": "$r1_total", "items": "$r1_items"}},
  {"type": "SectionCard", "data": {"title": "$r2_name", "tag": "$r2_id", "total": "$r2_total", "items": "$r2_items"}}
]
```

**关键**：SectionCard 数量 = 数据记录数。LLM 按实际数据条数生成对应数量的 SectionCard。

### 模式 2：方案卡（SectionCard + ActionButton 对）

当需要展示多个可选方案（每个方案有独立操作按钮）时使用。

```
blocks=[
  {"type": "SummaryHeader", "data": {"title": "$goal", "value": "$amount"}},
  {"type": "SectionCard", "data": {"title": "$plan1_title", "tag": "$plan1_tag", "total": "$plan1_total", "items": "$plan1_items"}},
  {"type": "ActionButton", "data": {"text": "$plan1_btn", "action": {"name": "query", "args": "$plan1_action"}}},
  {"type": "SectionCard", "data": {"title": "$plan2_title", "tag": "$plan2_tag", "total": "$plan2_total", "items": "$plan2_items"}},
  {"type": "ActionButton", "data": {"text": "$plan2_btn", "action": {"name": "query", "args": "$plan2_action"}}},
  {"type": "AdviceCard", "data": {"icon": "💡", "title": "$advice", "texts": ["$tip1"]}}
]
```

**关键**：每个方案是紧邻的 `SectionCard` + `ActionButton` 对。方案数由 LLM 根据业务逻辑决定（通常 2-3 个）。

## 数字安全规则

1. **所有金额/利率/数量**必须通过 Transform DSL 获取
2. **禁止**在 blocks 的 data 中硬编码任何数字
3. 文案中的数字用 `concat` + `get` + `format` 组合

**错误示例** ✗
```json
{"type": "SummaryHeader", "data": {"value": "¥ 337,800.00"}}
```

**正确示例** ✓
```json
{"type": "SummaryHeader", "data": {"value": "$total_value"}}
// transforms: {"total_value": {"get": "total_available_incl_loan", "format": "currency"}}
```
