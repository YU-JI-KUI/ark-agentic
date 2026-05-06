---
enabled: True
name: 保险取款
description: 当用户表达取款意图时使用：询问可取金额、查询总览、指定金额/渠道取款、调整已有方案。
version: "16.0.0"
invocation_policy: auto
group: insurance
tags:
  - withdrawal
  - insurance
  - financial
required_tools:
  - rule_engine
  - render_a2ui
---

# 保险取款技能

<output_constraint>
1. **必须**：每次展示取款数据时调用 `render_a2ui`。严禁用 Markdown 表格、列表或纯文本替代。如果你准备写表格或列表来展示数据——停下来，改为调用 `render_a2ui`。
2. **回退/引用/重复方案也必须重新出卡片**：用户说"还是第一个方案"、"回到之前的"等，必须重新 `rule_engine` + `render_a2ui`，禁止从对话记忆中复述。
3. **禁止**：在文字回复中重复卡片已展示的金额、渠道名称或保单号。卡片后仅 1 句引导（≤25字）。
4. **多个 PlanCard 必须在同一次 `render_a2ui` 调用中生成**（blocks 数组包含多个 WithdrawPlanCard），禁止分多次调用。
5. **不要传 title/tag/tag_color**：标题与标签由引擎从实际分配渠道反推，LLM 端只控制 `channels` / `target` / `is_recommended` / `reason`。
6. 违反以上任一条等同于任务失败。
</output_constraint>

三步流水线：**意图分类 → 参数提取 → 渲染**。

---

## 触发 / 不触发

**触发**：用户表达与取款相关的咨询、方案生成、方案调整意图。

**不触发**（交「渠道办理」处理）：最近 render_a2ui digest 以 `[卡片:方案` 或 `[卡片:渠道步骤` 开头 **且** 用户明确选择该方案中某渠道办理（生存金/红利/保单贷款），或正处于已有渠道流中。

**兜底**：以下情况本技能主导 SUMMARY / PLAN / ADJUST 流程：
- digest 只有 `[卡片:总览/…]` 或无 A2UI 渲染历史
- 「渠道办理」因条件不满足（渠道不在方案 channels 里、无 PlanCard 等）回退

---

## STEP 1 — 意图分类

按规则从上到下匹配，命中即停：

| 序号 | 意图 | 触发条件 | 示例 |
|------|------|---------|------|
| R1 | **ADJUST** | 最近 digest 含 `[卡片:方案` **且** 出现修改语义 | "不要贷款"、"少取"、"多取"、"换方案" |
| R2 | **PLAN** | 用户消息含**可解析金额**（如 10000 / 5万 / 十万）**或** 渠道名 + 办理类动词（"办理贷款"、"领取生存金"） | "取5万"、"领生存金"、"贷款3万" |
| R3 | **SUMMARY**（带 sections）| 用户消息为筛选关键词或 SUMMARY 后选择 | "只看零成本"、"不看贷款" |
| R4 | **SUMMARY** | 其余咨询类问句（无金额、无办理动词） | "能取多少"、"帮我看看"、"怎么取" |

**辅助说明**：
- ADJUST 需要 digest 前提。如果最近 digest 不含 `[卡片:方案`，但用户消息满足 R2 条件 → 走 PLAN，不走 ADJUST。
- "取" 字单独不算办理动词。"能取多少" / "可以取吗" 是问句，按 R4 走 SUMMARY；"取5万" 含金额，按 R2 走 PLAN。

### SUMMARY sections 对照表

| 用户说法 | sections 值 |
|---------|-------------|
| 零成本 / 不影响保障的（生存金+红利合并） | `["zero_cost"]` |
| 只看红利 / 红利有多少 | `["bonus"]` |
| 只看生存金 / 生存金有多少 | `["survival_fund"]` |
| 不看贷款 | `["zero_cost", "partial_withdrawal", "surrender"]` |
| 不看退保 | `["zero_cost", "loan"]` |
| 全部（默认） | `["zero_cost", "loan", "partial_withdrawal", "surrender"]` |

---

## STEP 2 — 参数提取

### SUMMARY 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| sections | list / null | 要展示的分组，null = 全部 |
| exclude_policies | list / null | 排除的保单 |

### PLAN / ADJUST 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| target | number / null | 目标金额，null = 取 channels 累计全额 |
| channels | list / null | 渠道 ID 列表，**顺序 = 分配优先级**（贪心从前到后），null = 由 STEP 3 决策表生成 |
| is_recommended | bool | 该卡片是否带 "★ 推荐" 前缀；一组方案中至多 1 个为 true |
| exclude_policies | list / null | 排除的保单 |

> ⚠️ `channels` 数组的顺序至关重要：引擎按 `[ch_0, ch_1, ...]` 顺序贪心分配 target。
> 比如 `channels=["policy_loan","survival_fund"]` 会先扣完贷款额度才动生存金。
> 通常优先级高的渠道写在前面。

> ⚠️ **不要传 title / tag / tag_color**。标题与标签由引擎根据"实际被分配的渠道"反推，
> 这样可以保证标题不会撒谎（不会出现"含贷款方案"但明细里没贷款的情况）。

### 渠道 ID

| 用户说法 | channel ID |
|---------|-----------|
| 生存金 | `survival_fund` |
| 红利 | `bonus` |
| 贷款 | `policy_loan` |
| 部分领取 | `partial_withdrawal` |
| 退保 | `surrender` |

### 金额校验

