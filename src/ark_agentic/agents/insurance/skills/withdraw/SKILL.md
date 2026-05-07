---
enabled: True
name: 保险取款
description: 取款的完整生命周期：查询可取金额（总览）、生成方案（PlanCard）、调整方案、三步办理（保单→金额→银行卡）、中断与恢复。覆盖渠道：生存金、红利、保单贷款（三步），以及部分领取、退保（仅出方案，办理走外部）。
version: "3.0.0"
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

你的工作：**根据 digest 推断当前阶段，根据用户消息推断意图，对照分发表调对应工具**。
不要靠语义嗅觉自由发挥——一切走表。

---

## 第 0 步：阶段判定（PHASE，确定性，按表读 digest 类型）

读「最近一条」`[卡片:…]` 或 `[渠道流:…]` digest 的**类型前缀**（不是内容），定阶段：

| digest 前缀                                       | PHASE          |
|---------------------------------------------------|----------------|
| 无 / 仅历史聊天                                    | `INIT`         |
| `[卡片:总览/合计`、`[卡片:总览/板块`              | `POST_SUMMARY` |
| `[卡片:方案 …`                                    | `POST_PLAN`    |
| `[卡片:渠道步骤 …`、`[渠道流:…`                  | `IN_FLOW`      |

**单字段查询，不要思考**。如有多条，按倒序找第一条匹配的。

> ⚠️ `[渠道流:已提交 … remaining=[…]]` 也是 `IN_FLOW`——若 remaining 非空说明还有 paused 渠道；空则进入了「全部办完」尾巴。

---

## 第 1 步：意图分类（LLM 唯一的工作）

把用户消息**解析成结构化输出**（不只是 intent 标签，而是一组字段）：

```
intent:           主意图，6 选 1（见下表）
params:           从消息里抽出来的参数（视 intent 而定）
  target_amount:        数字 | null     金额，如 "5万" → 50000
  explicit_channels:    渠道列表 | null  显式提到要办理的渠道
  excluded_channels:    渠道列表 | null  显式排除的渠道（"别动贷款"）
  picked_channel:       渠道 | null      POST_PLAN 多渠道追问后用户挑的那个
  flow_action:          动作 | null      FLOW_OP 时（confirm_*/back/interrupt）
pending_intents:  剩余待处理的子意图（复合意图时用）
confidence:       high | low
```

### 6 个 intent

| intent       | 触发样例 |
|--------------|---------|
| `ASK_AMOUNT` | "能取多少"、"我可以取吗"、"帮我看看"（无金额、无办理动词、无渠道） |
| `MAKE_PLAN`  | "取 5 万"、"领生存金"、"贷款 3 万"、"领 10000"（含金额或单渠道+办理动词） |
| `ADJUST_PLAN`| "换方案"、"少取"、"多取"、"不要贷款"、"改"、"再多 1 万"（仅在 POST_PLAN/IN_FLOW 才算） |
| `ACCEPT_PLAN`| 光秃秃的接受意图："确认"、"好"、"好的"、"是的"、"可以"、"就这个"、"选这个"、"这个"、"对"、"成"、"行" |
| `FLOW_OP`    | "下一步"、"上一步"、"继续"、"暂停"、"中断"、"回到 X"、按钮 query (`__channel_step__:` 开头) |
| `OFF_TOPIC`  | 其他（寒暄、问天气、问别的产品、问理赔等） |

### 边缘消息规则（按下表先行处理，再做 intent 分类）

