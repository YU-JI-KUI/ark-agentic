---
name: 保险取款
description: 查询可取金额总览、生成取款方案、调整已有方案，均以 A2UI 卡片展示。
version: "7.0.0"
invocation_policy: auto
group: insurance
tags:
  - withdrawal
  - insurance
  - financial
required_tools:
  - customer_info
  - rule_engine
  - render_a2ui
---

# 保险取款技能

处理所有与取款相关的用户请求，包括总览查询、具体方案生成、方案调整。

## 触发条件

以下意图触发本技能：
- "能取多少钱" / "可以取多少" / "总共多少钱" → Case A（总览）
- "取5万" / "需要10万" / 带金额的取款需求 → Case B（具体方案）
- "不要贷款" / "换个方案" / "多取一点" → Case C（方案调整，前提是已有推荐方案）

**不触发**：
- "我的保单" / "个人信息" → 由 view_info 处理
- 未明确取款意图的闲聊

## 回复结构

`[1 句引导语] + A2UI 卡片 + [可选 1 句确认引导]`

---

## Case A：总览（无具体金额）

用户想知道"一共能取多少钱"，不需要具体方案。使用 SummaryHeader + 3 个分类 SectionCard 展示。

### 执行流程

```
rule_engine(action="list_options", user_id=用户ID)
→ render_a2ui(blocks=..., transforms=...)
```

### 卡片结构

1. **SummaryHeader** — 总可领金额 + 不含贷款金额
2. **SectionCard「零成本领取」** — 生存金 + 红利，不影响保障（无此类保单则**省略此块**）
3. **SectionCard「保单贷款」** — 可贷额度 + 利率说明（无可贷保单则**省略此块**）
4. **SectionCard「退保/部分领取」** — 退保或部分领取金额 + 影响说明（无此类保单则**省略此块**）
5. **AdviceCard** — 建议
6. **ActionButton** — "获取最优方案"

### 完整示例

以下示例基于 3 张保单。LLM 必须根据 `options` 数组中各字段的实际值决定哪些 SectionCard 需要生成。

```
render_a2ui(
  blocks=[
    {"type": "SummaryHeader", "data": {"title": "$header_title", "value": "$header_value", "subtitle": "$header_sub", "note": "$requested_note"}},
    {"type": "SectionCard", "data": {"title": "$zero_title", "tag": "$zero_tag", "total": "$zero_total", "items": "$zero_items"}},
    {"type": "SectionCard", "data": {"title": "$loan_title", "tag": "$loan_tag", "total": "$loan_total", "items": "$loan_items"}},
    {"type": "SectionCard", "data": {"title": "$impact_title", "tag": "$impact_tag", "total": "$impact_total", "items": "$impact_items"}},
    {"type": "AdviceCard", "data": {"icon": "💡", "title": "$advice_title", "texts": ["$advice_1", "$advice_2"]}},
    {"type": "ActionButton", "data": {"text": "$btn_text", "action": {"name": "query", "args": "$btn_args"}}}
  ],
  transforms={
    "header_title": {"literal": "目前可领取的总金额(含贷款)"},
    "header_value": {"get": "total_available_incl_loan", "format": "currency"},
    "header_sub": {"concat": ["不含贷款可领金额：", {"get": "total_available_excl_loan", "format": "currency"}]},
    "requested_note": {"literal": "本次取款目标：未指定"},

    "zero_title": {"literal": "零成本领取"},
    "zero_tag": {"literal": "不影响保障"},
    "zero_total": {"concat": ["合计：", {"sum": ["options.survival_fund_amt", "options.bonus_amt"], "format": "currency"}]},
    "zero_items": {
      "select": "options",
      "where": {"or": [{"survival_fund_amt": "> 0"}, {"bonus_amt": "> 0"}]},
      "map": {
        "label": {"concat": [{"get": "$.policy_id"}, " ", {"get": "$.product_name"}, " 生存金+红利"]},
        "value": {"concat": [{"get": "$.survival_fund_amt", "format": "currency"}, " + ", {"get": "$.bonus_amt", "format": "currency"}]}
      }
    },

    "loan_title": {"literal": "保单贷款"},
    "loan_tag": {"literal": "需支付利息"},
    "loan_total": {"concat": ["合计可贷：", {"sum": "options.loan_amt", "where": {"loan_amt": "> 0"}, "format": "currency"}]},
    "loan_items": {
      "select": "options",
      "where": {"loan_amt": "> 0"},
      "map": {
        "label": {"concat": [{"get": "$.policy_id"}, " ", {"get": "$.product_name"}, " 可贷(年利率5%)"]},
        "value": {"get": "$.loan_amt", "format": "currency"}
      }
    },

    "impact_title": {"literal": "退保/部分领取"},
    "impact_tag": {"literal": "影响保障"},
    "impact_total": {"concat": ["合计：", {"sum": "options.refund_amt", "where": {"refund_amt": "> 0"}, "format": "currency"}]},
    "impact_items": {
      "select": "options",
      "where": {"refund_amt": "> 0"},
      "map": {
        "label": {"concat": [{"get": "$.policy_id"}, " ", {"get": "$.product_name"}, " ",
          {"switch": "$.product_type", "cases": {"whole_life": "退保(保障终止)"}, "default": "部分领取"}
        ]},
        "value": {"get": "$.refund_amt", "format": "currency"}
      }
    },

    "advice_title": {"literal": "建议方案"},
    "advice_1": {"literal": "• 如需资金，建议优先领取生存金，零成本、无影响、最快到账。"},
    "advice_2": {"literal": "• 如需更多资金，可组合使用 生存金 + 保单贷款，不影响您的保障。"},
    "btn_text": {"literal": "获取最优方案"},
    "btn_args": {"literal": {"queryMsg": "获取最优方案"}}
  }
)
```

