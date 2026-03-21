---
name: 动态UI渲染参考
description: render_a2ui 块类型和 Transform DSL 语法参考。不直接触发，仅供其他技能引用。
version: "6.0.0"
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

block data 的值可以是：

- **纯字符串/数字** → 直接使用（静态值）
- **Transform spec 对象** → 运行时由 BlockComposer 求值

Transform spec 直接写在 block data 的值位置，不需要单独的 `transforms` 参数。

### Action 格式

```json
{"name": "query", "args": {"queryMsg": "用户点击后发送的文本"}}
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
  {"type": "SummaryHeader", "data": {"title": {"literal": "总览"}, "value": {"get": "total", "format": "currency"}}},
  {"type": "SectionCard", "data": {"title": {"get": "records[0].name"}, "tag": {"get": "records[0].id"}, "total": {"get": "records[0].amount", "format": "currency"}, "items": [
    {"label": "明细A", "value": {"get": "records[0].detail_a", "format": "currency"}},
    {"label": "明细B", "value": {"get": "records[0].detail_b", "format": "currency"}}
  ]}},
  {"type": "SectionCard", "data": {"title": {"get": "records[1].name"}, "tag": {"get": "records[1].id"}, "total": {"get": "records[1].amount", "format": "currency"}, "items": [
    {"label": "明细A", "value": {"get": "records[1].detail_a", "format": "currency"}},
    {"label": "明细B", "value": {"get": "records[1].detail_b", "format": "currency"}}
  ]}}
]
```

**关键**：SectionCard 数量 = 数据记录数。LLM 按实际数据条数生成对应数量的 SectionCard。

### 模式 2：方案卡（SectionCard + ActionButton 对）

当需要展示多个可选方案（每个方案有独立操作按钮）时使用。

```
blocks=[
  {"type": "SummaryHeader", "data": {"title": {"literal": "本次取款目标"}, "value": {"get": "requested_amount", "format": "currency"}}},
  {"type": "SectionCard", "data": {"title": {"literal": "方案一 ⭐ 推荐"}, "tag": {"literal": "零成本"}, "total": {"literal": "方案总额"}, "items": [
    {"label": "POL002 金瑞人生 · 生存金", "value": {"get": "options[0].survival_fund_amt", "format": "currency"}},
    {"label": "POL002 金瑞人生 · 红利", "value": {"get": "options[0].bonus_amt", "format": "currency"}}
  ]}},
  {"type": "ActionButton", "data": {"text": {"literal": "一键领取 (方案一)"}, "action": {"name": "query", "args": {"queryMsg": "确认方案一"}}}},
  {"type": "AdviceCard", "data": {"icon": "💡", "title": {"literal": "建议"}, "texts": [{"literal": "• 推荐方案一，零成本不影响保障。"}]}}
]
```

**关键**：每个方案是紧邻的 `SectionCard` + `ActionButton` 对。方案数由 LLM 根据业务逻辑决定（通常 2-3 个）。

### items 数组规则

当 items 数组内的值包含 transform spec（如 `{"get": ...}`），数组必须是**裸数组**，不能用 `{"literal": [...]}` 包裹：

```python
# 错误 — literal 内的 transform spec 不会被解析
"items": {"literal": [
  {"label": "生存金", "value": {"get": "amt", "format": "currency"}}
]}

# 正确 — 裸数组，composer 递归解析每个值
"items": [
  {"label": "生存金", "value": {"get": "amt", "format": "currency"}}
]
```

纯静态数组（值中无 transform spec）可以用 `{"literal": [...]}`。

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
{"type": "SummaryHeader", "data": {"value": {"get": "total_available_incl_loan", "format": "currency"}}}
```
