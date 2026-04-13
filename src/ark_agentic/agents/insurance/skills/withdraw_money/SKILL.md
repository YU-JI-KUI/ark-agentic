---
name: 保险取款
description: 查询可取金额总览、生成取款方案、调整已有方案，均以 A2UI 卡片展示。用户表达取款意图（无论是否给出金额）均由本技能处理。
version: "12.0.0"
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

处理所有与取款相关的用户请求：总览查询、方案生成、方案调整。使用三步流水线：**意图分类 → 参数提取 → 渲染**。

> **所有数据展示必须调用 `render_a2ui`，详见末尾「输出约束」。**

---

## 触发 / 不触发

**触发**：用户表达了与取款相关的咨询、方案生成、方案调整意图。

**不触发**（由「取款执行」技能处理）：

- 对话中已展示过 PlanCard，且用户表达了确认/选择/办理意图
- "办理方案1"、"就第一个"、"确认"、"办理"
- "领生存金"（当对话中已有包含 survival_fund 的 PlanCard 时）

**当「取款执行」不适用时自动接管**：

「取款执行」因前置条件不满足（无 PlanCard 或渠道不匹配）时，本技能自动接管，走 PLAN 意图生成新 PlanCard。

---

## STEP 1 — 意图分类（3 选 1）

| 意图 | 判断依据 |
|------|---------|
| **OVERVIEW** | 咨询类。标志："能取多少"、"帮我看看"、"有什么可以领的"、"只看零成本"。关键判据：不含"领取/取/办理"**与具体渠道或金额的组合**。疑问句式（"能取多少"）属 OVERVIEW，即使含"取"字。可带渠道筛选（"只看零成本"→ channels=[survival_fund,bonus]），因为是"看"不是"领" |
| **PLAN** | 行动类，以下任一满足：(a) 有具体金额 (b) 有具体渠道 + "领取/取/办理"等行动动词 (c) 已展示 Summary 且用户选择了具体渠道/金额 |
| **ADJUST** | 修改类，**前提**：对话中已展示 PlanCard。标志词："不要X"、"少取"、"多取"、"换个方案"、"只用零成本"。前提不满足时**降级为 PLAN** |

### 上下文规则

- Summary 已展示 → 后续任何包含渠道/金额的消息，意图判为 **PLAN**（不再出 Summary）
- PlanCard 已展示 → 包含"调整"语义 → **ADJUST**；包含新渠道/新金额 → **PLAN**（重新生成方案）
- "领取"是行动信号：包含"领取/取/办理"+ 渠道名 → **PLAN** 而非 OVERVIEW

---

## STEP 2 — 参数提取

从用户消息中提取（未提及留 null）：

| 参数 | 类型 | 说明 |
|------|------|------|
| target_amount | number / null | 目标金额，null = 取全部可用 |
| channels | list / null | 用户指定的渠道 |
| exclude_channels | list / null | 用户排除的渠道 |
| exclude_policies | list / null | 用户排除的保单 |

### 渠道 ID 参考

| 用户说法 | 渠道 ID |
|---------|---------|
| 生存金 | `survival_fund` |
| 红利 | `bonus` |
| 贷款 | `policy_loan` |
| 部分领取 | `partial_withdrawal` |
| 退保 | `surrender` |
| 零成本 / 不影响保障的 | `survival_fund` + `bonus` |

### 金额校验

target_amount 为负数 → 直接回复"取款金额需要为正数"，不调工具。

---

## STEP 3 — 执行流程 + 渲染

所有意图都先确保 rule_engine 数据可用：

```
customer_info(info_type="identity", user_id=用户ID)  -- 仅首次
rule_engine(action="list_options", user_id=用户ID, amount=target_amount)
```

### OVERVIEW 渲染

```json
[
  {"type": "WithdrawSummaryHeader", "data": {"sections": ["zero_cost", "loan", "partial_surrender"]}},
  {"type": "WithdrawSummarySection", "data": {"section": "zero_cost"}},
  {"type": "WithdrawSummarySection", "data": {"section": "loan"}},
  {"type": "WithdrawSummarySection", "data": {"section": "partial_surrender"}}
]
```

**sections 推导**：

- channels 为 null → 全部: `["zero_cost", "loan", "partial_surrender"]`
- channels 含 survival_fund 或 bonus → 含 `"zero_cost"`
- channels 含 policy_loan → 含 `"loan"`
- channels 含 partial_withdrawal 或 surrender → 含 `"partial_surrender"`
- exclude_channels 对应的 section 从列表中移除

空数据的 section 自动返回空（不显示）。

**筛选示例**（"只看零成本"）：

```json
[
  {"type": "WithdrawSummaryHeader", "data": {"sections": ["zero_cost"]}},
  {"type": "WithdrawSummarySection", "data": {"section": "zero_cost"}}
]
```

