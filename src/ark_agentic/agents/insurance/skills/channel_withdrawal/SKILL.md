---
enabled: False
name: 渠道办理
description: PlanCard（[卡片:方案]）已展示后，或处于已有渠道流（[卡片:渠道步骤]/[渠道流:…]）中。用户表达办理/确认/好/是的/选某渠道/继续/上一步/下一步/中断/暂停/恢复 等意图时使用。覆盖：生存金 / 红利 / 保单贷款 三步办理（保单→金额→银行卡）。
version: "2.1.0"
invocation_policy: auto
group: insurance
tags:
  - withdrawal
  - channel
  - flow
required_tools:
  - channel_flow
---

# 渠道办理技能

## 工具与职责

只用一个工具：`channel_flow(channel, action)`。
- 状态变更（`_channel_flows`）与卡片渲染（`ChannelStepCard`）由工具**原子完成**
- 本技能下严禁调用 `render_a2ui` / `rule_engine` / `submit_withdrawal` / `customer_info` / `policy_query`

三步：`policy`（保单确认） → `amount`（金额确认） → `bank_card`（银行卡确认）。

## 触发门禁

**前置条件（必须）**：最近 digest 含 `[卡片:方案 …]` 或 `[卡片:渠道步骤 …]` 或 `[渠道流:…]`

**用户消息任一即可**：
- 含办理动词 + 渠道（"领生存金"、"办贷款"、"办红利"）
- 含光秃秃的办理 / 接受意图（"办理"、"确认"、"好"、"好的"、"是的"、"可以"、"就这个"、"选这个"、"这个"、"对"）
- 含步骤导航词（"下一步"、"上一步"、"继续"、"返回"、"暂停"、"中断"、"恢复"、"回到"）
- 按钮 query：以 `__channel_step__:` 开头

**让位**：用户明确表达调整意图（"换方案"、"少取"、"多取"、"不要贷款"等）→ 不触发本技能，由「保险取款」ADJUST。

`partial_withdrawal` / `surrender` 不在本技能覆盖范围内。

## 状态定位（必须先做）

每次响应前从最近一条工具结果 digest 中读取**单字段**：

```
active_channel=<X>      ← 永远以最近这个字段为准
```

工具每次返回的 digest 都带 `active_channel=`（含 `[卡片:渠道步骤 …]` 也带）。
不要从「最近一张卡是哪个 channel」去猜——直接读字段。

## 决策树（从上到下，命中即停）

### STEP 0 — 按钮 query 快速路径

用户消息形如 `__channel_step__:<channel>:<action>` → 直接调

```
channel_flow(channel=<channel>, action=<action>)
```

action 取值与含义：

| action | 含义 |
|---|---|
| `confirm_policy` / `confirm_amount` / `confirm_bank` | 推进 |
| `back` | 后退（amount→policy；bank_card→amount，自动清银行卡） |
| `interrupt` | 暂停当前 active 渠道 |

### STEP 1 — 自然语言推进 / 后退（已存在渠道流时）

**仅在最近 digest 是 `[卡片:渠道步骤 …]` 或 `[渠道流:…]` 时适用**（即已经在三步流程中）。
读 `active_channel=X`、`step=Y`，按下表映射：

**强意图词**（严格匹配，命中才动状态）：

| 用户消息 | step=policy | step=amount | step=bank_card |
|---|---|---|---|
| 下一步 / 继续办 / 确认 | confirm_policy | confirm_amount | confirm_bank |
| 提交 / 确认提交 | （拒绝） | （拒绝） | confirm_bank |
| 上一步 / 返回 / 改一下 | （拒绝） | back | back |

**拒绝条件下不调工具**，只回复一句话：
- 在 step=policy 说"上一步" → 回复："这是第 1 步，没有上一步。"
- 在 step≠bank_card 说"确认提交" → 回复："请先完成前面的步骤。"

**禁止把寒暄/弱应答当成强意图**：单字"好"、"嗯"、"行"、"OK"，半句"我看下"、"等等"、"再说"——**都不调工具**，正常回复即可。

### STEP 2 — 启动 / 切换 / 恢复（用户明确指渠道）

用户含办理类动词 + 渠道 Y（"领 Y"、"办 Y"、"继续 Y"、"回到 Y"）：

```
channel_flow(channel=Y, action=start)
```

- 工具自动判断「新建」（首次）vs「恢复」（已存在 paused/active）
- 工具自动暂停其他 active 渠道
- 不需要先判断当前是哪种情况

### STEP 2.5 — PlanCard 上的光秃秃确认（关键路径）

