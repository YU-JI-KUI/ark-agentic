# 阶段 4：执行取款

## 目标

提交取款操作，等待系统处理结果，并向用户展示执行状态。

## 操作步骤

1. `submit_withdrawal` 触发外部业务流程。
2. 向用户告知提交状态（一句话，含金额和预计到账时间）。

## 异常处理

- `submit_withdrawal` 返回错误 → 告知用户失败原因，不调用 commit_flow_stage（流程停在 execute 阶段，可重试）
- 网络超时 → 提示用户稍后查询取款状态，不调用 commit_flow_stage
- 用户希望修改方案 → 参照 SKILL.md「流程回退」规则，回退到 plan_confirm 阶段重新执行

## 输出约束

- 禁止用 Markdown 表格展示金额明细
- 若需展示取款凭证，调用 `render_a2ui` 渲染 WithdrawSummaryHeader 卡片
- 回复文字 ≤ 30 字
