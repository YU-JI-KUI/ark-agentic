---
enabled: False
name: 保险取款
description: 取款的完整生命周期：查询可取金额、生成方案（PlanCard）、调整方案、三步办理（保单→金额→银行卡）、中断与恢复。覆盖渠道：生存金、红利、保单贷款（三步），以及部分领取、退保（仅出方案）。
version: "3.1.0"
invocation_policy: auto
group: insurance
tags:
  - withdrawal
  - insurance
  - financial
required_tools:
  - rule_engine
  - render_a2ui
  - channel_flow
---

# 保险取款

工作方式：**根据 digest 推断 PHASE，根据用户消息推断 intent，对照分发表调工具**。

---

## 第 0 步：PHASE（读最近一条 digest 的前缀）

| digest 前缀                                       | PHASE          |
|---------------------------------------------------|----------------|
| 无 / 仅历史聊天                                    | `INIT`         |
| `[卡片:总览/合计`、`[卡片:总览/板块`              | `POST_SUMMARY` |
| `[卡片:方案 …`                                    | `POST_PLAN`    |
| `[卡片:渠道步骤 …`、`[渠道流:…`                  | `IN_FLOW`      |

**单字段查询，不要自由心证**。倒序找第一条匹配的。

---

## 第 1 步：解析用户消息成结构化输出

输出 4 个字段（仅在心里推理，**不要写进回复**）：

```
intent       6 选 1（见下表）
params       从消息抽出的参数
pending      复合意图剩余子意图列表
confidence   high | low；low → 不动状态、反问澄清
```

### 6 个 intent

| intent       | 触发样例 |
|--------------|---------|
| `ASK_AMOUNT` | "能取多少"、"帮我看看"（无金额、无办理动词、无渠道） |
| `MAKE_PLAN`  | "取 5 万"、"领生存金"、"贷款 3 万"（含金额或单渠道+办理动词） |
| `ADJUST_PLAN`| "换方案"、"少取"、"多取"、"不要贷款"（仅 POST_PLAN/IN_FLOW 有效） |
| `ACCEPT_PLAN`| 光秃秃接受："确认"、"好"、"好的"、"是的"、"可以"、"就这个"、"对"、"成"、"行" |
| `FLOW_OP`    | "下一步"、"上一步"、"继续"、"暂停"、"中断"、按钮 query (`__channel_step__:` 开头) |
| `OFF_TOPIC`  | 其他（寒暄、问别的产品、问理赔等） |

### params 字段

| 字段                  | 类型           | 来源 |
|-----------------------|---------------|------|
| `target_amount`       | 数字 \| null   | "5万" → 50000；负数则不调工具直接回复"金额需为正" |
| `explicit_channels`   | list \| null  | 显式提到要办的渠道 |
| `excluded_channels`   | list \| null  | "别动 X"、"不要 Y"——传给 PlanCard 时从 channels 移除 |
| `picked_channel`      | channel \| null | POST_PLAN 多渠道追问后用户挑的 |
| `flow_action`         | enum \| null  | FLOW_OP 时（confirm_*/back/interrupt） |

### 边缘消息（按表先处理，再做 intent 分类）

| # | 类型 | 例 | 规则 |
|---|---|---|---|
| 1 | **复合意图** | "确认生存金然后看看红利" | 按 `,` `；` `然后` `再` `并` `顺便` `还要` 拆；本轮处理第 1 个，其余进 `pending`，回复末尾追加 "下一步帮您 X" |
| 2 | **意图+约束** | "取5万但别动贷款" | 主 intent + `excluded_channels`/`explicit_channels` 抽出来 |
| 3 | **自我修正** | "取5万等等10万" | 取最右侧值 |
| 4 | **闲聊+意图** | "今天好热啊取5万" / "贷款利率多少？取5万" | 闲聊不为主→处理意图忽略闲聊；闲聊与产品相关→本轮答闲聊，意图入 `pending` |
| 5 | **犹豫语气** | "可能取5万吧" / "再想想" | 犹豫修饰不影响动作；裸"再想想"/"算了" → OFF_TOPIC（INIT 阶段）/ FLOW_OP=interrupt（IN_FLOW 阶段） |
| 6 | **指代历史** | "用刚才那个方案" | 翻历史找 `[卡片:方案 …]`；找到 → `ACCEPT_PLAN`；找不到 → confidence=low 反问 |
| 7 | **真歧义** | 无前文的"好" | confidence=low → **不调工具**，反问"您是说 X 还是 Y？" |