**最近 digest 是 `[卡片:方案 …]`**（PlanCard 已展示，但还没进入三步流程），
用户表达办理意图但**没指明渠道**："办理"、"确认"、"好"、"好的"、"是的"、"可以"、
"就这个"、"选这个"、"这个"、"对"、"成"、"行"。

操作：

1. 从最近 `[卡片:方案 channels=[A,B,C] …]` digest 读 channels 列表
2. 过滤：只保留 `{survival_fund, bonus, policy_loan}` 内的渠道
3. 分支：
   - 过滤后 **1 个** 渠道 X：`channel_flow(channel=X, action=start)`
   - 过滤后 **>1 个** 渠道：**不调工具**，回复："本方案含 N 项，您想先办哪个？"
     列出每个渠道的中文名 + 金额（从 digest 读，不要复述全部细节，每行 ≤15 字）
   - 过滤后 **0 个** 渠道：回复："当前方案不含三步办理渠道（仅支持生存金/红利/贷款），如需办理部分领取或退保请告诉我。"

> ⚠️ 这一步是用户"重复确认死循环"的修复点。看到 `[卡片:方案]` digest 又遇到光秃秃的"确认"/"好"——**直接走这一步**，不要反过来再问"想办什么"。

### STEP 3 — 单纯中断

用户说"暂停"、"先不办"、"等会儿"，且不指明切换到其他渠道：

```
channel_flow(channel=<active_channel>, action=interrupt)
```

### STEP 4 — fallthrough（兜底）

用户消息与办理流程无关（"今天天气怎么样"、"我妈也有保险吗"等），且 R0~R3 都不匹配：

- **不调工具**
- 正常回答用户问题
- 状态保持不变（`_channel_flows` 不变）
- 完成后用户下一步仍可继续办理

---

## 错误恢复

`channel_flow` 返回 `is_error=true` 时，按错误内容判断：

| 错误片段 | 处理 |
|---|---|
| `step=X 无法执行 Y` | 读最近 digest 校正 step，按正确 action 重试 1 次 |
| `无法后退` | 回复："这是第 1 步，没有上一步。" 不重试 |
| `没有进行中的办理` / `流程未启动` | 改调 `action=start` |
| `已提交` | 回复："该渠道已办完，如需新办需先生成新的取款方案。" |
| `在当前方案中没有分配` | 回复："当前方案里没有该渠道的额度。" |
| `不支持的渠道` | 回复："仅支持生存金、红利、保单贷款的三步办理。" |

最多重试 1 次；仍失败 → 告知用户当前状态，不再调工具。

---

## 卡片后回复模板（≤25 字，严格遵守）

工具触发卡片后（start / confirm_policy / confirm_amount / back），**禁止**复述卡片内
容（金额、保单号、银行卡）。仅用以下模板：

| 工具结果 | 回复 |
|---|---|
| 推进到 step=amount | （直接出卡，不加文字 / 仅"请确认金额"） |
| 推进到 step=bank_card | （直接出卡，不加文字 / 仅"请确认银行卡"） |
| back 到 amount | "已返回金额确认。" |
| back 到 policy | "已返回保单确认。" |
| start（新建） | "请确认保单。" |
| start（恢复） | "已恢复办理。" |

confirm_bank 与 interrupt 由工具自带文案，不用再加。

---

## 正例

### 例 1：方案卡 → 用户领生存金 → 完整三步

```
最近 digest: [卡片:方案 ... channels=[survival_fund] total=10000.00]
用户: "领生存金"
助手: → channel_flow(channel=survival_fund, action=start)
       工具同时返回 ChannelStepCard 卡片 + digest:
       [渠道流:启动 channel=survival_fund step=policy active_channel=survival_fund]

按钮 → "__channel_step__:survival_fund:confirm_policy"
助手: → channel_flow(channel=survival_fund, action=confirm_policy)
       digest: [渠道流:推进 channel=survival_fund step=amount
                active_channel=survival_fund]

按钮 → "__channel_step__:survival_fund:confirm_amount"
助手: → channel_flow(channel=survival_fund, action=confirm_amount)
       digest: [渠道流:推进 channel=survival_fund step=bank_card
                active_channel=survival_fund]

按钮 → "__channel_step__:survival_fund:confirm_bank"
助手: → channel_flow(channel=survival_fund, action=confirm_bank)
       digest: [渠道流:已提交 channel=survival_fund
                active_channel=none remaining=[]]
       回复: "生存金领取已完成。"
```

### 例 2：聊天驱动「下一步 / 上一步 / 确认」

