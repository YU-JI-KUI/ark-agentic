---
name: 信息查询
description: 查询并展示用户个人信息或保单列表，以 A2UI 卡片呈现。
version: "4.0.0"
invocation_policy: auto
group: insurance
tags:
  - query
  - info
  - policy
required_tools:
  - customer_info
  - rule_engine
  - render_a2ui
---

# 信息查询技能

当用户询问个人信息或保单情况时，调用对应数据工具获取数据，然后通过 `render_a2ui` 以卡片展示。

## 触发条件

- "我的信息" / "个人信息" / "查看我的资料" → Case 1
- "我的保单" / "有什么保单" / "保单列表" / "我买了什么保险" / "保单数量" / "持有哪些产品" / "额度明细" → Case 2

**不触发**：
- 涉及取款/取钱 → 由 withdraw_money 处理
- 金额相关问题 → 由 withdraw_money 处理

## 回复结构

`[1 句引导语] + A2UI 卡片`

---

## Case 1：个人信息

客户档案展示：名字为 Hero 元素，关键信息以 KV 列表呈现，家庭成员单独 Card。

### 执行流程

```
customer_info(info_type="full", user_id=用户ID)
→ render_a2ui(blocks=...)
```

### 完整示例

使用 fine blocks 动态组合：

```json
[
  {"type": "Card", "data": {"padding": 20, "children": [
    {"type": "SectionHeader", "data": {"title": "客户档案"}},
    {"type": "KVRow", "data": {"label": "姓名", "value": {"get": "identity.name"}}},
    {"type": "KVRow", "data": {"label": "证件类型", "value": {"get": "identity.id_type"}}},
    {"type": "KVRow", "data": {"label": "证件号码", "value": {"get": "identity.id_number"}}},
    {"type": "KVRow", "data": {"label": "性别", "value": {"get": "identity.gender"}}},
    {"type": "KVRow", "data": {"label": "出生日期", "value": {"get": "identity.birth_date"}}},
    {"type": "KVRow", "data": {"label": "年龄", "value": {"concat": [{"get": "identity.age"}, "岁"]}}},
    {"type": "KVRow", "data": {"label": "婚姻状况", "value": {"get": "identity.marital_status"}}},
    {"type": "Divider"},
    {"type": "KVRow", "data": {"label": "联系电话", "value": {"get": "contact.phone"}}},
    {"type": "KVRow", "data": {"label": "邮箱", "value": {"get": "contact.email"}}}
  ]}},
  {"type": "Card", "data": {"children": [
    {"type": "SectionHeader", "data": {"title": "家庭成员", "tag": "2人"}},
    {"type": "KVRow", "data": {"label": "配偶", "value": "李芳"}},
    {"type": "KVRow", "data": {"label": "子女", "value": "张小明"}}
  ]}}
]
```

### 数据字段参考（customer_info full，与 data_service mock 一致）

**identity**：name, id_type, id_number, gender, birth_date, age, has_children, marital_status, verified, verification_date
**contact**：phone, email, address, preferred_contact, contact_time_preference

卡片展示时从 identity / contact 用 get 取上述字段，勿编造字段名。

---

## Case 2：保单列表

使用 fine blocks 为每张保单动态构建 Card，LLM 根据用户需求控制展示哪些字段。

### 执行流程

```
rule_engine(action="list_options", user_id=用户ID)
→ render_a2ui(blocks=...)
```

### 完整示例（3张保单）

LLM 读取 `rule_engine` 返回的 `options` 数组，为每张保单生成一个 Card：