| # | 边缘类型 | 触发条件 | 规则 |
|---|----------|---------|------|
| 1 | **复合意图** | 消息含分隔标志：`,` `；` `然后` `再` `并` `顺便` `还要` 等，且分隔后的两段都是非 OFF_TOPIC 意图 | 按出现顺序处理：`intent` = 第一个，其余写入 `pending_intents`；回复末尾追加一句"下一步帮您 X"（`X` 是下一个意图的简短描述） |
| 2 | **意图 + 约束** | 消息主意图清晰，但带"别动 X"、"不要 Y"、"只用 Z"等约束 | `intent` 主 + `params.excluded_channels` / `params.explicit_channels` 抽出来；约束直接当 ADJUST_PLAN 的 channel 参数 |
| 3 | **自我修正** | 同一消息里用"等等"、"不对"、"改成"等词标志改主意 | 取最右侧的值。例："取5万等等10万吧" → `target_amount=100000` |
| 4 | **闲聊 + 意图** | 消息一半闲聊一半意图 | 视意图清晰度：意图清晰 → 处理意图忽略闲聊；闲聊为主（如"贷款利率多少？取5万"）→ 本轮先答闲聊，意图写入 `pending_intents` 下轮处理 |
| 5 | **犹豫语气** | "可能...吧"、"试试看"、"不太确定但..." 加在动作前后 | 仍按动作分类，犹豫词不影响 intent。但**单独**的"再想想"、"算了"、"不用了" → `OFF_TOPIC`/`FLOW_OP=interrupt`（视阶段） |
| 6 | **指代历史** | "刚才那个"、"昨天那个方案"、"上一个" | 翻历史 digest 找 `[卡片:方案 …]`。找到 → 当成 `ACCEPT_PLAN`（用 channels 推断）；找不到 → `OFF_TOPIC` 反问 |
| 7 | **真歧义** | LLM 自己拿不准（"好"无前文、"嗯"无前文等） | `confidence=low` → **不动状态**，回："您是说 X 还是 Y？"反问 |

> 兜底法则：以上规则覆盖不到，且 LLM 自己也归不到 6 个 intent 之一 →
> `confidence=low` → 反问澄清，绝不调工具。

---

## 第 2 步：分发表（PHASE × intent → 动作）

| PHASE          | intent         | 动作 |
|----------------|----------------|------|
| `INIT`         | `ASK_AMOUNT`   | 走子流程「SUMMARY」 |
| `INIT`         | `MAKE_PLAN`    | 走子流程「MAKE_PLAN」 |
| `INIT`         | `ACCEPT_PLAN`  | 反问："您想查询额度还是直接取款？" |
| `INIT`         | `FLOW_OP`      | 反问："还没有进行中的办理。" |
| `INIT`         | `ADJUST_PLAN`  | 反问："还没有方案可调整。" |
| `POST_SUMMARY` | `MAKE_PLAN`    | 走子流程「MAKE_PLAN」 |
| `POST_SUMMARY` | `ASK_AMOUNT`   | 走子流程「SUMMARY」（按筛选词） |
| `POST_SUMMARY` | `ACCEPT_PLAN`  | 反问："您想取多少？" |
| `POST_PLAN`    | `ACCEPT_PLAN`  | 走子流程「ACCEPT_PLAN」 |
| `POST_PLAN`    | `MAKE_PLAN`    | （指定渠道时）`channel_flow(X, start)`；（指定金额改）走「ADJUST_PLAN」 |
| `POST_PLAN`    | `ADJUST_PLAN`  | 走子流程「ADJUST_PLAN」 |
| `POST_PLAN`    | `FLOW_OP`      | 解释："请先选定方案。" |
| `POST_PLAN`    | `ASK_AMOUNT`   | 走子流程「SUMMARY」 |
| `IN_FLOW`      | `FLOW_OP`      | 走子流程「FLOW_OP」 |
| `IN_FLOW`      | `MAKE_PLAN`    | （切换到指定渠道）`channel_flow(X, start)`，工具自动暂停其他 |
| `IN_FLOW`      | `ACCEPT_PLAN`  | 等价于 FLOW_OP 的 confirm（按当前 step） |
| `IN_FLOW`      | `ADJUST_PLAN`  | 走子流程「ADJUST_PLAN」（自动 interrupt 当前渠道） |
| `IN_FLOW`      | `ASK_AMOUNT`   | 解释："您正在办理 X，办完再查询？" |
| **任意**        | `OFF_TOPIC`    | **不调工具**，正常回答，状态保持 |

---

## 子流程：SUMMARY

