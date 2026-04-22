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

## 异常处理

- 用户明确拒绝所有方案 → 询问是否需要修改取款金额或终止流程，不调用 collect_user_fields
- 用户要求修改金额 → 重新调用 `rule_engine` 查询（返回阶段 2）再重新展示方案卡片
- `render_a2ui` 渲染失败 → 以文本形式向用户描述方案内容，继续收集确认信息
