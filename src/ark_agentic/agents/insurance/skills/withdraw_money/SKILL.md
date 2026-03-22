---
name: 保险取款
description: 查询可取金额总览、生成取款方案、调整已有方案，均以 A2UI 卡片展示。
version: "10.0.0"
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

本技能使用 **component 级别**的 blocks 动态组合，LLM 通过选择和组合 component 控制展示内容。

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

| 用户说法 | 渠道 ID |
|---------|---------|
| 生存金 | `survival_fund` |
| 红利 | `bonus` |
| 贷款 | `policy_loan` |
| 部分领取 | `partial_withdrawal` |
| 退保 | `surrender` |

---

## 可用 Component 类型

| 类型 | 用途 | data |
|------|------|------|
| `WithdrawSummaryHeader` | 总览头部（总金额） | `{"sections": [...]}` |
| `WithdrawSummarySection` | 总览分组（零成本/贷款/退保） | `{"section": "preset_name"}` |
| `WithdrawPlanCard` | 取款方案卡 | `{"channels": [...], "target": N, "title": "...", "tag_color"?: "...", "button_variant"?: "primary/secondary"}` |

Component 内部自动从 context 读取 `rule_engine` 数据并计算金额，LLM 无需硬编码数字。

---

## Case A：总览（无具体金额）

用户想知道"一共能取多少钱"，不需要具体方案。

### 执行流程

```
rule_engine(action="list_options", user_id=用户ID)
→ render_a2ui(blocks=...)
```

### 完整示例

```json
[
  {"type": "WithdrawSummaryHeader", "data": {"sections": ["zero_cost", "loan", "partial_surrender"]}},
  {"type": "WithdrawSummarySection", "data": {"section": "zero_cost"}},
  {"type": "WithdrawSummarySection", "data": {"section": "loan"}},
  {"type": "WithdrawSummarySection", "data": {"section": "partial_surrender"}}
]
```

### 动态筛选

| 用户说 | 调整 |
|-------|------|
| "不算贷款能取多少" | 移除 `loan` section + header 中移除 `"loan"` |
| "只看零成本的" | 仅保留 `zero_cost` section 和 header |

示例（不含贷款）：

```json
[
  {"type": "WithdrawSummaryHeader", "data": {"sections": ["zero_cost", "partial_surrender"]}},
  {"type": "WithdrawSummarySection", "data": {"section": "zero_cost"}},
  {"type": "WithdrawSummarySection", "data": {"section": "partial_surrender"}}
]
```

### Section 预设

| section | 包含渠道 | 标签 |
|---------|---------|------|
| `zero_cost` | survival_fund, bonus | 不影响保障 |
| `loan` | policy_loan | 需支付利息 |
| `partial_surrender` | partial_withdrawal, surrender | 保障有损失，不建议 |

无数据的 section 自动返回空（不显示）。

---

## Case B：具体方案（有明确金额）

用户明确取款金额，生成方案卡，按成本从低到高排列。

### 执行流程

```
customer_info(info_type="identity", user_id=用户ID)
→ rule_engine(action="list_options", user_id=用户ID, amount=金额)
→ render_a2ui(blocks=...)
```

### 方案生成策略

1. 先用 `rule_engine` 结果判断各类别渠道合计能否满足目标金额
2. 如果零成本渠道（survival_fund + bonus）足够 → 推荐方案只用零成本
3. 如果零成本不够 → **推荐方案必须组合多类别渠道以满足目标金额**
4. 可选方案二/三展示单类别渠道的最大可取额（作为参考对比）
5. 每个 PlanCard 的 `target` 应设为该方案实际能达到的金额

### 渠道优先级（从高到低）

1. **生存金 + 红利** → 零成本，不影响保障
2. **部分领取**（非 whole_life 的 refund_amt）→ 低成本
3. **保单贷款** → 年利率 5%，保障不受影响
4. **退保**（whole_life 的 refund_amt）→ 保障终止，最后手段

### 示例 1：单类别足够（零成本 >= 目标金额）

```json
[
  {"type": "WithdrawPlanCard", "data": {
    "channels": ["survival_fund", "bonus"],
    "target": 50000,
    "title": "★ 推荐: 零成本领取",
    "tag": "(不影响保障)",
    "reason": "零成本、无风险，不影响您的保障"
  }},
  {"type": "WithdrawPlanCard", "data": {
    "channels": ["policy_loan"],
    "target": 50000,
    "title": "保单贷款",
    "tag": "(需支付利息)",
    "tag_color": "#FA8C16",
    "button_variant": "secondary",
    "reason": "保障不受影响，适合短期周转"
  }}
]
```

### 示例 2：需要组合（目标 30000，零成本仅 20000）

推荐方案应组合渠道以满足目标金额；可用单类别方案作为参考对比。

```json
[
  {"type": "WithdrawPlanCard", "data": {
    "channels": ["survival_fund", "bonus", "policy_loan"],
    "target": 30000,
    "title": "★ 推荐: 零成本 + 保单贷款",
    "tag": "(部分需付利息)",
    "reason": "优先使用零成本渠道；不足部分用保单贷款补足。"
  }},
  {"type": "WithdrawPlanCard", "data": {
    "channels": ["survival_fund", "bonus"],
    "target": 20000,
    "title": "仅零成本（最多 ¥20,000.00）",
    "tag": "(不影响保障)",
    "button_variant": "secondary",
    "reason": "零成本渠道合计 ¥20,000.00，不足目标 ¥30,000.00。"
  }}
]
```

注意：组合方案的 `target` 设为用户的完整目标金额，单类别参考方案的 `target` 设为该类别的实际最大可取额。

---

## Case C：方案调整

用户对已有推荐方案提出修改。**前提**：本轮对话中已展示过 Case A 或 Case B 的方案。

### 调整方式

| 用户说 | 调整 blocks |
|-------|------------|
| "多取一点，总共8万" | 更新 target 为 80000 |
| "不要贷款" | 移除 channels 中 policy_loan 的 PlanCard |
| "不退保" | 移除含 surrender 的 PlanCard |
| "只用不影响保障的" | 仅保留 `["survival_fund","bonus"]` channels |
| "不要POL002" | 添加 `"exclude_policies": ["POL002"]` |

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

---

## 风格要求

- 友好、专业、简洁、通俗
- 对敏感操作（退保）给出清晰风险提示
- 方案展示后必须引导用户确认

## 注意事项

1. 始终优先推荐零成本、不影响保障的渠道
2. 金额计算由 component 内部完成，LLM 只控制 component 选择和 data 参数
3. `product_type=whole_life` 的 refund_amt 为退保（保障终止），其他为部分领取