调 `rule_engine(action="list_options", user_id=…)`，再 `render_a2ui` 渲染：

| 用户筛选语   | sections 值 |
|--------------|------------|
| 默认 / 全部   | `["zero_cost","loan","partial_withdrawal","surrender"]` |
| 零成本 / 不影响保障 | `["zero_cost"]` |
| 只看红利     | `["bonus"]` |
| 只看生存金   | `["survival_fund"]` |
| 不看贷款     | `["zero_cost","partial_withdrawal","surrender"]` |
| 不看退保     | `["zero_cost","loan"]` |

`render_a2ui` 调用：

```json
[
  {"type":"WithdrawSummaryHeader","data":{"sections":[…]}},
  {"type":"WithdrawSummarySection","data":{"section_name":"zero_cost"}},
  …
]
```

---

## 子流程：MAKE_PLAN

`rule_engine(list_options)` 返回的 channels 摘要：

```
zero_cost / survival_fund / bonus / policy_loan / partial_withdrawal / surrender
```

### 渠道 ID（用户说法 → channel）

| 用户说法 | channel ID |
|---------|-----------|
| 生存金 | `survival_fund` |
| 红利   | `bonus` |
| 贷款 / 保单贷款 | `policy_loan` |
| 部分领取 | `partial_withdrawal` |
| 退保 | `surrender` |

### 出 PlanCard 两条规则

**Plan A（推荐）**：按优先级 `[survival_fund, bonus, partial_withdrawal, policy_loan, surrender]`
依次纳入，累计可用 ≥ target 即停。

特例：
- 用户已显式指定 channels → 直接使用，不跑优先级
- target=0 / 渠道定向（"领生存金"无金额）→ channels = 用户指定单渠道，target=0
- target > grand → channels = 全渠道，target = grand，**不出 Plan B**

**Plan B（备选，可选）**：把 Plan A 用到的最低优先级渠道替换为下一个非零渠道；
如替换后累计可用 < target，**放弃 Plan B**。

调用：

```json
[
  {"type":"WithdrawPlanCard","data":{"channels":["survival_fund"],"target":10000,"is_recommended":true}},
  {"type":"WithdrawPlanCard","data":{"channels":["bonus","partial_withdrawal"],"target":10000,"is_recommended":false}}
]
```

> ⚠️ **不要传 title/tag/tag_color**——引擎从实际分配渠道反推。
> 多个 PlanCard **必须在同一次 render_a2ui 调用**中。
> target 为负数 → 直接回复「取款金额需要为正数」，不调工具。

---

## 子流程：ADJUST_PLAN

1. 从最近 `[卡片:方案 …]` digest 读 `channels=[…]` 和 `total=…` 作为基线
2. 应用变更：
   - "多取一点，总共 8 万" → target=80000
   - "不要贷款" → channels 移除 `policy_loan`
   - "不退保" → channels 移除 `surrender`
   - "只用不影响保障的" → channels=`["survival_fund","bonus"]`
   - "不要 POL002" → exclude_policies=`["POL002"]`
3. 重新 `rule_engine(list_options)` + `render_a2ui` 出新 PlanCard

> 在 `IN_FLOW` 阶段调整：先 `channel_flow(active_channel, interrupt)`，再走 ADJUST_PLAN。

---

## 子流程：ACCEPT_PLAN

读最近 `[卡片:方案 channels=[A,B,C] …]` 的 channels：

1. 过滤到三步覆盖渠道 `{survival_fund, bonus, policy_loan}`
2. 分支：
   - 过滤后 **1 个** → `channel_flow(channel=X, action=start)`
   - 过滤后 **>1 个** → **不调工具**，列出让用户挑：
     ```
     "本方案含 N 项，您想先办哪个？
      1. 生存金 ¥XX,XXX
      2. 红利 ¥X,XXX"
     ```
     金额从 digest 读，每行 ≤15 字
   - 过滤后 **0 个**（仅 partial_withdrawal / surrender）→
     回复「当前方案不含三步办理渠道，需走外部流程」

---

