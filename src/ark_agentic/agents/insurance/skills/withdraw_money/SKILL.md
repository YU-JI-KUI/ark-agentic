---
name: 保险取款
description: 查询可取金额总览、生成取款方案、调整已有方案，均以 A2UI 卡片展示。
version: "9.0.0"
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

## 渠道 ID 参考

card_args 中 `exclude_channels` / `include_channels` 使用以下渠道 ID：

| 用户说法 | 渠道 ID |
|---------|---------|
| 生存金 | `survival_fund` |
| 红利 | `bonus` |
| 贷款 | `policy_loan` |
| 部分领取 | `partial_withdrawal` |
| 退保 | `surrender` |

---

## Case A：总览（无具体金额）

用户想知道"一共能取多少钱"，不需要具体方案。使用预制模板展示总览卡片。

### 执行流程

```
rule_engine(action="list_options", user_id=用户ID)
→ render_a2ui(card_type="withdraw_summary")
```

模板自动按渠道分组（零成本/贷款/退保），计算合计金额，无数据的渠道自动隐藏。

### 筛选（可选）

用户可能要求排除某些渠道或保单，通过 `card_args` 传递：

| 用户说 | card_args |
|-------|-----------|
| "不算贷款能取多少" | `{"exclude_channels": ["policy_loan"]}` |
| "不算POL003能取多少" | `{"exclude_policies": ["POL003"]}` |
| "只看零成本的" | `{"include_channels": ["survival_fund", "bonus"]}` |

---

## Case B：具体方案（有明确金额）

用户明确取款金额，生成最多 3 个方案卡，按成本从低到高排列。使用预制模板展示。

### 执行流程

```
customer_info(info_type="identity", user_id=用户ID)
→ rule_engine(action="list_options", user_id=用户ID, amount=金额)
→ render_a2ui(card_type="withdraw_plan")
```

模板自动按渠道优先级生成方案（零成本 → 部分领取 → 贷款 → 退保），计算分配金额，生成操作按钮。

### 渠道优先级（从高到低）

1. **生存金 + 红利** → 零成本，不影响保障
2. **部分领取**（非 whole_life 的 refund_amt）→ 低成本
3. **保单贷款** → 年利率 5%，保障不受影响
4. **退保**（whole_life 的 refund_amt）→ 保障终止，最后手段

### 金额不足处理

当 `total_available_incl_loan` < 用户期望金额时，模板自动展示最大可取方案。LLM 在文字回复中说明差额。

---

## Case C：方案调整

用户对已有推荐方案提出修改。**前提**：本轮对话中已展示过 Case A 或 Case B 的方案。

### 调整类型与 card_args

| 用户说 | 处理 |
|-------|------|
| "多取一点，总共8万" | `rule_engine(list_options, amount=新金额)` → `render_a2ui(card_type="withdraw_plan")` |
| "不要贷款" | `rule_engine(list_options, amount=原金额)` → `render_a2ui(card_type="withdraw_plan", card_args='{"exclude_channels":["policy_loan"]}')` |
| "不退保" | `render_a2ui(card_type="withdraw_plan", card_args='{"exclude_channels":["surrender"]}')` |
| "只用不影响保障的" | `render_a2ui(card_type="withdraw_plan", card_args='{"include_channels":["survival_fund","bonus"]}')` |
| "不要POL002" | `render_a2ui(card_type="withdraw_plan", card_args='{"exclude_policies":["POL002"]}')` |
| "多取一点但不要贷款" | `rule_engine(list_options, amount=新金额)` → `render_a2ui(card_type="withdraw_plan", card_args='{"exclude_channels":["policy_loan"]}')` |

### 单项精算

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
- 调整后重新 `list_options` 刷新数据再出卡片

### 回溯之前的方案

用户可能说"用前面那个方案"或"还是第一个方案好"。此时：
1. 从对话历史中找到该方案对应的参数（金额、排除条件）
2. 重新调用 `rule_engine(list_options)` 获取最新数据
3. 用相同的 `card_args` 调用 `render_a2ui(card_type="withdraw_plan")`

---

## 风格要求

- 友好、专业、简洁、通俗
- 对敏感操作（退保）给出清晰风险提示
- 方案展示后必须引导用户确认

## 注意事项

1. 始终优先推荐零成本、不影响保障的渠道
2. 金额计算和格式化由模板提取器完成，LLM 只需调用 `card_type` + 可选 `card_args`
3. `product_type=whole_life` 的 refund_amt 为退保（保障终止），其他为部分领取
