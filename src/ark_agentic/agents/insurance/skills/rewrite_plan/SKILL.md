---
name: 方案改写
description: 用户已看过取款方案后表达任何修改意图时，立即使用此技能。涵盖"多取一点"、"不要贷款"、"换个方案"、"利息太高"、"某保单少取点"等改写场景；先判断调整类型（A金额/B渠道/C单项），再调用 rule_engine 并以 A2UI 卡片展示调整结果，卡片后仅一句对比说明。禁止重新走 clarify_need 流程。
version: "4.0.0"
invocation_policy: auto
group: insurance
tags:
  - rewrite
  - customization
required_tools:
  - rule_engine
  - render_card
---

# 方案改写技能

> **输出原则（最高优先级）**
>
> 用户已经看过一次方案，这次是在「对比」。A2UI 卡片承载了新方案的全部细节。
> 你唯一需要补充的，是帮用户完成一个判断：「这次和上次有什么不同，值不值得换？」
> 这一句话就够了。写更多会让用户感到信息过载，也会让确认按钮被淹没。
>
> 因此：`render_card` 调用后，**只允许 1 句文字（≤ 25 字）**，聚焦于与原方案的关键差异或确认引导。
> 如果你发现自己想写第二句话——那正说明卡片已经把该说的都说了，**停止**。

当用户**对已推荐的方案**提出修改意见时，使用此技能调整方案。

## 前置条件

本技能仅在 withdraw_money 技能已经给出过方案推荐之后才可能触发。如果用户还没看到过方案就提出修改要求，应先走 clarify_need → withdraw_money 的正常流程。

## 触发条件

用户表达以下意图时触发（前提是已有推荐方案）：
- "金额能多一点吗"
- "有没有更快到账的方案"
- "能不能不要影响保障"
- "不要贷款 / 不要退保"
- "换一个方案"
- "我觉得利息太高了"
- "POL002 少取一点"

**不触发**的情况：
- 用户初次表达取款意图 → 由 clarify_need / withdraw_money 处理
- 用户确认方案、同意办理 → 由 withdraw_money 的确认流程处理

## 回复结构

- **推荐结构**：`A2UI 取款汇总卡片 + 最多 1 句（≤25字，对比差异或引导确认）`；卡片前**不写任何引导语**。
- **原则**：答案以 A2UI 卡片为核心；卡片后仅允许 1 句简短对比或确认；**严禁** Markdown 列表、多段落或任何卡片内容重述。

## 关于规则引擎返回数据

规则引擎 `list_options` 返回每张保单一条记录，包含四个金额字段：

| 字段 | 含义 | 特点 |
|-----|------|------|
| `survival_fund_amt` | 生存金 | 零成本，不影响保障 |
| `bonus_amt` | 红利 | 零成本，不影响保障 |
| `refund_amt` | 部分领取/退保金额 | `product_type=whole_life` 时为退保，其他为部分领取 |
| `loan_amt` | 保单贷款额度 | 年利率见 `loan_interest_rate` |
| `available_amount` | 四项合计 | 该保单总可用金额 |

同一张保单的多个渠道可同时使用，但每个渠道取用金额不得超过该渠道的数值。

## 第一步：判断调整类型

用户的修改请求分为三类，**必须先判断属于哪一类**，再选择对应的处理方式：

### 类型 A：调整总金额

用户想改变取款的总目标金额，但没有指定某张保单或某种方式。

典型表述：
- "我想多取一点，总共8万"
- "5万太多了，3万就够了"
- "能不能凑到10万"

**处理方式**：重新调用 `list_options`，用新金额获取最新保单数据。

```
rule_engine(action="list_options", user_id=用户ID, amount=新总金额)
```

然后基于新的保单数据，按 withdraw_money 技能的组装逻辑重新构建推荐方案。

**金额不足处理**：如果 `total_available_incl_loan` < 新金额，给出最大可取方案并告知用户。

### 类型 B：改变方案方向 / 排除某类渠道

用户不改金额，但对渠道类型有偏好或排除条件。

典型表述：
- "不要贷款"
- "不想退保"
- "只用不影响保障的方式"
- "有没有不收手续费的方案"
- "我不想动那个终身寿险"