#### Section 预设

| section | 包含渠道 | 标签 |
|---------|---------|------|
| `zero_cost` | survival_fund, bonus | 不影响保障 |
| `loan` | policy_loan | 需支付利息 |
| `partial_surrender` | partial_withdrawal, surrender | 保障有损失，不建议 |

### PLAN 渲染

生成 1-3 个 PlanCard：

```json
[
  {"type": "WithdrawPlanCard", "data": {
    "channels": ["survival_fund", "bonus"],
    "target": 50000,
    "title": "★ 推荐: 零成本领取",
    "tag": "(不影响保障)",
    "reason": "零成本、无风险，不影响您的保障"
  }}
]
```

**channels 推导**：

- channels 不为 null → 直接使用
- channels 为 null + exclude_channels 不为 null → 全渠道去掉 exclude_channels
- 都为 null → 按优先级 `["survival_fund", "bonus", "partial_withdrawal", "policy_loan", "surrender"]`

**title/tag 规则**：

- 纯零成本渠道 → "★ 推荐: 零成本领取" + "(不影响保障)"
- 含贷款 → "(部分需付利息)"
- 含退保 → "(保障有损失)"
- 单渠道 → 直接用渠道中文名

**多方案策略**：

- 推荐方案只用一个类别且其他类别也够 target → 生成备选方案（最多 3 个）
- target > 全部可用 → 只出一个"最大可取"方案
- target = 0（渠道定向）→ 出该渠道全部可用额度的单方案

**渠道优先级（从高到低）**：

1. **生存金 + 红利** → 零成本，不影响保障
2. **部分领取**（非 whole_life 的 refund_amt）→ 低成本
3. **保单贷款** → 年利率 5%，保障不受影响
4. **退保**（whole_life 的 refund_amt）→ 保障终止，最后手段

#### 示例 1：单类别足够（零成本 >= 目标金额）

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

#### 示例 2：需组合（目标 30000，零成本仅 20000）

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

组合方案的 `target` = 用户完整目标金额，单类别参考方案的 `target` = 该类别实际最大可取额。

#### 示例 3：渠道定向（"领取生存金"，无金额）

```json
[
  {"type": "WithdrawPlanCard", "data": {
    "channels": ["survival_fund"],
    "target": 0,
    "title": "生存金领取",
    "tag": "(不影响保障)",
    "reason": "为您领取全部可用生存金"
  }}
]
```

`target=0` 表示取该渠道全部可用额度。

### ADJUST 渲染

从对话历史中上一轮 PlanCard 的 digest 读取当前参数（`channels: [...]`、`总额: ¥...`），合并本轮变更（如"不要贷款" → 从 channels 中移除 policy_loan），然后重新 `rule_engine(list_options)` + `render_a2ui`。

如需单保单精算，可额外调用 `rule_engine(action="calculate_detail", ...)`，但非必须。

**调整方式参考**：

| 用户说 | 调整 |
|--------|------|
| "多取一点，总共8万" | target → 80000 |
| "不要贷款" | channels 中移除 policy_loan |
| "不退保" | channels 中移除 surrender |
| "只用不影响保障的" | channels → ["survival_fund","bonus"] |
| "不要POL002" | exclude_policies → ["POL002"] |

---

## 可用 Component 类型

| 类型 | 用途 | data |
|------|------|------|
| `WithdrawSummaryHeader` | 总览头部（总金额） | `{"sections": [...]}` |
| `WithdrawSummarySection` | 总览分组（零成本/贷款/退保） | `{"section": "preset_name"}` |
| `WithdrawPlanCard` | 取款方案卡 | `{"channels": [...], "target": N, "title": "...", "tag"?: "...", "reason"?: "...", "tag_color"?: "...", "button_variant"?: "primary/secondary", "exclude_policies"?: [...]}` |

Component 内部自动从 context 读取 `rule_engine` 数据并计算金额，LLM 无需硬编码数字。

---

## 注意事项

1. 始终优先推荐零成本、不影响保障的渠道
2. 金额计算由 component 内部完成，LLM 只控制 component 选择和 data 参数
3. `product_type=whole_life` 的 refund_amt 为退保（保障终止），其他为部分领取

## 输出约束（最高优先级）

1. **必须**：每次展示取款数据时调用 `render_a2ui`。严禁用 Markdown 表格、列表或纯文本替代。如果你准备写表格或列表来展示数据——停下来，改为调用 `render_a2ui`。
2. **回退/引用/重复方案也必须重新出卡片**：用户说"还是第一个方案"、"回到之前的"等，必须重新 `rule_engine` + `render_a2ui`，禁止从对话记忆中复述。
3. **禁止**：在文字回复中重复卡片已展示的金额、渠道名称或保单号。卡片后仅 1 句引导（≤25字）。
4. 违反以上任一条等同于任务失败。
