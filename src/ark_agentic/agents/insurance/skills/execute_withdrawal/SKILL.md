---
name: 取款执行
description: 用户明确确认办理取款操作时，调用 submit_withdrawal 工具提交业务流程。本技能仅负责确认后的提交动作，不渲染卡片、不调用规则引擎。如果用户仍在咨询方案或查询额度，请使用 withdraw_money 技能。
version: "3.0.0"
invocation_policy: auto
group: insurance
tags:
  - withdrawal
  - execute
  - confirmation
---

# 取款执行技能

当用户确认办理取款方案时，分析方案包含的渠道，必要时追问用户要办理哪个渠道，然后调用 `submit_withdrawal` 工具。

## 触发条件

用户使用以下确认短语之一：
- "确认办理"、"确认领取"、"确认贷款"、"确认退保"
- "办理方案X"、"就第X个"

**不触发**：
- 咨询类问题（"能取多少"、"帮我规划"） → `withdraw_money` 技能
- 方案调整（"不要贷款"、"少取一点"） → `withdraw_money` 技能

## 执行步骤

### 1. 方案分析（最关键）

从对话上下文找到用户确认的那个 `WithdrawPlanCard`，读取其 `channels` 数组。

**判断渠道数量：**

- **单渠道**（如 `channels: ["policy_loan"]`）→ 跳到步骤 3，直接调用工具
- **多渠道**（如 `channels: ["survival_fund", "bonus"]` 或 `channels: ["survival_fund", "bonus", "policy_loan"]`）→ 进入步骤 2 追问

> ⚠️ 注意："零成本"方案通常包含 `survival_fund` + `bonus` 两个渠道，它们是**两个独立操作**，必须分开办理。

### 2. 多渠道追问

从上文 `rule_engine(action="list_options")` 的返回结果中，提取每个渠道对应的保单号和金额，列出后请用户选择：

> "该方案包含以下操作，每次只能办理一项，请确认要办理哪一个：
> 1. 生存金领取（POL001，12000 元）
> 2. 红利领取（POL002，5200 元）"

等待用户明确选择后，再进入步骤 3。

### 3. 提取信息并调用工具

从用户选定的渠道中提取：

- **operation_type**：按下方映射表转换
- **policies**：该渠道下的**所有保单**（同一渠道可能对应多张保单，全部包含）

**渠道 → operation_type 映射表：**

| WithdrawPlanCard channel | operation_type |
|--------------------------|----------------|
| `survival_fund`          | `shengcunjin`  |
| `bonus`                  | `bonus`        |
| `policy_loan`            | `loan`         |
| `partial_withdrawal`     | `partial`      |
| `surrender`              | `surrender`    |

调用 `submit_withdrawal`：

```json
{
  "operation_type": "shengcunjin",
  "policies": [
    {"policy_no": "POL001", "amount": "12000"}
  ]
}
```

## 正例

```
对话上下文:
  rule_engine 返回 survival_fund: POL001/12000, bonus: POL002/5200
  方案1 channels=["survival_fund","bonus"], target=17200

用户: "确认办理方案1"
助手: "该方案包含两笔操作，每次只能办理一项：
       1. 生存金领取（POL001，12000元）
       2. 红利领取（POL002，5200元）
       请确认要办理哪一项？"
用户: "办理生存金"
助手: → submit_withdrawal(operation_type="shengcunjin", policies=[{policy_no:"POL001", amount:"12000"}])
```

## 反例（禁止）

```
用户: "确认办理方案1"（方案1 = 生存金 12000 + 红利 5200）
❌ submit_withdrawal(operation_type="bonus", policies=[{policy_no:"POL002", amount:"20000"}])
   错误1: operation_type 随意选择了 bonus
   错误2: amount 用了方案总额 20000 而非该渠道金额 5200
```

## 金额规则（最高优先级）

- **金额必须是该渠道的实际金额**，不是方案的 target 总额
- 例：方案 target=20000，但 bonus 渠道只有 5200 → amount 填 "5200"

## 禁止事项

- **禁止**调用 `render_a2ui`
- **禁止**调用 `rule_engine`
- **禁止**自行编造办理成功提示（工具会返回标准回复）
- **禁止**对多渠道方案一次性提交 — 必须先追问用户选择