---

## 第 2 步：PHASE × intent → 动作分发表

| PHASE          | intent         | 动作 |
|----------------|----------------|------|
| `INIT`         | `ASK_AMOUNT`   | 走「SUMMARY」 |
| `INIT`         | `MAKE_PLAN`    | 走「MAKE_PLAN」 |
| `INIT`         | `ACCEPT_PLAN`  | 反问："您想查询额度还是直接取款？" |
| `INIT`         | `FLOW_OP`/`ADJUST_PLAN` | 反问："还没有进行中的办理。"/"还没有方案可调整。" |
| `POST_SUMMARY` | `MAKE_PLAN`    | 走「MAKE_PLAN」 |
| `POST_SUMMARY` | `ASK_AMOUNT`   | 走「SUMMARY」（按筛选词） |
| `POST_SUMMARY` | `ACCEPT_PLAN`  | 反问："您想取多少？" |
| `POST_PLAN`    | `ACCEPT_PLAN`  | 走「ACCEPT_PLAN」 |
| `POST_PLAN`    | `MAKE_PLAN`    | 渠道明确 → `channel_flow(X, start)`；金额变更 → 走「ADJUST_PLAN」 |
| `POST_PLAN`    | `ADJUST_PLAN`  | 走「ADJUST_PLAN」 |
| `POST_PLAN`    | `FLOW_OP`      | 解释："请先选定方案。" |
| `IN_FLOW`      | `FLOW_OP`      | 走「FLOW_OP」 |
| `IN_FLOW`      | `MAKE_PLAN`    | 切换到指定渠道：`channel_flow(X, start)` （工具自动暂停其他） |
| `IN_FLOW`      | `ACCEPT_PLAN`  | 等价 FLOW_OP confirm（按当前 step） |
| `IN_FLOW`      | `ADJUST_PLAN`  | 走「ADJUST_PLAN」（自动 interrupt 当前渠道） |
| **任意**        | `OFF_TOPIC`    | **不调工具**，正常回答，状态保持 |

---

## 子流程：SUMMARY

`rule_engine(action="list_options")` + `render_a2ui` 渲染：

```json
[
  {"type":"WithdrawSummaryHeader","data":{"sections":["zero_cost","loan","partial_withdrawal","surrender"]}},
  {"type":"WithdrawSummarySection","data":{"section_name":"zero_cost"}}
]
```

筛选语映射：

| 筛选 | sections |
|---|---|
| 默认 | `["zero_cost","loan","partial_withdrawal","surrender"]` |
| 零成本 / 不影响保障 | `["zero_cost"]` |
| 只看红利 / 生存金 | `["bonus"]` / `["survival_fund"]` |
| 不看贷款 | `["zero_cost","partial_withdrawal","surrender"]` |
| 不看退保 | `["zero_cost","loan"]` |

---

## 子流程：MAKE_PLAN

`rule_engine(list_options)` 后出 PlanCard：

**Plan A（推荐）**：按优先级 `[survival_fund, bonus, partial_withdrawal, policy_loan, surrender]` 依次纳入，累计 ≥ target 即停。

特例：
- 用户显式指定 channels → 直接用，不跑优先级
- target=0 / 渠道定向（"领生存金"无金额）→ channels=单渠道, target=0
- target > grand → channels=全渠道, target=grand，**不出 Plan B**
- `params.excluded_channels` 非空 → 从 channels 列表移除这些

**Plan B（备选）**：把 Plan A 最低优先级渠道替换为下一非零渠道；替换后累计 < target 则**放弃**。

调用：

```json
[
  {"type":"WithdrawPlanCard","data":{"channels":["survival_fund"],"target":10000,"is_recommended":true}},
  {"type":"WithdrawPlanCard","data":{"channels":["bonus","partial_withdrawal"],"target":10000,"is_recommended":false}}
]
```

> 不要传 title/tag/tag_color——引擎反推。多个 PlanCard **必须**同次调用。

### 渠道 ID

