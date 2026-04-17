# 阶段 3：方案确认（wait_for_user）

## 目标

向用户展示取款方案卡片，等待用户选择并确认。

> **重要**：本阶段 `wait_for_user=true`，evaluator 将返回 `WAIT_FOR_USER` 信号。
> 框架会立即终止 ReAct 循环，等待用户下一轮输入。
> **严禁**在此阶段直接进入执行步骤。

## 操作步骤

1. 基于 `options_query` 阶段数据，调用 `render_a2ui` 展示推荐方案卡片（PlanCard）。

   推荐展示 2 个方案（推荐 + 备选），参考渠道优先级：
   ```json
   [
     {"type": "WithdrawPlanCard", "data": {
       "channels": ["survival_fund", "bonus"],
       "target": 0,
       "title": "★ 推荐：零成本领取",
       "tag": "(不影响保障)",
       "reason": "优先使用零成本渠道，不影响保险保障。"
     }},
     {"type": "WithdrawPlanCard", "data": {
       "channels": ["survival_fund", "bonus", "policy_loan"],
       "target": 0,
       "title": "零成本 + 保单贷款",
       "tag": "(部分需付利息)",
       "reason": "备选方案：如需保留零成本额度，可用保单贷款补充。"
     }}
   ]
   ```

2. 调用 `withdraw_money_flow_evaluator` → 收到 `flow_status=in_progress, wait_for_user=true` → 框架硬中断。

3. 等待用户下一轮确认输入。

## 用户确认后（下一轮）

用户说"确认方案1"/"办理"/"就第一个"等确认语时：

1. 从上轮 PlanCard digest 中读取 `channels` 和 `target`
2. 写入阶段完成数据：

```python
metadata={"state_delta": {
    "_flow_context.stage_plan_confirm": {
        "confirmed": True,
        "selected_option": {
            "channels": ["survival_fund", "bonus"],
            "target": 50000,
        },
        "amount": 50000.0,
    }
}}
```

3. 再次调用 `withdraw_money_flow_evaluator` → 进入 execute 阶段。

## 完成条件

- `confirmed = true`
- `selected_option` 包含用户选择的渠道和金额
- `amount` > 0