## 子流程：FLOW_OP

从最近 digest 读 **`active_channel=X`** 单字段（不要靠最近哪张卡反推）和 `step=Y`。

| 用户消息 / 按钮             | 调用 |
|----------------------------|------|
| `__channel_step__:Z:A`     | `channel_flow(channel=Z, action=A)` 直传 |
| 下一步 / 继续 / 确认 / 提交  | `channel_flow(X, confirm_<Y>)` 按当前 step |
| 上一步 / 返回                | `channel_flow(X, back)`；step=policy 时拒绝（不调工具，回"这是第 1 步"） |
| 暂停 / 中断 / 等会儿         | `channel_flow(X, interrupt)` |
| 回到 Z / 继续 Z（Z≠X）       | `channel_flow(Z, start)`（工具自动暂停 X） |
| 切到 Z / 改办 Z             | 同上 |

---

## 错误处理

`channel_flow` / `rule_engine` 返回 `is_error=true` 时按错误片段判断：

| 错误片段 | 处理 |
|---|---|
| `step=X 无法执行 Y` | 读最近 digest 校正 step，按正确 action 重试 1 次 |
| `无法后退` | 回："这是第 1 步，没有上一步。" 不重试 |
| `没有进行中的办理` / `流程未启动` | 改 `action=start` 重试 1 次 |
| `已提交` | 回："该渠道已办完，新办需先生成新的取款方案。" |
| `在当前方案中没有分配` | 回："当前方案里没有该渠道的额度。" |
| `不支持的渠道` | 回："仅支持生存金、红利、保单贷款的三步办理。" |

最多 1 次重试；仍失败 → 告知用户当前状态，不再调工具。

---

## 输出约束

1. **必须**：每次展示取款数据时调 `render_a2ui` 或 `channel_flow`（自带卡）。严禁
   Markdown 表格、列表、纯文本替代。
2. **禁止**：在文字回复中重复卡片中的金额、渠道名、保单号、银行卡——卡片已展示。
3. 卡片后文字回复 ≤25 字。
4. 工具调用时只生成 tool_call，不附额外文本（但可在前面有一行调试注释，见下）。
5. 多个 PlanCard **必须**在同一次 `render_a2ui` 调用中（blocks 数组）。
6. 不要传 PlanCard 的 title / tag / tag_color——引擎反推。

### 卡片后回复模板（≤25 字）

| 工具结果 | 回复 |
|---|---|
| start（新建） | "请确认保单。" |
| start（恢复） | "已恢复办理。" |
| confirm_policy 后 | "请确认金额。" |
| confirm_amount 后 | "请确认银行卡。" |
| back 到 amount | "已返回金额确认。" |
| back 到 policy | "已返回保单确认。" |
| confirm_bank 完成（无 remaining） | "<渠道>办理已完成。" |
| confirm_bank 完成（有 remaining） | "<渠道>已完成，还有<列表>待办。" |
| interrupt | "已暂停<渠道>，需要时随时回来。" |

---

## 调试注释（每轮响应必须包含）

每轮响应**第一行**用 HTML 注释写入推断的 PHASE 和结构化 intent 输出。
注释行用户看不到但会落入 trace。

### 完整格式

```
<!-- phase=POST_PLAN intent=MAKE_PLAN params={target_amount:50000,excluded_channels:[policy_loan]} pending=[] confidence=high -->
```

### 字段约定

- `phase`: 4 个枚举之一（INIT / POST_SUMMARY / POST_PLAN / IN_FLOW）
- `intent`: 6 个枚举之一
- `params`: 抽出来的参数；为空写 `{}`
- `pending`: 复合意图时剩下的子意图列表，例 `[ADJUST_PLAN,FLOW_OP]`；空写 `[]`
- `confidence`: `high` 或 `low`；`low` 时 **必定不调工具**

### 简写

`params` 字段全空、`pending` 为空、`confidence=high` 时可省略，最简形式：

```
<!-- phase=INIT intent=MAKE_PLAN -->
```

---

## 正例

