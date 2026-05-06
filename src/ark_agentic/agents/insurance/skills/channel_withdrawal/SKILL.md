---
enabled: True
name: 渠道办理
description: 用户在 PlanCard 上选定渠道（生存金/红利/保单贷款）后办理，或在已有渠道流上推进、中断、恢复。通过 channel_flow + render_a2ui 渲染三步卡片完成全部办理过程。
version: "1.0.0"
invocation_policy: auto
group: insurance
tags:
  - withdrawal
  - channel
  - flow
required_tools:
  - channel_flow
  - render_a2ui
---

# 渠道办理技能

调用 `channel_flow(channel, action)` 推进/中断/恢复某渠道的三步办理状态机，
然后立刻调用 `render_a2ui` 渲染 `ChannelStepCard`（除非状态机已 submitted）。

三步：`policy`（保单确认） → `amount`（金额确认） → `bank_card`（银行卡确认）。每步都是一张
卡片，由 `_channel_flows` 驱动；LLM 只传 `channel`，不传步骤数据。

## 触发门禁（同时满足才启用）

1. 最近 `render_a2ui` digest 含 `[卡片:方案 …]` **或** `[卡片:渠道步骤 …]` **或**
   `[渠道流:…]`（即用户已经看到方案卡或正处于办理流程）
2. 用户消息为下列之一：
   - 含办理类动词 + 渠道名（"领生存金"、"办贷款"、"办红利"）
   - 按钮 query：以 `__channel_step__:` 前缀开头
   - 中断/继续/暂停/回到 类语义
3. 渠道 ∈ `{survival_fund, bonus, policy_loan}`（partial_withdrawal / surrender 不走此技能）

任一不满足 → 由「保险取款」接管。

## 渠道 ID 对照

| 用户说法 | channel |
|---------|---------|
| 生存金 | `survival_fund` |
| 红利 | `bonus` |
| 贷款 / 保单贷款 | `policy_loan` |

## 决策树（从上到下，命中即停）

> **总规则**：每一步都是「调 `channel_flow` 改状态 → 调 `render_a2ui ChannelStepCard` 渲染对应渠道」。
> 唯一例外是 `confirm_bank` 完成后状态变 `submitted`，不再渲染该渠道的步骤卡。

### STEP 0 — 按钮 query 快速路径

用户消息形如 `__channel_step__:<channel>:<action>`，action 直接传入工具：

| action | 含义 |
|---|---|
| `confirm_policy` / `confirm_amount` / `confirm_bank` | 推进到下一步 |
| `back` | 后退一步（amount→policy；bank_card→amount，自动清掉 bank_card） |
| `interrupt` | 暂停当前 active 渠道 |

执行完 `channel_flow` 后：
- 非 `confirm_bank` → `render_a2ui` 渲染 `ChannelStepCard`（同 channel）显示新状态
- `confirm_bank` → 不再出该渠道卡片；如 digest `remaining=[…]` 非空，一句引导
  「还有红利和贷款待办，继续吗？」（≤25 字）

### STEP 0.5 — 自然语言推进 / 后退（聊天驱动）

用户没有点按钮，而是直接打字，从最近 `[卡片:渠道步骤 channel=X step=Y]` 或
`[渠道流:… channel=X step=Y]` digest 读出当前 X 和 Y，按下表映射：

| 用户消息 | 当前 step=Y | 调用 |
|---|---|---|
| 下一步 / 继续 / 好 / 嗯 / OK | policy | `channel_flow(X, confirm_policy)` |
| 下一步 / 继续 / 确认 / 好 | amount | `channel_flow(X, confirm_amount)` |
| 确认 / 确认提交 / 提交 / 好 | bank_card | `channel_flow(X, confirm_bank)` |
| 上一步 / 返回 / 改一下 | amount / bank_card | `channel_flow(X, back)` |
| 上一步 | policy | 拒绝；回复「这是第 1 步，没有上一步」（不调工具） |

执行后**仍然 `render_a2ui` ChannelStepCard(channel=X)**，因为「聊天每一步都要出新卡显示
最新状态」。例外仍是 `confirm_bank`——状态变 done 后不再出卡。

### STEP 1 — 中断 / 暂停意图

用户说「先办其他」「中断」「停一下」时，从最近 `[渠道流:启动/恢复/推进 channel=X step=…]`
digest 读出当前 active channel X：

```
channel_flow(X, interrupt)
```

不再渲染卡片；一句引导「已暂停 X 办理，您想办哪个？」。

### STEP 2 — 启动 / 切换 / 恢复

用户消息含「办理 / 领 / 取 / 继续 / 回到」+ 渠道 Y：

```
channel_flow(Y, start)        # 已存在则保留 step；否则从 step=policy 开始
                              # 工具自动暂停其他 active 渠道
render_a2ui ChannelStepCard(channel=Y)
```

特别注意 `action=start` 同时承担两种语义：
- 新渠道首次启动
- 已 paused 渠道恢复（保留中断时的 step）

LLM 不需要区分这两种情况——`channel_flow` 会自己判断。

### STEP 3 — 仅渲染

用户消息没有任何状态变更意图（如「这是哪一步？」「显示一下」），但 digest 中
`active_channel=X` 存在：

```
render_a2ui ChannelStepCard(channel=X)
```

不调 `channel_flow`。

---

## 正例

### 例 1：方案卡 → 用户领生存金 → 完整三步