**处理方式**：重新调用 `list_options` 获取完整保单数据，在 `plans` 规格中通过 `exclude_channels` 声明排除约束，extractor 自动补足至目标金额（排除指定渠道后的最大可取）。

```
rule_engine(action="list_options", user_id=用户ID, amount=原金额)
```

拿到结果后，根据用户约束设置 `exclude_channels`（extractor auto-fill 也会跳过这些渠道）：
- "不要贷款" → `exclude_channels: ["policy_loan"]`
- "不要退保" → `exclude_channels: ["surrender"]`
- "不影响保障" / "只用零成本" → `exclude_channels: ["partial_withdrawal", "policy_loan", "surrender"]`
- "不想动某保单" → 用 `exclude_policies: ["POL00X"]`（与 exclude_channels 独立）

如果排除后剩余渠道总额无法满足金额，extractor 会如实展示最大可取；明确告知用户并给出替代建议。

### 类型 C：调整某张保单 / 某个渠道的具体金额

用户针对已推荐方案中的某一项做微调。

典型表述：
- "POL002 少取一点，取3万就行"
- "保单贷款能不能只贷2万"
- "红利那个能全取吗"

**处理方式**：用 `calculate_detail` 对目标保单的指定渠道做精确计算。

```
rule_engine(
  action="calculate_detail",
  policy={...从上文 list_options 结果中获取该保单数据...},
  option_type="对应渠道类型",
  amount=新金额
)
```

`option_type` 取值：`survival_fund`, `bonus`, `partial_withdrawal`, `surrender`, `policy_loan`

**金额约束**：新金额不得超过该渠道的可用额度（如 `loan_amt` 是贷款上限）。如果用户要求的金额超过上限，`calculate_detail` 会自动按最大额度计算并返回 warning 字段，应向用户说明。

### 混合场景

用户可能同时提出多个条件，如 "多取一点但不要贷款"。处理方式：
1. 先用类型 A 的方式重新 `list_options`（新金额）
2. 再按类型 B 在组装方案时过滤掉不需要的渠道
3. 基于过滤后的保单数据组装方案

## 第二步：生成调整方案

所有类型改写后，均调用 `render_card(card_type="withdraw_plan", card_args=JSON)`，**你自行决策方案结构**（channels、title、reason），extractor 负责分配金额和生成按钮。

**核心原则：改写后同样只有一个 ★ 推荐。** 只有排名第一的方案标 ★ 推荐，其余为备选。

### 类型 A / B 的渲染流程

```
rule_engine(list_options, amount=...) → render_card(withdraw_plan, card_args={plans: [...]})
```

**类型 A**（调总额）：`list_options(new_amount)` → 按新金额组装 plans → `render_card(withdraw_plan)`。

**类型 B**（改方向/渠道排除）：`list_options(original_amount)` → 根据用户约束决定每个 plan 的 channels：
- "不要贷款" → plans 的 channels 不含 `policy_loan`
- "不要退保" → plans 的 channels 不含 `surrender`
- "只用不影响保障的" → channels 只有 `["survival_fund", "bonus"]`
- "不想动某保单" → 对应 plan spec 加 `"exclude_policies": ["POL00X"]`

→ `render_card(withdraw_plan, card_args={plans: [...]})`

**类型 C**（调单项）的工具调用链：
1. `rule_engine(calculate_detail, ...)` — 获取单项精确计算结果
2. `rule_engine(list_options, amount=目标金额)` — 刷新 context（必须，否则卡片数据与调整不一致）
3. `render_card(withdraw_plan, card_args={plans: [...]})` — LLM 在 plans 中体现 `calculate_detail` 结果

**混合 A+B**：先用新金额 `list_options`，再在 plans spec 中过滤渠道。

**禁止**：有 `list_options` 结果时必须先出卡片，不得用文字描述方案详情。卡片已完整承载所有方案信息，文字不得重复。

#### card_args 示例（类型 B："不要贷款"）

```json
{
  "plans": [
    {
      "title": "★ 推荐: 零成本优先（不含贷款）",
      "tag": "(不含贷款)",
      "reason": "优先使用零成本渠道，不足时搭配部分领取补足，不使用贷款。",
      "channels": ["survival_fund", "bonus"],
      "exclude_channels": ["policy_loan"]
    },
    {
      "title": "全零成本（可能不足）",
      "tag": "(不影响保障)",
      "reason": "仅使用生存金和红利，不影响保障，金额可能不足目标。",
      "channels": ["survival_fund", "bonus"],
      "exclude_channels": ["partial_withdrawal", "policy_loan", "surrender"]
    }
  ]
}
```