```
最近 digest: [卡片:渠道步骤 channel=bonus step=amount
              active_channel=bonus]

用户: "下一步"
助手: → channel_flow(channel=bonus, action=confirm_amount)

用户: "上一步"
助手: → channel_flow(channel=bonus, action=back)

用户: "确认"   # 此刻 step=amount → 等同 confirm_amount
助手: → channel_flow(channel=bonus, action=confirm_amount)

用户: "确认提交"   # 此刻 step=bank_card
助手: → channel_flow(channel=bonus, action=confirm_bank)
```

### 例 3：中断 → 切换 → 恢复

```
最近 digest: [渠道流:推进 channel=bonus step=amount active_channel=bonus]

用户: "我先办贷款"
助手:
  → channel_flow(channel=bonus, action=interrupt)
  # 然后启动贷款（同一对话，下一轮）
  → channel_flow(channel=policy_loan, action=start)

[完整办完贷款 ... digest: [渠道流:已提交 channel=policy_loan
                            active_channel=none remaining=[bonus]]]

用户: "继续红利"
助手: → channel_flow(channel=bonus, action=start)
       # 工具自动恢复到 step=amount
```

### 例 4：用户中文渠道名

```
用户: "领红利"
助手: → channel_flow(channel="红利", action="start")
       # 工具内部 normalize 到 "bonus"
```

### 例 5：PlanCard 单渠道 + 光秃秃确认（修复重复确认死循环）

```
最近 digest: [卡片:方案 title="★ 推荐: 生存金领取" channels=[survival_fund] total=10000]

用户: "确认"   或 "好"   或 "好的"   或 "就这个"
助手（STEP 2.5，channels=[survival_fund] 仅 1 个支持渠道）:
  → channel_flow(channel=survival_fund, action=start)
  ↳ A2UI 卡 + digest: [渠道流:启动 channel=survival_fund step=policy active_channel=survival_fund]
  回复: "请确认保单。"
```

### 例 6：PlanCard 多渠道 + 光秃秃确认 → 让用户挑

```
最近 digest: [卡片:方案 channels=[survival_fund,bonus] total=17200] 生存金 ¥12,000.00 · 红利 ¥5,200.00

用户: "确认"
助手（STEP 2.5，>1 个支持渠道，先列出让用户选）:
  不调工具
  回复: "本方案含两项，您想先办哪个？
         1. 生存金 ¥12,000
         2. 红利 ¥5,200"

用户: "先办生存金"
助手（STEP 2，渠道明确）:
  → channel_flow(channel=survival_fund, action=start)
```

---

## 反例（禁止）

### 反例 1：单字寒暄被误判为确认

```
digest: [卡片:渠道步骤 channel=bonus step=amount active_channel=bonus]
用户: "好"   # 用户只是回应"已确认金额，进入第 2 步"，不是确认动作
❌ channel_flow(bonus, confirm_amount)
✅ 回复："请确认金额。"（不调工具）
```

### 反例 2：在 step=policy 说"上一步"调工具

```
digest: [卡片:渠道步骤 channel=bonus step=policy active_channel=bonus]
用户: "上一步"
❌ channel_flow(bonus, back)   # 工具会拒
✅ 直接回复："这是第 1 步，没有上一步。" 不调工具
```

### 反例 3：confirm_bank 后再 start 同一渠道

```
digest: [渠道流:已提交 channel=bonus active_channel=none remaining=[]]
用户: "再办一次红利"
❌ channel_flow(bonus, start)   # 工具拒"已提交"
✅ 回复："红利领取本轮已完成，如需新办需先生成新的取款方案。"
```

### 反例 4：和 render_a2ui 一起调

```
❌ 一轮内同时调 channel_flow + render_a2ui ChannelStepCard
   channel_flow 已经自带卡片，重复 render 会让屏幕出两张。
✅ 只调 channel_flow。
```

### 反例 5：把跨渠道意图当中断

```
digest: [卡片:渠道步骤 channel=bonus step=amount active_channel=bonus]
用户: "改办贷款"   # 这是切换，不是单纯中断
❌ 只调 channel_flow(bonus, interrupt) 就回复
✅ 先 channel_flow(bonus, interrupt)，下一轮再 channel_flow(policy_loan, start)
```

### 反例 6：复述卡片字段

```
工具返回 ChannelStepCard：保单 POL002，金额 ¥3,000.00
❌ 文字回复："您的红利保单 POL002，金额 3,000 元，请确认。"
✅ 文字回复："请确认金额。"  ≤25 字 + 不复述卡片字段
```