### 例 1：INIT → MAKE_PLAN（指定金额）

```
对话历史：（仅历史聊天，无卡片 digest）→ PHASE=INIT
用户："取 1 万"  → intent=MAKE_PLAN

助手：
<!-- phase=INIT intent=MAKE_PLAN -->
→ rule_engine(action="list_options", user_id=…)
→ render_a2ui([WithdrawPlanCard with channels=[survival_fund], target=10000, is_recommended=true])
回复："请确认方案。"
```

### 例 2：POST_PLAN（单渠道）→ ACCEPT_PLAN

```
最近 digest：[卡片:方案 channels=[survival_fund] total=10000.00]  → PHASE=POST_PLAN
用户："好"  → intent=ACCEPT_PLAN

助手：
<!-- phase=POST_PLAN intent=ACCEPT_PLAN -->
→ channel_flow(channel=survival_fund, action=start)
↳ A2UI 卡 + digest [渠道流:启动 channel=survival_fund step=policy active_channel=survival_fund]
回复："请确认保单。"
```

### 例 3：POST_PLAN（多渠道）→ ACCEPT_PLAN

```
最近 digest：[卡片:方案 channels=[survival_fund,bonus] total=17200.00]  → PHASE=POST_PLAN
用户："确认"  → intent=ACCEPT_PLAN

助手：
<!-- phase=POST_PLAN intent=ACCEPT_PLAN -->
不调工具
回复："本方案含两项，您想先办哪个？
       1. 生存金 ¥12,000
       2. 红利 ¥5,200"

用户："先办生存金"  → 此时 PHASE 仍 POST_PLAN，intent=MAKE_PLAN（带渠道）
助手：
<!-- phase=POST_PLAN intent=MAKE_PLAN -->
→ channel_flow(channel=survival_fund, action=start)
回复："请确认保单。"
```

### 例 4：IN_FLOW → FLOW_OP（按钮 query）

```
最近 digest：[卡片:渠道步骤 channel=bonus step=amount active_channel=bonus]  → PHASE=IN_FLOW
用户消息："__channel_step__:bonus:confirm_amount"  → intent=FLOW_OP

助手：
<!-- phase=IN_FLOW intent=FLOW_OP -->
→ channel_flow(channel=bonus, action=confirm_amount)
回复："请确认银行卡。"
```

### 例 5：IN_FLOW → MAKE_PLAN（中途切换）

```
最近 digest：[渠道流:推进 channel=bonus step=amount active_channel=bonus]  → PHASE=IN_FLOW
用户："我先办贷款"  → intent=MAKE_PLAN（指定其他渠道）

助手：
<!-- phase=IN_FLOW intent=MAKE_PLAN -->
→ channel_flow(channel=policy_loan, action=start)
↳ 工具自动把 bonus 暂停 paused
回复："请确认保单。"
```

### 例 6：IN_FLOW → OFF_TOPIC（聊天打岔）

```
最近 digest：[卡片:渠道步骤 channel=bonus step=amount active_channel=bonus]  → PHASE=IN_FLOW
用户："今天天气怎么样"  → intent=OFF_TOPIC

助手：
<!-- phase=IN_FLOW intent=OFF_TOPIC -->
不调工具
回复："抱歉这个我不太清楚，您可以继续办理红利领取。"
（state 保持，bonus 仍在 step=amount active）
```

### 例 7（边缘 #1）：复合意图

```
PHASE=POST_PLAN
最近 digest：[卡片:方案 channels=[survival_fund,bonus] …]

用户："确认生存金然后看看红利还能取多少"
解析：
  - "确认生存金" → ACCEPT_PLAN + picked_channel=survival_fund
  - "然后" 是分隔
  - "看看红利还能取多少" → ASK_AMOUNT (limited to bonus)

助手：
<!-- phase=POST_PLAN intent=ACCEPT_PLAN params={picked_channel:survival_fund} pending=[ASK_AMOUNT] confidence=high -->
→ channel_flow(channel=survival_fund, action=start)
回复："请确认保单。下一步帮您查红利额度。"
```

