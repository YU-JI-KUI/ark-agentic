# 阶段 4：执行取款

## 目标

提交取款操作，等待系统处理结果，并向用户展示执行状态。

## 操作步骤

1. 从 `_flow_context.stage_plan_confirm` 读取用户确认的方案：
   - `selected_option.channels`：取款渠道列表
   - `amount`：取款金额

2. 调用 `submit_withdrawal(operation_type=<channel>)` 触发外部业务流程。

   `submit_withdrawal` 写入 `_submitted_channels`（已触发渠道列表），
   并发送 `start_flow` 事件到前端启动 RPA 流程。

3. 向用户告知提交状态（一句话，含金额和预计到账时间）。

## 阶段提交

`submit_withdrawal` 调用完成后，调用 `commit_flow_stage` 提交本阶段：

```
commit_flow_stage(stage_id="execute")
```

> `submitted` 和 `channels` 均为 **tool 来源**，
> 框架自动从 `_submitted_channels` 中提取：
> - `submitted` ← `bool(_submitted_channels)`
> - `channels` ← `_submitted_channels`（渠道名列表）
>
> **无需在 user_data 中传递**。

4. 调用 `withdraw_money_flow_evaluator` → 返回 `flow_status=completed` → 流程结束。

## 完成条件

- `submitted = true`
- `channels` 非空列表

## 异常处理

- `submit_withdrawal` 返回错误 → 告知用户失败原因，不调用 commit_flow_stage（流程停在 execute 阶段，可重试）
- 网络超时 → 提示用户稍后查询取款状态，不调用 commit_flow_stage

## 输出约束

- 禁止用 Markdown 表格展示金额明细
- 若需展示取款凭证，调用 `render_a2ui` 渲染 WithdrawSummaryHeader 卡片
- 回复文字 ≤ 30 字