| 用户说法 | channel ID |
|---|---|
| 生存金 | `survival_fund` |
| 红利   | `bonus` |
| 贷款 / 保单贷款 | `policy_loan` |
| 部分领取 | `partial_withdrawal` |
| 退保 | `surrender` |

---

## 子流程：ADJUST_PLAN

1. 从最近 `[卡片:方案 …]` digest 读 `channels=[…]` 和 `total=…` 作为基线
2. 应用变更：

| 用户说 | 变更 |
|---|---|
| "多取一点，总共 8 万" | target=80000 |
| "不要贷款" | channels 移除 `policy_loan` |
| "不退保" | channels 移除 `surrender` |
| "只用不影响保障的" | channels=`["survival_fund","bonus"]` |
| "不要 POL002" | exclude_policies=`["POL002"]` |

3. 重新 `rule_engine(list_options)` + `render_a2ui` 出新 PlanCard

> IN_FLOW 阶段调整：先 `channel_flow(active_channel, interrupt)`，再走 ADJUST。

---

## 子流程：ACCEPT_PLAN

读最近 `[卡片:方案 channels=[A,B,C] …]`：

1. 过滤到 3 步覆盖渠道 `{survival_fund, bonus, policy_loan}`
2. 分支：

| 过滤后 | 动作 |
|---|---|
| 1 个 X | `channel_flow(channel=X, action=start)` |
| >1 个 | **不调工具**，回复："本方案含 N 项，您想先办哪个？" 列出渠道+金额（每行 ≤15 字） |
| 0 个 | 回复："当前方案不含三步办理渠道，需走外部流程。" |

如有 `params.picked_channel`（用户已指明）→ 直接 `channel_flow(picked_channel, start)`。

---

## 子流程：FLOW_OP

从最近 digest 读**单字段** `active_channel=X`、`step=Y`：

| 用户消息 / 按钮 | 调用 |
|---|---|
| `__channel_step__:Z:A` | `channel_flow(channel=Z, action=A)` 直传 |
| 下一步 / 继续 / 确认 / 提交 | `channel_flow(X, confirm_<Y>)` 按当前 step |
| 上一步 / 返回 | `channel_flow(X, back)`；step=policy 时**不调工具**，回"这是第 1 步" |
| 暂停 / 中断 / 等会儿 | `channel_flow(X, interrupt)` |
| 回到 Z / 继续 Z（Z≠X）| `channel_flow(Z, start)` （工具自动暂停 X） |

---

## 错误处理

`channel_flow` / `rule_engine` 返回 `is_error=true`：

| 错误片段 | 处理 |
|---|---|
| `step=X 无法执行 Y` | 读最近 digest 校正 step，按正确 action 重试 1 次 |
| `无法后退` | 回："这是第 1 步，没有上一步。" 不重试 |
| `没有进行中的办理` / `流程未启动` | 改 `action=start` 重试 1 次 |
| `已提交` | 回："该渠道已办完，新办需先生成新的取款方案。" |
| `在当前方案中没有分配` | 回："当前方案里没有该渠道的额度。" |
| `不支持的渠道` | 回："仅支持生存金、红利、保单贷款的三步办理。" |

最多 1 次重试；仍失败 → 告知当前状态，不再调工具。

---

## 输出约束

1. 展示取款数据**必须**调 `render_a2ui` 或 `channel_flow`（自带卡）。**禁止** Markdown 表格、列表、纯文本替代
2. **禁止** 复述卡片中的金额、渠道名、保单号、银行卡
3. 卡片后回复 ≤25 字
4. 工具调用时只生成 tool_call，不附额外文本
5. 多个 PlanCard **必须**同次 `render_a2ui` 调用（blocks 数组）
6. 不要传 PlanCard 的 title/tag/tag_color
7. **不要在回复里写任何 HTML 注释**

### 卡片后回复模板

| 工具结果 | 回复 |
|---|---|
| start（新建） | "请确认保单。" |
| start（恢复） | "已恢复办理。" |
| confirm_policy 后 | "请确认金额。" |
| confirm_amount 后 | "请确认银行卡。" |
| back 到 amount/policy | "已返回金额确认。" / "已返回保单确认。" |
| confirm_bank 完成（无 remaining） | "<渠道>办理已完成。" |
| confirm_bank 完成（有 remaining） | "<渠道>已完成，还有<列表>待办。" |
| interrupt | "已暂停<渠道>，需要时随时回来。" |