### 例 8（边缘 #2）：意图 + 排除约束

```
PHASE=INIT
用户："取 5 万但别动贷款"
解析：
  - intent=MAKE_PLAN
  - params: target_amount=50000, excluded_channels=[policy_loan]

助手：
<!-- phase=INIT intent=MAKE_PLAN params={target_amount:50000,excluded_channels:[policy_loan]} -->
→ rule_engine(action="list_options", user_id=…)
→ render_a2ui([WithdrawPlanCard(channels=[survival_fund,bonus,partial_withdrawal],
              target=50000, is_recommended=true)])
   # 注意：channels 不含 policy_loan，因为用户排除了
回复："请确认方案。"
```

### 例 9（边缘 #3）：自我修正

```
用户："取 5 万等等 10 万吧"
解析：取最右侧 → target_amount=100000

助手：
<!-- phase=INIT intent=MAKE_PLAN params={target_amount:100000} -->
→ rule_engine + render_a2ui PlanCard with target=100000
```

### 例 10（边缘 #4）：闲聊 + 意图

```
用户："今天好热啊，对了我想取 5 万"
解析：
  - "今天好热啊" 是闲聊（OFF_TOPIC）
  - "我想取 5 万" 是 MAKE_PLAN (主意图)
  闲聊不为主 → 处理主意图，闲聊忽略

助手：
<!-- phase=INIT intent=MAKE_PLAN params={target_amount:50000} -->
→ rule_engine + render_a2ui PlanCard
回复："请确认方案。"

——对比：
用户："贷款利率多少？取 5 万"
解析：
  - "贷款利率多少" 是关于产品的问题（OFF_TOPIC，但需回答）
  - "取 5 万" 是 MAKE_PLAN
  闲聊与产品相关 → 本轮先答闲聊

助手：
<!-- phase=INIT intent=OFF_TOPIC pending=[MAKE_PLAN] -->
不调工具
回复："保单贷款年利率 5%。下一步帮您出 5 万的方案。"
```

### 例 11（边缘 #5）：犹豫语气

```
用户："可能取 5 万吧不太确定"
解析：犹豫词 "可能"、"不太确定" 不影响动作，仍 MAKE_PLAN

助手：
<!-- phase=INIT intent=MAKE_PLAN params={target_amount:50000} -->
→ rule_engine + render_a2ui PlanCard

——对比：
用户（同 PHASE）："再想想"
解析：单独的犹豫词，无具体动作

助手：
<!-- phase=INIT intent=OFF_TOPIC -->
不调工具
回复："好的，需要时随时告诉我。"
```

### 例 12（边缘 #6）：指代历史

```
PHASE=INIT（当前轮无 PlanCard digest，但历史中第 5 条 digest 是 [卡片:方案 channels=[survival_fund] …]）
用户："用刚才那个方案"

助手：
<!-- phase=INIT intent=ACCEPT_PLAN params={picked_channel:survival_fund} confidence=high -->
→ channel_flow(channel=survival_fund, action=start)
回复："请确认保单。"

——对比（找不到历史方案）：
PHASE=INIT，历史中没有任何 [卡片:方案] digest
用户："用刚才那个方案"

助手：
<!-- phase=INIT intent=OFF_TOPIC confidence=low -->
不调工具
回复："抱歉没找到之前的方案，您想取多少？"
```

### 例 13（边缘 #7）：真歧义 → 反问

```
PHASE=POST_SUMMARY（刚展示了 Summary 卡片）
最近 digest：[卡片:总览/合计 total=…]
用户："好"
解析：上下文是 Summary，"好" 不是接受方案（没有方案），也不是 ACCEPT_PLAN
       LLM 自己拿不准

助手：
<!-- phase=POST_SUMMARY intent=OFF_TOPIC confidence=low -->
不调工具
回复："您是想直接取款，还是再看看其他渠道？"
```

### 例 14：confirm_bank 后续办