```json
[
  {"type": "Card", "data": {"children": [
    {"type": "SectionHeader", "data": {"title": "富贵人生保险"}},
    {"type": "HintText", "data": {"text": "保单号: POL002"}},
    {"type": "HintText", "data": {"text": "保单年度: 第3年"}},
    {"type": "Divider"},
    {"type": "KVRow", "data": {"label": "生存金", "value": {"get": "options[0].survival_fund_amt", "format": "currency"}}},
    {"type": "KVRow", "data": {"label": "红利", "value": {"get": "options[0].bonus_amt", "format": "currency"}}},
    {"type": "KVRow", "data": {"label": "可贷额度", "value": {"get": "options[0].loan_amt", "format": "currency"}}},
    {"type": "KVRow", "data": {"label": "退保金", "value": {"get": "options[0].refund_amt", "format": "currency"}}},
    {"type": "Divider"},
    {"type": "AccentTotal", "data": {"label": "合计可用", "value": {"get": "options[0].available_amount", "format": "currency"}}}
  ]}},
  {"type": "Card", "data": {"children": [
    {"type": "SectionHeader", "data": {"title": "鑫享人生保险"}},
    {"type": "HintText", "data": {"text": "保单号: POL003"}},
    {"type": "HintText", "data": {"text": "保单年度: 第8年"}},
    {"type": "Divider"},
    {"type": "KVRow", "data": {"label": "生存金", "value": {"get": "options[1].survival_fund_amt", "format": "currency"}}},
    {"type": "KVRow", "data": {"label": "红利", "value": {"get": "options[1].bonus_amt", "format": "currency"}}},
    {"type": "Divider"},
    {"type": "AccentTotal", "data": {"label": "合计可用", "value": {"get": "options[1].available_amount", "format": "currency"}}}
  ]}}
]
```

### 动态控制示例

| 用户说 | 调整 |
|-------|------|
| "不要显示可贷额度" | 省略 `loan_amt` 的 KVRow |
| "只看保单POL001" | 只输出 POL001 对应的 Card |
| "不要退保金" | 省略 `refund_amt` 的 KVRow |

### Card 内 block 使用规则

- `SectionHeader`: 保单名称（必须）
- `HintText`: 保单号、年度等元信息
- `KVRow`: 各项金额明细（label + value）
- `AccentTotal`: 合计行（高亮橙色）
- `Divider`: 分隔线
- 金额必须通过 Transform DSL 获取，禁止硬编码数字

### 卡片发出后的文字

卡片已完整展示保单信息。**禁止**在文字中重复保单名称、金额、保单号等任何卡片内容。仅允许 1 句引导（≤25字），示例：
- "以上是您的保单概况，有什么想了解的吗？"
- "如需办理取款，请告诉我金额。"

### 生成规则

- 保单为 0 张时，只出 1 句文字说明无有效保单。
- Card 数量 = 保单数量。

### 数据字段参考（rule_engine list_options 返回）

```json
{
  "options": [
    {
      "policy_id": "POL001",
      "product_name": "平安福终身寿险",
      "product_type": "whole_life",
      "policy_year": 5,
      "available_amount": 75600,
      "survival_fund_amt": 0,
      "bonus_amt": 0,
      "loan_amt": 33600,
      "refund_amt": 42000
    }
  ],
  "total_count": 3
}
```

金额字段含义：`survival_fund_amt`(生存金) / `bonus_amt`(红利) / `loan_amt`(可贷款) / `refund_amt`(退保/部分领取)

---

## 附录：Transform DSL 与数字安全规则

### Transform DSL

block data 的值可以是纯字符串/数字（直接使用），也可以是 Transform spec 对象（运行时求值）：

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

### Action 格式

```json
{"name": "query", "args": {"queryMsg": "用户点击后发送的文本"}}
```

### 数字安全规则

1. Fine Blocks 中 **所有金额/利率/数量** 必须通过 Transform DSL 获取
2. **禁止**在 blocks 的 data 中硬编码任何数字
3. 文案中的数字用 `concat` + `get` + `format` 组合
4. Components 内部自动计算，LLM 不需要传递金额值

**错误示例** ✗
```json
{"type": "KVRow", "data": {"label": "生存金", "value": "¥ 12,000.00"}}
```

**正确示例** ✓
```json
{"type": "KVRow", "data": {"label": "生存金", "value": {"get": "options[0].survival_fund_amt", "format": "currency"}}}
```