### 空 Section 处理

当某类渠道没有符合条件的保单时（如所有保单 `loan_amt = 0`），**LLM 应省略对应的 SectionCard 块**，不要生成空的 SectionCard。

### 数据字段参考（rule_engine list_options 返回）

```json
{
  "requested_amount": null,
  "total_available_excl_loan": 219200,
  "total_available_incl_loan": 337800,
  "options": [
    {
      "policy_id": "POL002",
      "product_name": "金瑞人生年金险",
      "product_type": "annuity",
      "available_amount": 177200,
      "survival_fund_amt": 12000,
      "bonus_amt": 5200,
      "loan_amt": 0,
      "refund_amt": 160000,
      "refund_fee_rate": 0.01,
      "loan_interest_rate": null,
      "processing_time": "1-3个工作日"
    }
  ]
}
```

---

## Case B：具体方案（有明确金额）

用户明确取款金额，生成 **2-3 个方案卡**（每个方案一个 `SectionCard` + `ActionButton` 对），按成本从低到高排列。**最多 3 个方案**。

### 执行流程

```
customer_info(info_type="identity", user_id=用户ID)
→ rule_engine(action="list_options", user_id=用户ID, amount=金额)
→ render_a2ui(blocks=..., transforms=...)
```

### 渠道优先级（从高到低）

1. **生存金 + 红利** → 零成本，不影响保障
2. **部分领取**（非 whole_life 的 refund_amt）→ 低成本
3. **保单贷款** → 年利率 5%，保障不受影响
4. **退保**（whole_life 的 refund_amt）→ 保障终止，最后手段

### 卡片结构

1. **SummaryHeader** — 本次取款目标 + 总可用金额
2. **方案卡 × N（最多 3 个）**，每个方案由以下两块组成：
   - **SectionCard** — 方案名称 + 方案总额 + 涉及的保单和渠道明细
   - **ActionButton** — "一键领取 (方案X)"
3. **AdviceCard** — 推荐理由和风险说明

### 完整示例（2 个方案）

```
render_a2ui(
  blocks=[
    {"type": "SummaryHeader", "data": {"title": "$header_title", "value": "$requested_display", "subtitle": "$header_sub"}},
    {"type": "SectionCard", "data": {"title": "$plan1_title", "tag": "$plan1_tag", "total": "$plan1_total", "items": "$plan1_items"}},
    {"type": "ActionButton", "data": {"text": "$plan1_btn", "action": {"name": "query", "args": "$plan1_action"}}},
    {"type": "SectionCard", "data": {"title": "$plan2_title", "tag": "$plan2_tag", "total": "$plan2_total", "items": "$plan2_items"}},
    {"type": "ActionButton", "data": {"text": "$plan2_btn", "action": {"name": "query", "args": "$plan2_action"}}},
    {"type": "AdviceCard", "data": {"icon": "💡", "title": "$advice_title", "texts": ["$advice_1", "$advice_2"]}}
  ],
  transforms={
    "header_title": {"literal": "本次取款目标"},
    "requested_display": {"get": "requested_amount", "format": "currency"},
    "header_sub": {"concat": ["总可用金额：", {"get": "total_available_incl_loan", "format": "currency"}]},

    "plan1_title": {"literal": "方案一 ⭐ 推荐"},
    "plan1_tag": {"literal": "零成本"},
    "plan1_total": {"literal": "以下为 LLM 根据渠道优先级组合计算的金额"},
    "plan1_items": {"literal": [
      {"label": "POL002 金瑞人生年金险 · 生存金", "value": "$plan1_item1_val"},
      {"label": "POL002 金瑞人生年金险 · 红利", "value": "$plan1_item2_val"}
    ]},
    "plan1_item1_val": {"literal": "¥ 12,000.00"},
    "plan1_item2_val": {"literal": "¥ 5,200.00"},
    "plan1_btn": {"literal": "一键领取 (方案一)"},
    "plan1_action": {"literal": {"queryMsg": "确认方案一：领取生存金+红利"}},

    "plan2_title": {"literal": "方案二"},
    "plan2_tag": {"literal": "含贷款"},
    "plan2_total": {"literal": "以下为 LLM 根据渠道优先级组合计算的金额"},
    "plan2_items": {"literal": [
      {"label": "POL002 金瑞人生年金险 · 生存金", "value": "$plan2_item1_val"},
      {"label": "POL002 金瑞人生年金险 · 红利", "value": "$plan2_item2_val"},
      {"label": "POL001 平安福终身寿险 · 贷款(年利率5%)", "value": "$plan2_item3_val"}
    ]},
    "plan2_item1_val": {"literal": "¥ 12,000.00"},
    "plan2_item2_val": {"literal": "¥ 5,200.00"},
    "plan2_item3_val": {"literal": "¥ 33,600.00"},
    "plan2_btn": {"literal": "一键领取 (方案二)"},
    "plan2_action": {"literal": {"queryMsg": "确认方案二：领取生存金+红利+贷款"}},

    "advice_title": {"literal": "建议"},
    "advice_1": {"literal": "• ⭐ 推荐方案一：优先领取零成本渠道（生存金、红利），不影响保障。"},
    "advice_2": {"literal": "• 方案二含贷款部分，年利率5%，保障不受影响，但需按期还款。"}
  }
)
```