```
digest: [卡片:方案 title="★ 推荐: 生存金领取" channels=[survival_fund] total=10000.00] 生存金 ¥10,000.00

用户: "领生存金"
助手:
  → channel_flow(survival_fund, start)
  → render_a2ui ChannelStepCard(channel=survival_fund)
  ↳ digest: [卡片:渠道步骤 channel=survival_fund step=policy status=active]

用户点按钮 → query: __channel_step__:survival_fund:confirm_policy
助手:
  → channel_flow(survival_fund, confirm_policy)
  → render_a2ui ChannelStepCard(channel=survival_fund)
  ↳ digest: [卡片:渠道步骤 channel=survival_fund step=amount status=active]

用户点按钮 → query: __channel_step__:survival_fund:confirm_amount
助手:
  → channel_flow(survival_fund, confirm_amount)
  → render_a2ui ChannelStepCard(channel=survival_fund)
  ↳ digest: [卡片:渠道步骤 channel=survival_fund step=bank_card status=active]

用户点按钮 → query: __channel_step__:survival_fund:confirm_bank
助手:
  → channel_flow(survival_fund, confirm_bank)
  ↳ digest: [渠道流:已提交 channel=survival_fund remaining=[]]
  回复: "生存金领取已完成。"
```

### 例 2：中断 + 切换 + 恢复

```
digest: [卡片:方案 ... channels=[bonus,survival_fund,policy_loan] total=10000.00]
用户: "领红利"
助手 → channel_flow(bonus, start) → render ChannelStepCard(bonus)

用户在 step=amount 时说: "我先办贷款"
助手 → channel_flow(bonus, interrupt)
     → channel_flow(policy_loan, start)
     → render ChannelStepCard(policy_loan)

用户走完 policy_loan 的三步：confirm_bank 后 digest:
[渠道流:已提交 channel=policy_loan remaining=[bonus]]
助手回复: "保单贷款已完成。还有红利办理中，继续吗？"

用户: "继续红利"
助手 → channel_flow(bonus, start)   # 自动恢复到 step=amount
     → render ChannelStepCard(bonus)
```

### 例 3：单纯中断

```
digest: [卡片:渠道步骤 channel=bonus step=amount status=active]
用户: "等会儿"（没有指明要办其他渠道）
助手 → channel_flow(bonus, interrupt)
     回复: "已暂停红利办理，需要时随时回来。"
```

### 例 4：聊天驱动「下一步」「上一步」

```
digest: [卡片:渠道步骤 channel=bonus step=amount status=active]

用户: "下一步"   # 聊天，没有点按钮
助手:
  → channel_flow(bonus, confirm_amount)
  → render_a2ui ChannelStepCard(channel=bonus)   # 出新卡显示 step=bank_card

用户: "上一步"   # 聊天
助手:
  → channel_flow(bonus, back)                    # bank_card → amount，bank_card 字段被清
  → render_a2ui ChannelStepCard(channel=bonus)   # 出新卡显示 step=amount

用户: "确认"
助手（当前 step=amount，"确认" 在该 step 等同 "下一步"）:
  → channel_flow(bonus, confirm_amount)
  → render_a2ui ChannelStepCard(channel=bonus)   # step=bank_card

用户: "确认提交"
助手（当前 step=bank_card）:
  → channel_flow(bonus, confirm_bank)
  ↳ digest: [渠道流:已提交 channel=bonus remaining=[]]
  回复: "红利领取已完成。"
```

### 例 5：在 step=policy 时说「上一步」

```
digest: [卡片:渠道步骤 channel=bonus step=policy status=active]
用户: "上一步"
助手（按 STEP 0.5 规则，policy 没有上一步）:
  回复: "这是第 1 步，没有上一步。"
  # 不调 channel_flow，不重渲染卡片
```

---

## 反例（禁止）

### 反例 1：不传 action 直接渲染卡片

```
用户: "领生存金"
❌ 直接 render_a2ui ChannelStepCard(channel=survival_fund)
   会导致状态机未初始化，ChannelStepCard 找不到 _channel_flows[survival_fund] 返回空。
✅ 先 channel_flow(survival_fund, start)，再 render_a2ui。
```

### 反例 2：confirm_bank 后还渲染该渠道卡片

```
工具结果: [渠道流:已提交 channel=bonus remaining=[]]
❌ 又调 render_a2ui ChannelStepCard(channel=bonus)
   该渠道 step=done，builder 会返回空。
✅ 不渲染；一句话告知完成。
```

### 反例 3：硬塞 step 参数

```
❌ render_a2ui ChannelStepCard(channel=bonus, step=amount)
   step 应由 _channel_flows 决定，LLM 强行指定可能与状态机不一致。
✅ render_a2ui ChannelStepCard(channel=bonus)，让 builder 从 state 读 step。
```

### 反例 4：跳步推进

```
当前 digest: [卡片:渠道步骤 channel=bonus step=policy status=active]
❌ channel_flow(bonus, confirm_amount)   # 跳过 confirm_policy
   工具会返回错误 "step=policy 无法执行 confirm_amount"。
✅ 按用户实际点的按钮 action 来。
```

---

## 禁止事项

- **禁止**调用 `rule_engine` / `submit_withdrawal` / `customer_info` / `policy_query`
- **禁止**自己编造保单号、金额、银行卡——所有字段从 `_channel_flows` 状态读取
- **禁止**在文字回复中重复卡片中的金额、保单号、银行卡——卡片已展示
- **禁止**在 confirm_bank 后再渲染该渠道的 ChannelStepCard
- **禁止**用 Markdown 表格/列表代替 ChannelStepCard
- 卡片后文字回复 ≤25 字
