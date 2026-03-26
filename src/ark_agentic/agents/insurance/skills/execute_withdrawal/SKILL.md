---
name: 取款执行
description: 用户明确确认办理取款操作时，调用 submit_withdrawal 工具提交业务流程。本技能仅负责确认后的提交动作，不渲染卡片、不调用规则引擎。如果用户仍在咨询方案或查询额度，请使用 withdraw_money 技能。
version: "2.0.0"
invocation_policy: auto
group: insurance
tags:
  - withdrawal
  - execute
  - confirmation
---

# 取款执行技能

当用户已确认取款方案并使用明确确认短语时，调用 `submit_withdrawal` 工具提交办理请求。

## 触发条件

用户使用以下确认短语之一，且保单号、金额、操作类型信息齐全：
- "确认办理"
- "确认领取"
- "确认贷款"
- "确认退保"

**不触发**的情况：
- 用户在询问"能取多少"、"帮我规划方案"等咨询类问题 → 由 `withdraw_money` 技能处理
- 用户对已有方案提出修改意见（如"不要贷款"、"少取一点"） → 由 `withdraw_money` 技能处理
- 用户说"帮我办理"但未提供具体保单号或金额 → 先追问补齐信息

## 执行步骤

### 1. 信息提取与校验

从对话上下文提取以下关键信息：
- **操作类型**（operation_type）：参照下方枚举映射表
- **保单列表**（policies）：每项包含 `policy_no`（保单号）和 `amount`（金额）

如果信息不全，先追问："请确认保单号和金额。"

### 2. operation_type 枚举映射

| 用户表述 | operation_type 值 |
|---------|------------------|
| 生存金领取 | `shengcunjin` |
| 红利领取 | `bonus` |
| 保单贷款 | `loan` |
| 部分领取 | `partial` |
| 退保 | `surrender` |

### 3. 调用工具

信息齐全后，调用 `submit_withdrawal` 工具：

```json
{
  "operation_type": "bonus",
  "policies": [
    {"policy_no": "P001", "amount": "5000"}
  ]
}
```

## 禁止事项

- **禁止**调用 `render_a2ui`
- **禁止**调用 `rule_engine`
- **禁止**自行编造办理成功提示（工具会返回标准回复）
