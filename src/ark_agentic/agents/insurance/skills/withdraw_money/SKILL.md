---
name: 保险取款
description: 当用户表达取款意图时使用：询问可取金额、查询总览、指定金额/渠道取款、调整已有方案。
version: "15.0.0"
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

<output_constraint>
1. **必须**：每次展示取款数据时调用 `render_a2ui`。严禁用 Markdown 表格、列表或纯文本替代。如果你准备写表格或列表来展示数据——停下来，改为调用 `render_a2ui`。
2. **回退/引用/重复方案也必须重新出卡片**：用户说"还是第一个方案"、"回到之前的"等，必须重新 `rule_engine` + `render_a2ui`，禁止从对话记忆中复述。
3. **禁止**：在文字回复中重复卡片已展示的金额、渠道名称或保单号。卡片后仅 1 句引导（≤25字）。
4. **多个 PlanCard 必须在同一次 `render_a2ui` 调用中生成**（blocks 数组包含多个 WithdrawPlanCard），禁止分多次调用。
5. 违反以上任一条等同于任务失败。
</output_constraint>

三步流水线：**意图分类 → 参数提取 → 渲染**。

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

## STEP 1 — 意图分类

按优先级从高到低检查，命中即停：

| 优先级 | 意图 | 判断条件 | 示例 |
|--------|------|---------|------|
| 1 | **ADJUST** | 对话中已有 PlanCard + 修改语义 | "不要贷款"、"少取"、"多取"、"换方案" |
| 2 | **PLAN** | (a) 有金额 (b) 渠道+行动动词 (c) Summary后选渠道/金额 | "取五万"、"领取生存金"、"办理贷款" |
| 3 | **SUMMARY** | 其余咨询类 | "能取多少"、"帮我看看"、"只看零成本" |

**补充规则**：
- ADJUST 无 PlanCard → 降级为 PLAN
- 疑问句即使含"取"字仍为 SUMMARY（"能取多少" ≠ "领取"）
- SUMMARY 筛选：提取 sections 参数，"只看零成本" → sections=["zero_cost"]

默认：无法判断时走 SUMMARY

---

## STEP 2 — 参数提取

### SUMMARY 参数

从用户消息中提取，未提及留 null：

| 参数 | 类型 | 说明 |
|------|------|------|
| sections | list / null | 要展示的分组，null = 全部 |
| exclude_policies | list / null | 排除的保单 |

**sections 对照**：

| 用户说法 | sections 值 |
|---------|-------------|
| 零成本 / 不影响保障的（生存金+红利合并） | `["zero_cost"]` |
| 只看红利 / 红利有多少 | `["bonus"]` |
| 只看生存金 / 生存金有多少 | `["survival_fund"]` |
| 不看贷款 | `["zero_cost", "partial_withdrawal", "surrender"]` |
| 不看退保 | `["zero_cost", "loan"]` |
| 全部（默认） | `["zero_cost", "loan", "partial_withdrawal", "surrender"]` |

### PLAN / ADJUST 参数

从用户消息中提取，未提及留 null：

| 参数 | 类型 | 说明 |
|------|------|------|
| target | number / null | 目标金额，null = 取全部可用 |
| channels | list / null | 原子渠道 ID 列表（已是最终列表），null = 全渠道 |
| exclude_policies | list / null | 排除的保单 |

> 排除渠道不需要单独参数：直接在 channels 中移除对应 ID。

**渠道 ID 参考**：

| 用户说法 | channels 值 |
|---------|-------------|
| 生存金 | `survival_fund` |
| 红利 | `bonus` |
| 贷款 | `policy_loan` |
| 部分领取 | `partial_withdrawal` |
| 退保 | `surrender` |
| 零成本 / 不影响保障的 | `["survival_fund", "bonus"]` |

### 金额校验

target 为负数 → 直接回复"取款金额需要为正数"，不调工具。

---

## STEP 3 — 执行流程 + 渲染

所有意图先调 `rule_engine(action="list_options")`；首次需调 `customer_info`。

> rule_engine 返回渠道级摘要（不含保单明细）：`channels.zero_cost.total` = 生存金+红利合计，
> `channels.policy_loan.total` = 贷款合计，`channels.partial_withdrawal.total` / `channels.surrender.total` 等。
> LLM 用这些 total 做策略判断（是否需要组合渠道），保单级分配由 render_a2ui 内部完成，LLM 不需要知道每张保单的金额。

### SUMMARY 渲染

默认展示全部分组（sections 为 null 时），空数据的 section 自动返回空：

```json
[
  {"type": "WithdrawSummaryHeader", "data": {"sections": ["zero_cost", "loan", "partial_withdrawal", "surrender"]}},
  {"type": "WithdrawSummarySection", "data": {"section": "zero_cost"}},
  {"type": "WithdrawSummarySection", "data": {"section": "loan"}},
  {"type": "WithdrawSummarySection", "data": {"section": "partial_withdrawal"}},
  {"type": "WithdrawSummarySection", "data": {"section": "surrender"}}
]
```

筛选时只传对应 sections 和 section，结构相同。

### PLAN 渲染

**默认生成 2 个 PlanCard**（推荐 + 备选），仅以下情况出 1 个：

- target > 全部可用 → 只出一个"最大可取"方案
- target = 0（渠道定向）→ 出该渠道全部可用额度的单方案
- 只有一种可用渠道类别（无法构成备选）

**渠道优先级（从高到低）**：

1. **生存金 + 红利** → 零成本，不影响保障
2. **部分领取**（非 whole_life 的 refund_amt）→ 低成本
3. **保单贷款** → 年利率 5%，保障不受影响
4. **退保**（whole_life 的 refund_amt）→ 保障终止，最后手段

**channels 推导**：

- channels 不为 null → 直接使用
- channels 为 null → 按上述优先级选渠道（推荐方案用最高优先级类别，备选方案加入次优先级）

**title/tag 规则**：

- 纯零成本渠道 → "★ 推荐: 零成本领取" + "(不影响保障)"
- 含贷款 → "(部分需付利息)"
- 含退保 → "(保障有损失)"
- 单渠道 → 直接用渠道中文名

**示例**（渠道定向"领取生存金"，无金额 → 单方案）：

```json
[
  {"type": "WithdrawPlanCard", "data": {
    "channels": ["survival_fund"],
    "target": 0,
    "title": "生存金领取",
    "tag": "(不影响保障)"
  }}
]
```

`target=0` 表示取该渠道全部可用额度。需组合时 `target` = 用户目标金额。

### ADJUST 渲染

1. 从上轮 PlanCard digest 中读取 `channels: [...]` 和 `总额: ¥...`
2. 应用用户变更（见下表）
3. 重新 `rule_engine(list_options)` + `render_a2ui`

**调整方式参考**（从上轮 digest 的 channels 基础上修改）：

| 用户说 | data 变更 |
|--------|----------|
| "多取一点，总共8万" | target → 80000 |
| "不要贷款" | channels 中移除 policy_loan |
| "不退保" | channels 中移除 surrender |
| "只用不影响保障的" | channels → ["survival_fund","bonus"] |
| "不要POL002" | exclude_policies: ["POL002"] |

---

## 注意事项

1. 始终优先推荐零成本、不影响保障的渠道
2. 金额计算由 component 内部完成，LLM 只控制 component 选择和 data 参数
3. `product_type=whole_life` 的 refund_amt 为退保（保障终止），其他为部分领取

## 注意：数字准确性

禁止自行计算或推算任何金额，所有数字以工具返回为准。
