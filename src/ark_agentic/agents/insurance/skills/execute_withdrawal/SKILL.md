---
name: 取款执行
description: 用户选择办理某个取款渠道时，调用 submit_withdrawal 工具唤起业务流程。本技能仅负责提交动作，不渲染卡片、不调用规则引擎。如果用户仍在咨询方案或查询额度，请使用 withdraw_money 技能。
version: "6.0.0"
invocation_policy: auto
group: insurance
tags:
  - withdrawal
  - execute
required_tools:
  - submit_withdrawal
---

# 取款执行技能

调用 `submit_withdrawal` 唤起办理流程。工具自动从方案数据获取保单和金额，**LLM 只需传 `operation_type`**。

> **STOP 约束**：`submit_withdrawal` 会触发 STOP，调用后你**不能再发言**。所有澄清、渠道选择、剩余渠道提醒，都必须写在调用工具**之前**的文字里。

## 前置条件

1. 对话中**必须已展示过取款方案卡片**（即已调用过 `render_a2ui` 渲染 `WithdrawPlanCard`）
2. 如果未展示过方案，回复："需要先查询一下您的可取额度" 并**停止**，由 `withdraw_money` 技能接管

## 触发条件

用户表达了对某个取款渠道的办理意愿：
- 选择方案："办理方案1"、"就第一个"、"第一个吧"
- 选择渠道："领生存金"、"办理贷款"、"要红利"
- 按钮触发："办理生存金领取，POL001，12000.00"
- 上轮提交后继续："红利也办一下"、"继续"

**不触发**（转 `withdraw_money` 技能）：
- 咨询类："能取多少"、"帮我规划"
- 方案调整："不要贷款"、"少取一点"、"换个方案"

如果用户说"不"、"算了"、"再看看"，则**不执行**，回到方案咨询阶段。

---

## 决策树（必须从上到下逐步执行）

> **绝对禁止**：不经过下面三步就直接调用 `submit_withdrawal`。

### STEP 0 — 续办检查

查看对话历史中**最近的 `submit_withdrawal` 工具结果**。

- 如果结果包含"还有{X}待办理"：主动询问用户是否继续
  > "上次已办理了生存金领取，还有红利领取(¥5,200.00)，需要继续办理吗？"
  - 用户同意 → 跳到 **STEP 2**
  - 用户拒绝 → 结束
- 没有此类结果 → 进入 **STEP 1**

### STEP 1 — 渠道计数

读取 `render_a2ui` 工具结果中的方案摘要（digest），找到用户选择的方案，**数 `channels` 字段的数量**。

digest 格式示例：
```
[已向用户展示卡片] 方案: ★ 推荐: 零成本领取 | channels: ["survival_fund", "bonus"] | 总额: ¥17,200.00 | 明细: ...
方案: 保单贷款 | channels: ["policy_loan"] | 总额: ¥20,000.00 | 明细: ...
```

- **1 个渠道** → 跳到 **STEP 2**
- **2+ 个渠道** → 列出渠道让用户选择，**不要调用工具**：
  > "这个方案包含两项，每次办理一项，您想先办理哪个？
  > 1. 生存金领取(¥12,000.00)
  > 2. 红利领取(¥5,200.00)"
  - 等用户回复选择后 → 进入 **STEP 2**

### STEP 2 — 提交（带上下文）

你的文字回复**必须包含**：
1. 正在办理什么："正在帮您办理{X}"
2. 如果同方案还有未办理渠道："该方案还有{Y}(¥Z)，办完可以继续办理"

然后调用工具：`submit_withdrawal(operation_type=...)`

---

## 渠道 → operation_type 映射表

| 渠道 channel           | operation_type | 中文名   |
|------------------------|----------------|----------|
| `survival_fund`        | `shengcunjin`  | 生存金领取 |
| `bonus`                | `bonus`        | 红利领取   |
| `policy_loan`          | `loan`         | 保单贷款   |
| `partial_withdrawal`   | `partial`      | 部分领取   |
| `surrender`            | `surrender`    | 退保       |

---

## 正例

### 例 1：多渠道方案 — 列出渠道 → 用户选择 → 提交并提醒剩余

```
digest: 方案: ★ 推荐: 零成本领取 | channels: ["survival_fund", "bonus"] | 总额: ¥17,200.00

用户: "就零成本方案"
助手（STEP 1 — 2个渠道，需要问）:
  "这个方案包含两项，每次办理一项，您想先办理哪个？
   1. 生存金领取(¥12,000.00)
   2. 红利领取(¥5,200.00)"

用户: "先领生存金"
助手（STEP 2 — 提交+提醒剩余）:
  "正在帮您办理生存金领取~该方案还有红利领取(¥5,200.00)，办完可以继续办理"
  → submit_withdrawal(operation_type="shengcunjin")
```

### 例 2：续办 — 上轮提交后用户回来继续

```
上轮 submit_withdrawal 结果: "已启动生存金领取办理流程。还有红利领取(¥5,200.00)待办理"

用户: "红利也办一下"
助手（STEP 0 — 续办）:
  "正在帮您办理红利领取"
  → submit_withdrawal(operation_type="bonus")
```

### 例 3：单渠道方案 — 直接办理

```
digest: 方案: 保单贷款 | channels: ["policy_loan"] | 总额: ¥20,000.00

用户: "办理方案2"
助手（STEP 1 — 1个渠道，直接 STEP 2）:
  "正在帮您办理保单贷款"
  → submit_withdrawal(operation_type="loan")
```

### 例 4：按钮触发（结构化消息）

```
用户: "办理生存金领取，POL001，12000.00"
助手（按钮已含渠道，直接 STEP 2）:
  "正在帮您办理生存金领取"
  → submit_withdrawal(operation_type="shengcunjin")
```

## 反例（禁止）

### 反例 1：多渠道方案未追问直接提交

```
digest: channels: ["survival_fund", "bonus"]
用户: "就方案一"
❌ 直接调用 submit_withdrawal(operation_type="shengcunjin")
✅ 先列出两个渠道让用户选择，用户选定后再提交
```

### 反例 2：提交时未提醒剩余渠道

```
digest: channels: ["survival_fund", "bonus"]，用户选了生存金
❌ 助手: "正在帮您办理生存金领取" → submit（没提红利）
✅ 助手: "正在帮您办理生存金领取~该方案还有红利领取(¥5,200)，办完可以继续" → submit
```

### 反例 3：operation_type 映射错误

```
用户: "领生存金"
❌ submit_withdrawal(operation_type="survival_fund")
✅ submit_withdrawal(operation_type="shengcunjin")
```

## 禁止事项

- **禁止**调用 `render_a2ui`
- **禁止**调用 `rule_engine`
- **禁止**自行编造办理成功提示（工具会返回标准回复）
- **禁止**跳过决策树直接调用 `submit_withdrawal`
- **禁止**向 `submit_withdrawal` 传递 `operation_type` 以外的参数
- **禁止**额外确认环节 — 工具只是唤起流程，后续有独立确认页面
- **禁止**按方案名猜渠道数量 — 必须读 digest 中的 `channels` 字段
