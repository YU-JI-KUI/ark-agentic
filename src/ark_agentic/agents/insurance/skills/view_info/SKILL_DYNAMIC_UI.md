---
name: 信息查询
description: 查询并展示用户个人信息或保单列表，以 A2UI 卡片呈现。
version: "2.0.0"
invocation_policy: auto
group: insurance
tags:
  - query
  - info
  - policy
required_tools:
  - customer_info
  - policy_query
  - render_a2ui
---

# 信息查询技能

当用户询问个人信息或保单情况时，调用对应数据工具获取数据，然后通过 `render_a2ui` 以卡片展示。

## 触发条件

- "我的信息" / "个人信息" / "查看我的资料" → Case 1
- "我的保单" / "有什么保单" / "保单列表" / "我买了什么保险" → Case 2

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
→ render_a2ui(blocks=..., transforms=...)
```

### 完整示例

```
render_a2ui(
  blocks=[
    {"type": "SummaryHeader", "data": {"title": "$header_title", "value": "$name"}},
    {"type": "KeyValueList", "data": {"rowCount": 9, "rowPrefix": "row"}},
    {"type": "SectionCard", "data": {"title": "$family_title", "tag": "$family_tag", "total": "", "items": "$family_items"}}
  ],
  transforms={
    "header_title": {"literal": "客户档案"},
    "name": {"get": "identity.name"},
    "row1_label": {"literal": "证件类型"},
    "row1_value": {"get": "identity.id_type"},
    "row2_label": {"literal": "证件号码"},
    "row2_value": {"get": "identity.id_number"},
    "row3_label": {"literal": "性别"},
    "row3_value": {"get": "identity.gender"},
    "row4_label": {"literal": "出生日期"},
    "row4_value": {"get": "identity.birth_date"},
    "row5_label": {"literal": "年龄"},
    "row5_value": {"concat": [{"get": "identity.age"}, "岁"]},
    "row6_label": {"literal": "婚姻状况"},
    "row6_value": {"get": "identity.marital_status"},
    "row7_label": {"literal": "风险偏好"},
    "row7_value": {"literal": "保守型"},
    "row8_label": {"literal": "联系电话"},
    "row8_value": {"get": "contact.phone"},
    "row9_label": {"literal": "邮箱"},
    "row9_value": {"get": "contact.email"},
    "family_title": {"literal": "家庭成员"},
    "family_tag": {"literal": "2人"},
    "family_items": {"literal": [
      {"label": "配偶", "value": "李芳"},
      {"label": "子女", "value": "张小明"}
    ]}
  }
)
```

### 数据字段参考（customer_info full，与 data_service mock 一致）

**identity**：name, id_type, id_number, gender, birth_date, age, has_children, marital_status, verified, verification_date  
**contact**：phone, email, address, preferred_contact, contact_time_preference  

卡片展示时从 identity / contact 用 get 取上述字段，勿编造字段名。

---

## Case 2：保单列表

每张保单用一个 `SectionCard`（Title=产品名, Tag=保单号, Total=可用总额, Items=四类金额明细）。LLM 必须根据 `policyAssertList` 数组长度，为**每张保单**生成一个独立的 `SectionCard` 块。

### 执行流程

```
policy_query(user_id=用户ID, query_type="list")
→ render_a2ui(blocks=..., transforms=...)
```

### 完整示例（3 张保单 → 3 个 SectionCard）

```
render_a2ui(
  blocks=[
    {"type": "SummaryHeader", "data": {"title": "$header_title", "value": "$count_text"}},
    {"type": "SectionCard", "data": {"title": "$p1_name", "tag": "$p1_id", "total": "$p1_total", "items": "$p1_items"}},
    {"type": "SectionCard", "data": {"title": "$p2_name", "tag": "$p2_id", "total": "$p2_total", "items": "$p2_items"}},
    {"type": "SectionCard", "data": {"title": "$p3_name", "tag": "$p3_id", "total": "$p3_total", "items": "$p3_items"}},
    {"type": "AdviceCard", "data": {"icon": "📋", "title": "$advice_title", "texts": ["$advice_1", "$advice_2"]}}
  ],
  transforms={
    "header_title": {"literal": "保单概览"},
    "count_text": {"concat": ["共 ", {"get": "total_count"}, " 张有效保单"]},
    "p1_name": {"get": "policyAssertList[0].product_name"},
    "p1_id": {"get": "policyAssertList[0].policy_id"},
    "p1_total": {"concat": ["可用总额 ", {"sum": ["policyAssertList[0].survivalFundAmt", "policyAssertList[0].bounusAmt", "policyAssertList[0].loanAmt", "policyAssertList[0].policyRefundAmount"], "format": "currency"}]},
    "p1_items": {"literal": [
      {"label": "生存金", "value": "$p1_survival"},
      {"label": "红利", "value": "$p1_bonus"},
      {"label": "可贷款", "value": "$p1_loan"},
      {"label": "退保/部分领取", "value": "$p1_refund"}
    ]},
    "p1_survival": {"get": "policyAssertList[0].survivalFundAmt", "format": "currency"},
    "p1_bonus": {"get": "policyAssertList[0].bounusAmt", "format": "currency"},
    "p1_loan": {"get": "policyAssertList[0].loanAmt", "format": "currency"},
    "p1_refund": {"get": "policyAssertList[0].policyRefundAmount", "format": "currency"},

    "p2_name": {"get": "policyAssertList[1].product_name"},
    "p2_id": {"get": "policyAssertList[1].policy_id"},
    "p2_total": {"concat": ["可用总额 ", {"sum": ["policyAssertList[1].survivalFundAmt", "policyAssertList[1].bounusAmt", "policyAssertList[1].loanAmt", "policyAssertList[1].policyRefundAmount"], "format": "currency"}]},
    "p2_items": {"literal": [
      {"label": "生存金", "value": "$p2_survival"},
      {"label": "红利", "value": "$p2_bonus"},
      {"label": "可贷款", "value": "$p2_loan"},
      {"label": "退保/部分领取", "value": "$p2_refund"}
    ]},
    "p2_survival": {"get": "policyAssertList[1].survivalFundAmt", "format": "currency"},
    "p2_bonus": {"get": "policyAssertList[1].bounusAmt", "format": "currency"},
    "p2_loan": {"get": "policyAssertList[1].loanAmt", "format": "currency"},
    "p2_refund": {"get": "policyAssertList[1].policyRefundAmount", "format": "currency"},

    "p3_name": {"get": "policyAssertList[2].product_name"},
    "p3_id": {"get": "policyAssertList[2].policy_id"},
    "p3_total": {"concat": ["可用总额 ", {"sum": ["policyAssertList[2].survivalFundAmt", "policyAssertList[2].bounusAmt", "policyAssertList[2].loanAmt", "policyAssertList[2].policyRefundAmount"], "format": "currency"}]},
    "p3_items": {"literal": [
      {"label": "生存金", "value": "$p3_survival"},
      {"label": "红利", "value": "$p3_bonus"},
      {"label": "可贷款", "value": "$p3_loan"},
      {"label": "退保/部分领取", "value": "$p3_refund"}
    ]},
    "p3_survival": {"get": "policyAssertList[2].survivalFundAmt", "format": "currency"},
    "p3_bonus": {"get": "policyAssertList[2].bounusAmt", "format": "currency"},
    "p3_loan": {"get": "policyAssertList[2].loanAmt", "format": "currency"},
    "p3_refund": {"get": "policyAssertList[2].policyRefundAmount", "format": "currency"},

    "advice_title": {"literal": "温馨提示"},
    "advice_1": {"literal": "• 所有保单均为有效状态，保障持续中"},
    "advice_2": {"literal": "• 如需取款或了解具体保障内容，可随时咨询"}
  }
)
```

### 生成规则

- **SectionCard 数量 = policyAssertList 长度**，不得多于也不得少于实际保单数。
- 每个 SectionCard 的 `items` 必须包含四类金额明细（生存金 / 红利 / 可贷款 / 退保或部分领取），金额通过 transforms 的 `get` + `format: "currency"` 获取。
- 保单为 0 张时，只出 SummaryHeader + AdviceCard（说明无有效保单）。

### 数据字段参考（policy_query list 返回）

```json
{
  "policyAssertList": [
    {
      "policy_id": "POL001",
      "product_name": "平安福终身寿险",
      "product_type": "whole_life",
      "status": "active",
      "effective_date": "2019-03-15",
      "premium": 12000,
      "payment_years": 20,
      "paid_years": 5,
      "sum_insured": 500000,
      "account_value": 0,
      "bounusAmt": 0,
      "loanAmt": 33600,
      "survivalFundAmt": 0,
      "policyRefundAmount": 42000
    }
  ],
  "total_count": 3
}
```

金额字段含义：`survivalFundAmt`(生存金) / `bounusAmt`(红利) / `loanAmt`(可贷款) / `policyRefundAmount`(退保/部分领取)

## 数字安全规则

- 所有金额必须通过 transforms 的 `get` + `format: "currency"` 获取
- 禁止在 blocks 的 data 中硬编码任何数字