## 第三步：操作确认

卡片后的 1 句文字即为确认引导（如"是否按此方案办理？"）。用户不满意则继续调整。

## 手续费参考

部分领取手续费率（按保单年度）：

| 保单年度 | 手续费率 |
|---------|---------|
| 第 1 年 | 3% |
| 第 2 年 | 2% |
| 第 3-5 年 | 1% |
| 第 6 年起 | 0% |

保单贷款：年利率 5%（固定），按日计息。

生存金领取、红利领取、退保：无手续费。

## 常见改写场景速查

| 用户说 | 调整类型 | 工具调用链 | plans 约束处理 |
|-------|---------|-----------|--------------|
| "多取一点" / "总共要X万" | A 调总额 | `list_options(新amount)` → `render_card(withdraw_plan)` | 按新金额正常组装，无 exclude |
| "不要贷款" | B 改方向 | `list_options(原amount)` → `render_card(withdraw_plan)` | `exclude_channels: ["policy_loan"]` |
| "不退保" | B 改方向 | `list_options(原amount)` → `render_card(withdraw_plan)` | `exclude_channels: ["surrender"]` |
| "只用不影响保障的" | B 改方向 | `list_options(原amount)` → `render_card(withdraw_plan)` | `exclude_channels: ["partial_withdrawal","policy_loan","surrender"]` |
| "不想动某保单" | B 改方向 | `list_options(原amount)` → `render_card(withdraw_plan)` | `exclude_policies: ["POL00X"]` |
| "POL002 少取点" | C 调单项 | `calculate_detail` → `list_options(amount)` → `render_card(withdraw_plan)` | 在 plan reason 中体现调整结果 |
| "贷款只贷2万" | C 调单项 | `calculate_detail(policy_loan)` → `list_options` → `render_card(withdraw_plan)` | `exclude_channels: ["policy_loan"]`，loan plan target=20000 |
| "多取一点但不要贷款" | A+B 混合 | `list_options(新amount)` → `render_card(withdraw_plan)` | `exclude_channels: ["policy_loan"]` |
| "换个方案" | B 改方向 | `list_options(原amount)` → `render_card(withdraw_plan)` | 调整 channels 偏好顺序 |
| "利息太高了" | B 改方向 | `list_options(原amount)` → `render_card(withdraw_plan)` | `exclude_channels: ["policy_loan"]` |

## 输出格式

**主方案 = A2UI 取款方案卡片（`withdraw_plan`）**。卡片渲染成功后，文字部分**严格限制**在 1 句以内（≤25字）。禁止在未先出卡片时用任何文字描述方案详情。

### 类型 A / B / C

`render_card(withdraw_plan, card_args={plans: [...]})` → 之后仅 1 句对比或确认（如"比原方案少手续费 X 元，是否确认？"），无其他文字。

### 金额不足时

1 句说明：最多可取 **X 元**，无法满足 Y 元，是否调整？

## 风格要求

- 友好、专业、简洁、通俗
- 避免机械表达，体现对用户需求的理解
- 金额使用千分位格式（如 65,000 元）
- 对比原方案时用简洁的方式呈现差异
- 不要自行编造金额，所有数字必须来自规则引擎计算

## 注意事项

1. 始终尊重用户的偏好
2. 必须先判断调整类型（A/B/C），再选择正确的工具 action
3. 每个方案必须标注关联保单的名称和保单号
4. 不可行时主动提供替代建议，说明原因
5. 方案展示后必须引导用户确认，不要直接结束对话
6. 退保相关调整需要额外风险提示
7. **只有一个 ⭐ 推荐**：改写后的结果也只标一个推荐，其余为备选
8. **不要做需求澄清**：本技能处理的是已有方案的修改，不是初始需求收集
9. **金额硬约束**：每个渠道的取用金额不得超过该渠道的数值（survival_fund_amt / bonus_amt / loan_amt / refund_amt）
10. **product_type 决定 refund_amt 含义**：`whole_life` = 退保（保障终止），其他 = 部分领取