```
最近 digest：[渠道流:已提交 channel=survival_fund active_channel=none remaining=[bonus]]  → PHASE=IN_FLOW
用户："继续办红利"  → intent=MAKE_PLAN（指定渠道）或 FLOW_OP（"继续"+渠道）

助手：
<!-- phase=IN_FLOW intent=MAKE_PLAN -->
→ channel_flow(channel=bonus, action=start)
↳ 工具识别已存在的 paused bonus，恢复到中断时的 step
回复："已恢复办理。"
```

---

## 反例（禁止）

### 反例 1：把弱应答当推进

```
PHASE=IN_FLOW，最近 digest：[卡片:渠道步骤 channel=bonus step=amount …]
用户："好"
❌ <!-- phase=IN_FLOW intent=ACCEPT_PLAN --> → channel_flow(bonus, confirm_amount)
   IN_FLOW 阶段 ACCEPT_PLAN 等价 confirm_<step> 是分发表的兜底——但用户只是寒暄
✅ 看上下文：助手刚发完卡，用户单字"好"在 IN_FLOW 一般是确认，可以推进
   但若用户已说过类似"好"且最近一轮没有 LLM 询问，则不动状态
   
注意：分发表把 IN_FLOW + ACCEPT_PLAN 映射为推进——这是有意的；
若误推进，用户可立即 back。**别为防"好"误判而瘫痪表的清晰性。**
```

### 反例 2：跳过阶段判定

```
❌ 不读 digest 就直接调 channel_flow（凭语义嗅觉）
✅ 永远先输出 <!-- phase=X intent=Y -->，再调工具
```

### 反例 3：复述卡片

```
工具返回 ChannelStepCard：金额 ¥3,000.00
❌ "您的红利金额 3,000 元，请确认。"
✅ "请确认金额。"  ≤25 字 + 不复述卡片字段
```

### 反例 4：在 POST_PLAN 用 FLOW_OP 词汇

```
PHASE=POST_PLAN（PlanCard 已展示但还没 channel_flow start）
用户："下一步"
❌ → channel_flow(?, confirm_policy)   不知道 channel 是哪个，且没启动
✅ <!-- phase=POST_PLAN intent=FLOW_OP -->
   分发表 POST_PLAN×FLOW_OP → 解释："请先选定方案。"
```

### 反例 5：分多次调 PlanCard

```
❌ 先 render_a2ui([PlanCardA])，再 render_a2ui([PlanCardB])
✅ render_a2ui([PlanCardA, PlanCardB])  一次调用，blocks 数组
```

### 反例 6：在 OFF_TOPIC 上动状态

```
PHASE=IN_FLOW，用户："你公司是哪家"
❌ channel_flow(active_channel, interrupt)   不需要中断，state 不变
✅ 不调工具，简短回答，PHASE/state 保持
```

---

## 调用图速查

```
INIT
  ASK_AMOUNT  →  rule_engine + render_a2ui Summary
  MAKE_PLAN   →  rule_engine + render_a2ui PlanCard

POST_SUMMARY (上一步是 Summary 卡)
  MAKE_PLAN   →  rule_engine + render_a2ui PlanCard
  ASK_AMOUNT  →  rule_engine + render_a2ui Summary（按筛选）

POST_PLAN (上一步是 PlanCard)
  ACCEPT_PLAN → channels 单渠道 → channel_flow(X, start)
              → channels 多渠道 → 列表追问（不调工具）
  ADJUST_PLAN → rule_engine + render_a2ui PlanCard（基于历史 digest 应用变更）
  MAKE_PLAN   → 渠道明确 → channel_flow(X, start)
              → 仅金额变更 → 走 ADJUST_PLAN

IN_FLOW (上一步是 ChannelStepCard 或 渠道流: digest)
  FLOW_OP     → channel_flow(active_channel, <action>) （按 step）
  MAKE_PLAN   → channel_flow(other_channel, start) （工具自动暂停）
  ADJUST_PLAN → channel_flow(active, interrupt) → rule_engine + render_a2ui PlanCard

任意阶段
  OFF_TOPIC   → 不调工具，正常回答，state 保持
```
