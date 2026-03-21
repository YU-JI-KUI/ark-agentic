---
name: 信息查询
description: 查询并展示用户个人信息或保单列表，以 A2UI 卡片呈现。
version: "3.0.0"
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

客户档案展示：名字为 Hero 元素，关键信息以 KV 列表呈现，家庭成员用 SectionCard。

### 执行流程

```
customer_info(info_type="full", user_id=用户ID)
→ render_a2ui(blocks=...)
```

### 完整示例

```
render_a2ui(
  blocks=[
    {"type": "SummaryHeader", "data": {"title": {"literal": "客户档案"}, "value": {"get": "identity.name"}}},
    {"type": "KeyValueList", "data": {
      "rowCount": 9, "rowPrefix": "row",
      "row1_label": {"literal": "证件类型"}, "row1_value": {"get": "identity.id_type"},
      "row2_label": {"literal": "证件号码"}, "row2_value": {"get": "identity.id_number"},
      "row3_label": {"literal": "性别"}, "row3_value": {"get": "identity.gender"},
      "row4_label": {"literal": "出生日期"}, "row4_value": {"get": "identity.birth_date"},
      "row5_label": {"literal": "年龄"}, "row5_value": {"concat": [{"get": "identity.age"}, "岁"]},
      "row6_label": {"literal": "婚姻状况"}, "row6_value": {"get": "identity.marital_status"},
      "row7_label": {"literal": "风险偏好"}, "row7_value": {"literal": "保守型"},
      "row8_label": {"literal": "联系电话"}, "row8_value": {"get": "contact.phone"},
      "row9_label": {"literal": "邮箱"}, "row9_value": {"get": "contact.email"}
    }},
    {"type": "SectionCard", "data": {"title": {"literal": "家庭成员"}, "tag": {"literal": "2人"}, "total": "", "items": {"literal": [
      {"label": "配偶", "value": "李芳"},
      {"label": "子女", "value": "张小明"}
    ]}}}
  ]
)
```

### 数据字段参考（customer_info full，与 data_service mock 一致）

**identity**：name, id_type, id_number, gender, birth_date, age, has_children, marital_status, verified, verification_date  
**contact**：phone, email, address, preferred_contact, contact_time_preference  

卡片展示时从 identity / contact 用 get 取上述字段，勿编造字段名。

---

## Case 2：保单列表

使用预制模板渲染保单详情卡片，无需手动构造 SectionCard。

### 执行流程

```
rule_engine(action="list_options", user_id=用户ID)
→ render_a2ui(card_type="policy_detail")
```

`policy_detail` 模板自动从 `rule_engine` 返回的数据中提取每张保单的名称、保单号、年度、各项金额明细，以 List 组件渲染。

### card_args（可选）

- `policy_ids: list[str]` — 仅展示指定保单（不传则展示全部）

#### 示例

| 用户说 | render_a2ui 调用 |
|-------|-----------------|
| "我的保单" / "保单列表" | `render_a2ui(card_type="policy_detail")` |
| "看看POL001" | `render_a2ui(card_type="policy_detail", card_args='{"policy_ids":["POL001"]}')` |
| "POL001和POL002的详情" | `render_a2ui(card_type="policy_detail", card_args='{"policy_ids":["POL001","POL002"]}')` |

### 卡片发出后的文字

卡片已完整展示保单信息。**禁止**在文字中重复保单名称、金额、保单号等任何卡片内容。仅允许 1 句引导（≤25字），示例：
- "以上是您的保单概况，有什么想了解的吗？"
- "如需办理取款，请告诉我金额。"

### 生成规则

- 保单为 0 张时，只出 1 句文字说明无有效保单。

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