---

## 关键正例

### 例 1：INIT → MAKE_PLAN

```
用户："取 1 万"
助手: rule_engine(list_options) + render_a2ui([WithdrawPlanCard(channels=[survival_fund],target=10000,is_recommended=true)])
回复："请确认方案。"
```

### 例 2：POST_PLAN（单渠道）→ ACCEPT_PLAN（光秃秃确认 = 修复重复确认死循环）

```
最近 digest: [卡片:方案 channels=[survival_fund] total=10000]
用户："好"  或 "确认"  或 "就这个"
助手: channel_flow(channel=survival_fund, action=start)
回复："请确认保单。"
```

### 例 3：POST_PLAN（多渠道）→ ACCEPT_PLAN

```
最近 digest: [卡片:方案 channels=[survival_fund,bonus] total=17200]
用户："确认"
助手: 不调工具
回复："本方案含两项，您想先办哪个？
       1. 生存金 ¥12,000
       2. 红利 ¥5,200"

用户："先办生存金"
助手: channel_flow(channel=survival_fund, action=start)
```

### 例 4：IN_FLOW（按钮）

```
最近 digest: [卡片:渠道步骤 channel=bonus step=amount active_channel=bonus]
用户消息: "__channel_step__:bonus:confirm_amount"
助手: channel_flow(channel=bonus, action=confirm_amount)
回复："请确认银行卡。"
```

### 例 5：IN_FLOW → MAKE_PLAN（中途切换）

```
最近 digest: [渠道流:推进 channel=bonus step=amount active_channel=bonus]
用户："我先办贷款"
助手: channel_flow(channel=policy_loan, action=start)  # 工具自动 pause bonus
回复："请确认保单。"
```

### 例 6：边缘 — 意图 + 排除约束

```
用户："取 5 万但别动贷款"
解析：target_amount=50000，excluded_channels=[policy_loan]
助手: rule_engine + render_a2ui([WithdrawPlanCard(channels=[survival_fund,bonus,partial_withdrawal],target=50000,is_recommended=true)])
       # channels 不含 policy_loan
```

### 例 7：边缘 — 复合意图

```
用户："确认生存金然后看看红利还能取多少"
解析：第 1 个 ACCEPT_PLAN(picked=survival_fund)；pending=[ASK_AMOUNT]
助手: channel_flow(channel=survival_fund, action=start)
回复："请确认保单。下一步帮您查红利额度。"
```

### 例 8：边缘 — 真歧义反问

```
PHASE=POST_SUMMARY，用户："好"
解析：上下文无方案，"好"在此无明确动作 → confidence=low
助手: 不调工具
回复："您是想直接取款，还是再看看其他渠道？"
```

### 例 9：边缘 — OFF_TOPIC 不动状态

```
最近 digest: [卡片:渠道步骤 channel=bonus step=amount active_channel=bonus]
用户："今天天气怎么样"
助手: 不调工具
回复："抱歉这个我不太清楚，您可以继续办理红利领取。"
```

---

## 反例（合并到一处对照）

| 错误做法 | 正确做法 |
|---|---|
| 把 IN_FLOW 阶段单字"好"自动当 confirm（用户可能只是寒暄） | 看上下文：助手刚发完卡 → 推进；上一轮没询问 → confidence=low 反问 |
| 不读 digest 凭语义嗅觉 | 永远先 PHASE 字段查询 |
| 复述卡片金额/保单号 | 套用回复模板 ≤25 字 |
| POST_PLAN 阶段调 `channel_flow(?, confirm_policy)`（流程没启动） | 解释"请先选定方案" |
| 分多次调 `render_a2ui([PlanCardA])` 再 `render_a2ui([PlanCardB])` | 一次调用 blocks 数组 |
| OFF_TOPIC 时调 interrupt 干扰 state | 只回答，state 保持 |
| 写 `<!--phase=...-->` 注释（已废弃，会泄露给用户） | 不写注释，靠 tool_call + reply 自身可观测 |
| confirm_bank 后再 `start` 同渠道 | 回："该渠道已办完，新办需先生成新方案。" |
