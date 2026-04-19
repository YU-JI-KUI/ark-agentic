# 阶段 3：方案确认

## 目标

向用户展示取款方案卡片，等待用户选择并确认后提交阶段数据。

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

2. 向用户说明方案内容，等待用户明确确认（"确认方案1"/"就第一个"/"办理"等）。

3. 用户确认后，收集以下信息：

   | 字段 | 说明 |
   |------|------|
   | `confirmed` | 用户是否确认（true） |
   | `selected_option` | 选中的方案，含 `channels`（渠道列表）和 `target`（目标金额） |
   | `amount` | 最终取款金额（元） |

## 阶段提交

用户确认后，调用 `commit_flow_stage` 提交本阶段：

```
commit_flow_stage(
    stage_id="plan_confirm",
    user_data={
        "confirmed": true,
        "selected_option": {
            "channels": ["survival_fund", "bonus"],
            "target": 50000
        },
        "amount": 50000.0
    }
)
```

> 所有字段均为 **user 来源**，必须通过 user_data 提供。

提交后调用 `withdraw_money_flow_evaluator` → 进入 execute 阶段。

## 完成条件

- `confirmed = true`
- `selected_option` 包含用户选择的渠道和目标金额
- `amount` > 0