target 为负数 → 直接回复"取款金额需要为正数"，不调工具。

---

## STEP 3 — 执行流程 + 渲染

所有意图先调 `rule_engine(action="list_options", user_id=…)`。返回的 LLM digest 摘要长这样：

```json
{
  "status": "ok",
  "policy_count": 3,
  "channels": {
    "zero_cost":          {"total": 17200, "note": "不影响保障"},
    "survival_fund":      {"total": 12000},
    "bonus":              {"total": 5200},
    "partial_withdrawal": {"total": 245000, "note": "保额降低，可能有手续费"},
    "policy_loan":        {"total": 33600, "note": "年利率5%"},
    "surrender":          {"total": 42000, "note": "保障终止"}
  },
  "grand_total": 342800,
  "combination_hint": null
}
```

为表述简洁，下文用 `zero` / `partial` / `loan` / `surrender` / `grand` 指代上面对应的 `total`。

### SUMMARY 渲染

默认展示全部分组（sections 为 null 时），空数据的 section 自动返回空：

```json
[
  {"type": "WithdrawSummaryHeader", "data": {"sections": ["zero_cost", "loan", "partial_withdrawal", "surrender"]}},
  {"type": "WithdrawSummarySection", "data": {"section_name": "zero_cost"}},
  {"type": "WithdrawSummarySection", "data": {"section_name": "loan"}},
  {"type": "WithdrawSummarySection", "data": {"section_name": "partial_withdrawal"}},
  {"type": "WithdrawSummarySection", "data": {"section_name": "surrender"}}
]
```

筛选时只传对应 sections 和 section_name，结构相同。

### PLAN 渲染 — 两条规则

#### R1 — Plan A（推荐）：选满足 target 所需的最少渠道

按优先级 `[survival_fund, bonus, partial_withdrawal, policy_loan, surrender]` 依次纳入，累计可用 ≥ target 即停。

特例：
- 用户已显式指定 channels → 直接使用，不跑 R1
- target = 0 / 渠道定向（"领生存金"无金额）→ channels = 用户指定的单渠道，target = 0（引擎按 channels 累计上限处理）
- target > grand → channels = 全渠道，target = grand，**不出 Plan B**

#### R2 — Plan B（备选，可选）

只在能产生**与 Plan A 路径不同的可行组合**时才出，否则只出 Plan A：

把 Plan A 用到的最低优先级渠道，**替换为下一个非零渠道**，得到 Plan B 的 channels。如果替换后累计可用 < target，放弃 Plan B。

### 算例 1：用户 U001 说"取 10000"

rule_engine 摘要（U001 实际数据）：
- zero=17200, partial=245000, loan=33600, surrender=42000

**R1 — Plan A**：从 survival_fund(12000) 起纳入 → 12000 < 10000？否，12000 ≥ 10000，停。
- channels = `["survival_fund"]`，target = 10000，is_recommended = true

**R2 — Plan B**：把 Plan A 最低优先级 `survival_fund` 替换为下一个非零渠道 `bonus`。
- bonus 单独 5200 < 10000，需补：再加下一优先级 partial_withdrawal。
- channels = `["bonus", "partial_withdrawal"]`，target = 10000，is_recommended = false

调用：

```json
[
  {"type": "WithdrawPlanCard", "data": {
    "channels": ["survival_fund"], "target": 10000, "is_recommended": true
  }},
  {"type": "WithdrawPlanCard", "data": {
    "channels": ["bonus", "partial_withdrawal"], "target": 10000, "is_recommended": false
  }}
]
```

引擎反推 → Plan A 标题"★ 推荐: 生存金领取"，Plan B 标题"组合领取方案"。两张卡片实际分配不同。

### 算例 2：用户 U001 说"取 200000"

- zero=17200 < 200000 → 加 partial → 17200+245000=262200 ≥ 200000，停。

**R1 — Plan A**：channels = `["survival_fund", "bonus", "partial_withdrawal"]`，target = 200000，is_recommended = true

**R2 — Plan B**：替换最低优先级 `partial_withdrawal` → `policy_loan`。
- 17200 + 33600 = 50800 < 200000 → 不可行 → 放弃 Plan B。

只出 Plan A。

### 算例 3：用户 U001 说"领生存金"（渠道定向，无金额）

R2 不需要（已显式指定渠道）：

```json
[{"type": "WithdrawPlanCard", "data": {
    "channels": ["survival_fund"], "target": 0, "is_recommended": true
}}]
```

`target=0` 时引擎按该渠道全部可用额度分配。

### ADJUST 渲染

1. 从最近 `[卡片:方案` digest 中读取 `channels=[…]` 和 `total=…` 作为基线
2. 应用用户变更（见下表）
3. 重新 `rule_engine(list_options)` + `render_a2ui`

| 用户说 | data 变更 |
|--------|----------|
| "多取一点，总共8万" | target → 80000 |
| "不要贷款" | channels 中移除 policy_loan |
| "不退保" | channels 中移除 surrender |
| "只用不影响保障的" | channels → ["survival_fund","bonus"] |
| "不要 POL002" | exclude_policies → ["POL002"] |

---

## 注意事项

1. 始终优先推荐零成本、不影响保障的渠道
2. 金额计算与标题派生由引擎完成，LLM 只控制 `channels` / `target` / `is_recommended`
3. `product_type=whole_life` 的 refund_amt 为退保（保障终止），其他为部分领取
4. 禁止自行计算或推算任何金额，所有数字以工具返回为准