### 方案生成规则

1. **方案数量**：最少 1 个，最多 3 个。LLM 根据可用渠道和目标金额组合方案。
2. **排序**：按成本/影响从低到高。第一个方案永远是最优推荐（标记 ⭐）。
3. **每个方案的 items**：每一行 = 一个保单 + 一个渠道，格式为 `"{policy_id} {product_name} · {渠道名}"` → `"¥ 金额"`。
4. **金额来自数据**：虽然方案组合由 LLM 决定，每个渠道的金额上限**必须**通过 `get` 从 `options` 数组获取并使用 `format: "currency"`。LLM 可以使用 literal 写入已经从数据中确认过的 currency 格式化金额。
5. **0 个可行方案**：当总可用金额不足以满足用户需求，出 SummaryHeader + AdviceCard（说明差额），不出 SectionCard。

### 金额不足处理

当 `total_available_incl_loan` < 用户期望金额时，展示最大可取方案并用 AdviceCard 说明差额。

---

## Case C：方案调整

用户对已有推荐方案提出修改。**前提**：本轮对话中已展示过 Case B 的方案。

### 调整类型判断

| 用户说 | 类型 | 处理 |
|-------|------|------|
| "多取一点，总共8万" | A 改总额 | `rule_engine(list_options, amount=新金额)` → render_a2ui |
| "不要贷款" / "不退保" | B 排除渠道 | `rule_engine(list_options, amount=原金额)` → 在 blocks 中排除对应 SectionCard |
| "只用不影响保障的" | B 排除渠道 | 只保留 zero_cost SectionCard |
| "POL002 少取点" | C 调单项 | `rule_engine(calculate_detail, policy=..., option_type=..., amount=新金额)` |
| "多取一点但不要贷款" | A+B 混合 | list_options(新金额) → 排除贷款渠道 |

### A/B 类型处理

重新调用 `rule_engine(list_options)` 获取最新数据，按 Case B 同样的方式生成卡片。根据用户约束调整 blocks 中的 SectionCard：
- "不要贷款" → 方案中不使用贷款渠道
- "不要退保" → 方案中排除 whole_life 的 refund_amt
- 在 AdviceCard 中说明与之前方案的差异

### C 类型处理

调用 `calculate_detail` 获取精确计算：

```
rule_engine(
  action="calculate_detail",
  policy={从上文 list_options 中获取该保单数据},
  option_type="对应渠道",
  amount=新金额
)
```

`option_type` 取值：`survival_fund` / `bonus` / `partial_withdrawal` / `surrender` / `policy_loan`

- 若金额超过该渠道上限，calculate_detail 自动按最大额度计算并返回 warning
- 调整后需要重新 `list_options` 刷新数据再出卡片，或仅用 1 句文字说明调整结果

---

## 风格要求

- 友好、专业、简洁、通俗
- 金额通过 transforms 的 currency 格式化，禁止硬编码
- 对敏感操作（退保）给出清晰风险提示
- 方案展示后必须引导用户确认

## 注意事项

1. 始终优先推荐零成本、不影响保障的渠道
2. 每个方案标注关联保单的名称和保单号
3. **只有一个 ⭐ 推荐**
4. **金额硬约束**：每个渠道的取用金额不得超过该渠道数值
5. `product_type=whole_life` 的 refund_amt 为退保（保障终止），其他为部分领取
